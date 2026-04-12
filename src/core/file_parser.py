"""Parse .xlsx / .csv files into a list of transaction dicts."""
import io
from datetime import datetime

import chardet
import pandas as pd
import structlog
from pydantic import ValidationError

from src.core.models import Transaction

log = structlog.get_logger()

REQUIRED_COLUMNS_MAP = {
    # possible column name variants → normalized name
    "date": "date",
    "дата": "date",
    "transaction date": "date",
    "amount": "amount",
    "сумма": "amount",
    "sum": "amount",
    "merchant": "merchant",
    "мерчант": "merchant",
    "описание": "merchant",
    "description": "merchant",
    "name": "merchant",
    "category": "category",
    "категория": "category",
}


def parse_file(file_bytes: bytes, filename: str) -> tuple[list[dict], list[dict]]:
    """
    Parse xlsx or csv bytes into list of {date, amount, merchant, category}.
    Returns (records, skipped) where skipped is a list of {row, reason, raw}.
    Raises ValueError on bad format.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "xlsx" or ext == "xls":
        df = _read_excel(file_bytes)
    elif ext == "csv":
        df = _read_csv(file_bytes)
    else:
        raise ValueError(f"Unsupported file format: .{ext}. Please send .xlsx or .csv")

    df = _normalize_columns(df)
    return _to_records(df)


def _read_excel(data: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(data), engine="openpyxl")
    except Exception as e:
        raise ValueError(f"Cannot read Excel file: {e}") from e


def _read_csv(data: bytes) -> pd.DataFrame:
    detected = chardet.detect(data)
    encoding = detected.get("encoding") or "utf-8"
    try:
        return pd.read_csv(io.BytesIO(data), encoding=encoding, sep=None, engine="python")
    except Exception as e:
        raise ValueError(f"Cannot read CSV file: {e}") from e


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Build mapping from actual column → normalized name
    rename = {}
    for col in df.columns:
        normalized = REQUIRED_COLUMNS_MAP.get(col.strip().lower())
        if normalized:
            rename[col] = normalized
    df = df.rename(columns=rename)

    if "date" not in df.columns:
        raise ValueError("Файл не содержит колонку с датой. Ожидаемые названия: date, дата, transaction date")
    if "amount" not in df.columns:
        raise ValueError("Файл не содержит колонку с суммой. Ожидаемые названия: amount, сумма, sum")
    if "merchant" not in df.columns:
        # Try to use first non-date/amount column
        candidates = [c for c in df.columns if c not in ("date", "amount", "category")]
        if candidates:
            df = df.rename(columns={candidates[0]: "merchant"})
        else:
            raise ValueError("Файл не содержит колонку с названием merchant/магазина")

    return df


def _to_records(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    records = []
    skipped = []
    for i, row in df.iterrows():
        row_num = i + 2  # 1-based, +1 for header
        raw_preview = {k: str(row.get(k, ""))[:40] for k in ("date", "amount", "merchant") if k in df.columns}

        date_raw = row["date"]
        amount_raw_val = row["amount"]

        # Silently skip rows where both date and amount are missing (junk/empty rows)
        if pd.isna(date_raw) and pd.isna(amount_raw_val):
            continue

        # Validate amount
        if pd.isna(amount_raw_val):
            skipped.append({"row": row_num, "reason": "сумма не указана", "raw": raw_preview})
            continue
        try:
            amount_str = str(amount_raw_val).replace(",", ".").replace(" ", "").replace("\xa0", "")
            amount = float(amount_str)
        except (ValueError, TypeError):
            skipped.append({"row": row_num, "reason": "некорректная сумма", "raw": raw_preview})
            continue

        # Validate date
        if pd.isna(date_raw):
            skipped.append({"row": row_num, "reason": "дата отсутствует", "raw": raw_preview})
            continue
        if isinstance(date_raw, datetime):
            date_str = date_raw.strftime("%Y-%m-%d")
        else:
            parsed = pd.to_datetime(str(date_raw), dayfirst=True, errors="coerce")
            if pd.isna(parsed):
                skipped.append({"row": row_num, "reason": f"не удалось распознать дату '{date_raw}'", "raw": raw_preview})
                continue
            date_str = parsed.strftime("%Y-%m-%d")

        # Merchant: default to "Неизвестно" if missing
        merchant_raw = row.get("merchant") if "merchant" in df.columns else None
        merchant = str(merchant_raw).strip() if merchant_raw is not None and not pd.isna(merchant_raw) else "Неизвестно"

        raw_cat = row.get("category") if "category" in df.columns else None
        category = "" if raw_cat is None or pd.isna(raw_cat) else str(raw_cat).strip()

        try:
            tx = Transaction(date=date_str, amount=abs(amount), merchant=merchant, category=category)
            records.append(tx.model_dump())
        except ValidationError as e:
            skipped.append({"row": row_num, "reason": str(e.errors()[0]["msg"]), "raw": raw_preview})

    if skipped:
        log.info("file_parser_skipped", skipped=len(skipped))
    if not records:
        raise ValueError("Файл не содержит корректных транзакций. Проверьте формат данных.")

    log.info("file_parsed", rows=len(records))
    return records, skipped
