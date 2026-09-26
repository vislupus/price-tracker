"""Еднократен внос на старата история (data/hdd_data.csv, цени в лева) в SQLite.

Цените се превръщат в евро по фиксирания курс 1.95583 и се маркират
със source='legacy_bgn'. Продуктите влизат в категория „Архив (до 2025)“
като неактивни – виждат се в сайта, но не се проверяват.

    python scripts/import_legacy_csv.py                 # по подразбиране
    python scripts/import_legacy_csv.py стар.csv --db data/prices.db

Може да се пусне повторно – вече внесените редове се прескачат.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import statistics
from collections import Counter
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper.db import Database, utcnow_iso  # noqa: E402

BGN_PER_EUR = 1.95583
SOFIA = ZoneInfo("Europe/Sofia")
CATEGORY = "Архив (до 2025)"


def clean_title(raw: str) -> str:
    return " ".join(raw.replace('\\"', '"').replace("\\", "").split())


def legacy_code(title: str) -> str:
    # Старият CSV няма кодове – правим стабилен идентификатор от заглавието
    return "legacy-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]


def to_utc_iso(local: str) -> str:
    dt = datetime.strptime(local, "%d-%m-%Y %H:%M:%S").replace(tzinfo=SOFIA)
    return dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default=str(root / "data" / "hdd_data.csv"))
    ap.add_argument("--db", default=str(root / "data" / "prices.db"))
    args = ap.parse_args()

    db = Database(args.db)
    conn = db.conn
    now = utcnow_iso()
    added = skipped = 0

    # Първо четем всичко – трябва ни медианата на всеки продукт за филтъра по-долу
    rows = []
    with open(args.csv, encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) < 3 or row[0] == "Date":
                continue
            try:
                rows.append((to_utc_iso(row[0].strip()), clean_title(";".join(row[1:-1])),
                             float(row[-1].strip())))
            except ValueError:
                skipped += 1

    by_title: dict[str, list[float]] = {}
    for _, title, price in rows:
        by_title.setdefault(title, []).append(price)
    medians = {t: statistics.median(v) for t, v in by_title.items()}
    counts = {t: Counter(v) for t, v in by_title.items()}

    # Старият скрипт имаше бъг: ако на страницата не се намери цена, записваше
    # цената, останала от предишния продукт. Такива точки са далеч от обичайната
    # цена на продукта (напр. слушалки за 460 €) и обикновено единични, затова ги пропускаме.
    bogus = 0
    for checked_at, title, price_bgn in rows:
        ratio = price_bgn / medians[title]
        isolated = counts[title][price_bgn] <= 3
        if ratio > 1.8 or ratio < 0.45 or (isolated and (ratio > 1.4 or ratio < 0.6)):
            bogus += 1
            continue

        code = legacy_code(title)
        conn.execute(
            """INSERT OR IGNORE INTO products(code, name, category, active, legacy,
                                              created_at, updated_at)
               VALUES (?, ?, ?, 0, 1, ?, ?)""",
            (code, title, CATEGORY, now, now),
        )
        exists = conn.execute(
            "SELECT 1 FROM prices WHERE code = ? AND checked_at = ?", (code, checked_at)
        ).fetchone()
        if exists:
            skipped += 1
            continue
        conn.execute(
            """INSERT INTO prices(code, checked_at, price, currency, source)
               VALUES (?, ?, ?, 'EUR', 'legacy_bgn')""",
            (code, checked_at, round(price_bgn / BGN_PER_EUR, 2)),
        )
        added += 1

    db.close()
    print(f"Внесени {added} цени, пропуснати {skipped}, отхвърлени като грешни {bogus}.")


if __name__ == "__main__":
    main()
