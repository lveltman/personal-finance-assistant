"""aiogram 3.x message handlers."""
import io

import structlog
from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src import config
from src.agent import orchestrator
from src.bot.formatting import md_to_html
from src.core import session as session_store

log = structlog.get_logger()
router = Router()

WELCOME_TEXT = (
    "👋 Привет! Я персональный финансовый ассистент.\n\n"
    "📁 Пришли мне файл с транзакциями (.xlsx или .csv) — я разберу расходы и помогу с анализом.\n\n"
    "После загрузки файла можно:\n"
    "• Спросить «покажи расходы за месяц»\n"
    "• «Установи лимит 500₽ в неделю на кофе»\n"
    "• «Где я трачу больше всего?»\n"
    "• «Можно ли сэкономить на фастфуде?»"
)

HELP_TEXT = (
    "📋 Что я умею:\n\n"
    "📁 Загрузка данных\n"
    "• Пришли файл .xlsx или .csv с транзакциями\n\n"
    "📊 Анализ расходов\n"
    "• «Покажи расходы за месяц/неделю»\n"
    "• «Сколько я трачу на кофе?»\n"
    "• «Топ категорий расходов»\n\n"
    "⚙️ Лимиты\n"
    "• «Установи лимит 3000₽ в месяц на рестораны»\n"
    "• «Покажи мои лимиты»\n"
    "• «Проверь нарушения лимитов»\n\n"
    "💡 Экономия\n"
    "• «Найди дешевле в категории кофе»\n"
    "• «Можно ли вернуть покупку в Ozon?»"
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    user_hash = session_store.get_user_hash(message.from_user.id)
    path = session_store._session_path(user_hash)
    path.unlink(missing_ok=True)
    await message.answer("🗑 Все данные удалены. Пришли новый файл для начала работы.")


@router.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    doc = message.document
    filename = doc.file_name or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ("xlsx", "xls", "csv"):
        await message.answer("❌ Поддерживаются только файлы .xlsx и .csv")
        return

    size_mb = (doc.file_size or 0) / (1024 * 1024)
    if size_mb > config.MAX_FILE_SIZE_MB:
        await message.answer(f"❌ Файл слишком большой: {size_mb:.1f}MB. Максимум {config.MAX_FILE_SIZE_MB}MB")
        return

    status_msg = await message.answer("⏳ Обрабатываю файл...")

    try:
        file = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        file_bytes = buf.getvalue()

        response = await orchestrator.process_file(message.from_user.id, file_bytes, filename)
        await status_msg.edit_text(response)
    except Exception as e:
        log.error("file_handler_error", error=str(e), user_id=message.from_user.id)
        await status_msg.edit_text("⚠️ Ошибка при обработке файла. Проверь формат и попробуй ещё раз.")


@router.callback_query(F.data.startswith("confirm:"))
async def handle_confirmation(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    user_hash = session_store.get_user_hash(callback.from_user.id)
    sess = session_store.load_session(user_hash)
    pending = sess.get("pending_confirmation")

    if not pending or pending.get("action") != action:
        await callback.answer("Действие устарело", show_alert=True)
        return

    import json
    params = json.loads(pending.get("params", "{}"))
    sess["pending_confirmation"] = None
    session_store.save_session(user_hash, sess)

    # Apply the action
    confirmation_text = f"Да, подтверждаю: {action} с параметрами {pending.get('params', '')}"
    await callback.message.edit_text("⏳ Применяю...")
    await callback.answer()

    # Resume agent so it can continue the conversation after confirmation
    try:
        response = await orchestrator.process_message(callback.from_user.id, confirmation_text)
        await callback.message.edit_text(md_to_html(response), parse_mode=ParseMode.HTML)
    except Exception as e:
        log.error("confirmation_handler_error", error=str(e))
        await callback.message.edit_text("✅ Действие выполнено.")


@router.callback_query(F.data == "cancel")
async def handle_cancel(callback: CallbackQuery) -> None:
    user_hash = session_store.get_user_hash(callback.from_user.id)
    sess = session_store.load_session(user_hash)
    sess["pending_confirmation"] = None
    session_store.save_session(user_hash, sess)
    await callback.message.edit_text("❌ Действие отменено")
    await callback.answer()


@router.message(F.text)
async def handle_text(message: Message) -> None:
    if not message.text:
        return

    status_msg = await message.answer("🤔 Думаю...")

    try:
        response = await orchestrator.process_message(message.from_user.id, message.text)

        # Check if response contains a pending confirmation
        user_hash = session_store.get_user_hash(message.from_user.id)
        sess = session_store.load_session(user_hash)
        pending = sess.get("pending_confirmation")

        if pending:
            action = pending.get("action", "confirm")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}"),
                InlineKeyboardButton(text="❌ Нет", callback_data="cancel"),
            ]])
            await status_msg.edit_text(md_to_html(response), reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            await status_msg.edit_text(md_to_html(response), parse_mode=ParseMode.HTML)

    except Exception as e:
        log.error("text_handler_error", error=str(e), user_id=message.from_user.id)
        await status_msg.edit_text("⚠️ Что-то пошло не так. Попробуй ещё раз.")
