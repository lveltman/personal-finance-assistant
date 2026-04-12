"""Convert LLM markdown output to Telegram HTML."""
import html
import re


def md_to_html(text: str) -> str:
    """Convert common markdown patterns to Telegram-compatible HTML."""
    # Escape HTML special chars first
    text = html.escape(text)

    # **bold** and __bold__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)

    # *italic* and _italic_ (single, not double)
    text = re.sub(r"\*([^*\n]+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # `code`
    text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)

    return text
