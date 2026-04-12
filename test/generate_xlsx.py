"""Generate .xlsx test fixtures. Run: python test/generate_xlsx.py"""
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "fixtures"
OUT.mkdir(exist_ok=True)


def save(df: pd.DataFrame, name: str) -> None:
    path = OUT / name
    df.to_excel(path, index=False)
    print(f"  created: {path.name}")


print("Generating xlsx fixtures...")

# 11 — normal xlsx, English columns
save(pd.DataFrame([
    {"date": "2026-03-01", "amount": 450,  "merchant": "Starbucks"},
    {"date": "2026-03-02", "amount": 1200, "merchant": "Лента"},
    {"date": "2026-03-03", "amount": 350,  "merchant": "KFC"},
    {"date": "2026-03-05", "amount": 850,  "merchant": "Яндекс Такси"},
    {"date": "2026-03-07", "amount": 299,  "merchant": "Netflix"},
    {"date": "2026-03-10", "amount": 2300, "merchant": "Wildberries"},
    {"date": "2026-03-12", "amount": 180,  "merchant": "Starbucks"},
    {"date": "2026-03-15", "amount": 640,  "merchant": "McDonald's"},
    {"date": "2026-03-18", "amount": 950,  "merchant": "Перекрёсток"},
    {"date": "2026-03-20", "amount": 1500, "merchant": "DNS"},
]), "11_normal_en.xlsx")

# 12 — Tinkoff-style export (дата, сумма операции, описание)
save(pd.DataFrame([
    {"Дата операции": "01.03.2026 10:23:00", "Сумма операции": -450.00, "Описание": "STARBUCKS COFFEE"},
    {"Дата операции": "02.03.2026 14:05:00", "Сумма операции": -1200.00, "Описание": "ЛЕНТА"},
    {"Дата операции": "03.03.2026 19:11:00", "Сумма операции": -350.00, "Описание": "KFC МЕГА"},
    {"Дата операции": "04.03.2026 09:00:00", "Сумма операции": +5000.00, "Описание": "Пополнение счёта"},
    {"Дата операции": "05.03.2026 11:30:00", "Сумма операции": -850.00, "Описание": "YANDEX.TAXI"},
    {"Дата операции": "07.03.2026 08:44:00", "Сумма операции": -299.00, "Описание": "NETFLIX.COM"},
]), "12_tinkoff_style.xlsx")

# 13 — big file (500 rows)
import random, datetime
random.seed(42)
merchants = [
    ("Starbucks", "Кофе"), ("Лента", "Продукты"), ("KFC", "Фастфуд"),
    ("Яндекс Такси", "Такси"), ("Netflix", "Подписки"), ("Wildberries", "Маркетплейсы"),
    ("McDonald's", "Фастфуд"), ("Перекрёсток", "Продукты"), ("DNS", "Электроника"),
    ("Аптека Ригла", "Аптека"),
]
rows = []
start = datetime.date(2026, 1, 1)
for i in range(500):
    merchant, category = random.choice(merchants)
    d = start + datetime.timedelta(days=random.randint(0, 89))
    rows.append({"date": d.isoformat(), "amount": round(random.uniform(50, 5000), 2),
                 "merchant": merchant, "category": category})
save(pd.DataFrame(rows), "13_big_500rows.xlsx")

# 14 — all zero amounts (edge case)
save(pd.DataFrame([
    {"date": "2026-03-01", "amount": 0, "merchant": "Тест"},
    {"date": "2026-03-02", "amount": 0, "merchant": "Тест2"},
]), "14_zero_amounts.xlsx")

# 15 — semicolon-separated (wrong format but xlsx wrapping)
save(pd.DataFrame([
    {"date": "2026-03-01", "amount": 450, "merchant": "Starbucks", "extra_col": "ignore me"},
    {"date": "2026-03-02", "amount": 1200, "merchant": "Лента", "extra_col": "and me too"},
]), "15_extra_columns.xlsx")

print("Done.")
