"""LangGraph ReAct orchestrator with Mistral → GPT-4o-mini fallback."""
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src import config, metrics
from src.agent import prompts
from src.agent.callbacks import ToolLoggingCallback
from src.agent.guard import GuardRefusal, run_preflight
from src.agent.tools import ALL_TOOLS, set_context
from src.core import session as session_store

log = structlog.get_logger()


def _build_llm():
    """Build LLM with Mistral primary and GPT-4o-mini fallback."""
    mistral = ChatMistralAI(
        model=config.LLM_MODEL,
        api_key=config.MISTRAL_API_KEY,
        timeout=30,
        max_retries=2,
    )
    openai = ChatOpenAI(
        model=config.LLM_FALLBACK_MODEL,
        api_key=config.OPENAI_API_KEY,
        timeout=30,
        max_retries=2,
    )
    return mistral.with_fallbacks([openai])


_llm = None
_agent = None


def _build_langfuse_handler():
    """Return Langfuse callback handler if enabled, else None."""
    if not config.LANGFUSE_ENABLED:
        return None
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_HOST,
        )
    except Exception as e:
        log.warning("langfuse_init_failed", error=str(e))
        return None


_langfuse_handler = None
_langfuse_initialized = False


def _get_agent():
    global _llm, _agent, _langfuse_handler, _langfuse_initialized
    if _agent is None:
        _llm = _build_llm()
        _agent = create_react_agent(
            model=_llm,
            tools=ALL_TOOLS,
        )
        log.info("agent_created", model=config.LLM_MODEL, fallback=config.LLM_FALLBACK_MODEL)
    if not _langfuse_initialized:
        _langfuse_handler = _build_langfuse_handler()
        _langfuse_initialized = True
        if _langfuse_handler:
            log.info("langfuse_tracing_enabled", host=config.LANGFUSE_HOST)
    return _agent


async def process_message(telegram_id: int, user_text: str) -> str:
    """
    Main entry point. Runs pre-flight → ReAct agent → returns response text.
    """
    import time as _time
    _t0 = _time.time()
    user_hash = session_store.get_user_hash(telegram_id)
    metrics.active_requests.inc()

    # Pre-flight guard (deterministic, no LLM)
    try:
        clean_text = run_preflight(user_hash, user_text)
    except GuardRefusal as e:
        metrics.active_requests.dec()
        metrics.requests_total.labels(status="blocked").inc()
        return str(e)

    # Load session
    sess = session_store.load_session(user_hash)

    # Init agent first so _llm is populated before injecting into tools
    agent = _get_agent()

    # Inject session + LLM into tools via contextvars
    set_context(user_hash, sess, llm=_llm)

    # Build messages: system prompt + conversation history + current message
    system_prompt = prompts.build_system_prompt(sess)
    messages = [SystemMessage(content=system_prompt)]

    history = sess.get("conversation_history", [])
    for msg in history[-config.CONVERSATION_HISTORY_LIMIT:]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            from langchain_core.messages import AIMessage
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=clean_text))
    try:
        callbacks = [ToolLoggingCallback(user_hash=user_hash)]
        if _langfuse_handler:
            callbacks.append(_langfuse_handler)
        result = await agent.ainvoke(
            {"messages": messages},
            config={
                "recursion_limit": config.LLM_MAX_STEPS * 2,
                "callbacks": callbacks,
            },
        )
        # Extract final AI response
        final_message = result["messages"][-1]
        response_text = final_message.content
    except Exception as e:
        log.error("agent_error", error=str(e), user_hash=user_hash)
        metrics.errors_total.labels(component="orchestrator").inc()
        metrics.requests_total.labels(status="error").inc()
        response_text = (
            "⚠️ Произошла ошибка при обработке запроса. "
            "Попробуй ещё раз или пришли данные заново."
        )
    else:
        metrics.requests_total.labels(status="success").inc()
    finally:
        metrics.active_requests.dec()
        metrics.request_duration.labels(status="success").observe(_time.time() - _t0)

    # Save conversation history
    session_store.append_conversation(sess, "user", user_text)
    session_store.append_conversation(sess, "assistant", response_text)
    session_store.save_session(user_hash, sess)

    return response_text


async def process_file(telegram_id: int, file_bytes: bytes, filename: str) -> str:
    """Parse uploaded file and store transactions in session."""
    from datetime import datetime

    from src.core.categorizer import batch_categorize
    from src.core.file_parser import parse_file

    user_hash = session_store.get_user_hash(telegram_id)
    sess = session_store.load_session(user_hash)
    _get_agent()  # ensure _llm is initialized

    try:
        transactions, skipped_rows = parse_file(file_bytes, filename)
    except ValueError as e:
        return f"❌ Ошибка при разборе файла: {e}"

    # Categorize transactions (keyword rules → LLM fallback)
    transactions = batch_categorize(transactions, llm=_llm)

    # Merge with existing transactions (deduplicate by date+amount+merchant)
    existing = sess.get("transactions", [])
    existing_keys = {
        (tx["date"], tx["amount"], tx["merchant"])
        for tx in existing
    }
    new_txs = [
        tx for tx in transactions
        if (tx["date"], tx["amount"], tx["merchant"]) not in existing_keys
    ]
    merged = existing + new_txs

    sess["transactions"] = merged
    sess["last_file_ts"] = datetime.utcnow().isoformat()
    session_store.save_session(user_hash, sess)

    from src.core.limit_engine import get_spending_summary
    summary = get_spending_summary(merged, "month")
    top = "\n".join(
        f"  • {cat}: {amount:.0f}₽"
        for cat, amount in summary["top_categories"]
    )
    added_count = len(new_txs)
    dup_count = len(transactions) - added_count
    dup_note = f" (пропущено дублей: {dup_count})" if dup_count else ""
    msg = (
        f"✅ Добавлено {added_count} новых транзакций из {filename}{dup_note}\n"
        f"Всего в базе: {len(merged)}\n\n"
        f"📊 Расходы за текущий месяц: {summary['total']:.0f}₽\n"
        f"Топ категории:\n{top}\n\n"
        f"Задавай вопросы про свои расходы!"
    )
    if skipped_rows:
        lines = [f"\n⚠️ Пропущено строк из файла: {len(skipped_rows)}"]
        for s in skipped_rows[:5]:
            raw = s["raw"]
            date_hint = raw.get("date", "")
            merchant_hint = raw.get("merchant", "")
            if date_hint and date_hint != "nan":
                hint = f"напиши: «{date_hint} {merchant_hint} <сумма>₽»"
            elif merchant_hint and merchant_hint != "nan":
                hint = f"напиши: «{merchant_hint} <сумма>₽»"
            else:
                hint = "добавь вручную текстом"
            lines.append(f"  • Строка {s['row']}: {s['reason']} → {hint}")
        if len(skipped_rows) > 5:
            lines.append(f"  • ... и ещё {len(skipped_rows) - 5} строк")
        msg += "\n".join(lines)
    return msg
