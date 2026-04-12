"""LangGraph ReAct orchestrator with Mistral → GPT-4o-mini fallback."""
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src import config
from src.agent import prompts
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


def _get_agent():
    global _llm, _agent
    if _agent is None:
        _llm = _build_llm()
        _agent = create_react_agent(
            model=_llm,
            tools=ALL_TOOLS,
        )
        log.info("agent_created", model=config.LLM_MODEL, fallback=config.LLM_FALLBACK_MODEL)
    return _agent


async def process_message(telegram_id: int, user_text: str) -> str:
    """
    Main entry point. Runs pre-flight → ReAct agent → returns response text.
    """
    user_hash = session_store.get_user_hash(telegram_id)

    # Pre-flight guard (deterministic, no LLM)
    try:
        clean_text = run_preflight(user_hash, user_text)
    except GuardRefusal as e:
        return str(e)

    # Load session
    sess = session_store.load_session(user_hash)

    # Inject session context into tools via contextvars
    set_context(user_hash, sess)

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

    # Run ReAct agent
    agent = _get_agent()
    try:
        result = await agent.ainvoke(
            {"messages": messages},
            config={"recursion_limit": config.LLM_MAX_STEPS * 2},
        )
        # Extract final AI response
        final_message = result["messages"][-1]
        response_text = final_message.content
    except Exception as e:
        log.error("agent_error", error=str(e), user_hash=user_hash)
        response_text = (
            "⚠️ Произошла ошибка при обработке запроса. "
            "Попробуй ещё раз или пришли данные заново."
        )

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

    try:
        transactions = parse_file(file_bytes, filename)
    except ValueError as e:
        return f"❌ Ошибка при разборе файла: {e}"

    # Categorize transactions (keyword rules only for speed)
    transactions = batch_categorize(transactions)

    sess["transactions"] = transactions
    sess["last_file_ts"] = datetime.utcnow().isoformat()
    session_store.save_session(user_hash, sess)

    from src.core.limit_engine import get_spending_summary
    summary = get_spending_summary(transactions, "month")
    top = "\n".join(
        f"  • {cat}: {amount:.0f}₽"
        for cat, amount in summary["top_categories"]
    )
    return (
        f"✅ Загружено {len(transactions)} транзакций из {filename}\n\n"
        f"📊 Расходы за текущий месяц: {summary['total']:.0f}₽\n"
        f"Топ категории:\n{top}\n\n"
        f"Задавай вопросы про свои расходы!"
    )
