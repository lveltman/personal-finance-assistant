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


def parse_file(file_bytes: bytes, filename: str) -> list[dict]:
    """
    Parse xlsx or csv bytes into list of {date, amount, merchant, category}.
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


def _to_records(df: pd.DataFrame) -> list[dict]:
    records = []
    skipped = 0
    for _, row in df.iterrows():
        try:
            amount = float(str(row["amount"]).replace(",", ".").replace(" ", "").replace("\xa0", ""))
            date_raw = row["date"]
            if pd.isna(date_raw):
                skipped += 1
                continue
            if isinstance(date_raw, (datetime,)):
                date_str = date_raw.strftime("%Y-%m-%d")
            else:
                parsed = pd.to_datetime(str(date_raw), dayfirst=True, errors="coerce")
                if pd.isna(parsed):
                    skipped += 1
                    continue
                date_str = parsed.strftime("%Y-%m-%d")

            merchant = str(row.get("merchant", "Неизвестно")).strip()
            category = str(row.get("category", "")).strip() if "category" in df.columns else ""

            try:
                tx = Transaction(
                    date=date_str,
                    amount=abs(amount),
                    merchant=merchant,
                    category=category,
                )
                records.append(tx.model_dump())
            except ValidationError:
                skipped += 1
        except (ValueError, TypeError):
            skipped += 1

    if skipped:
        log.info("file_parser_skipped", skipped=skipped)
    if not records:
        raise ValueError("Файл не содержит корректных транзакций. Проверьте формат данных.")

    log.info("file_parsed", rows=len(records))
    return records
