"""SQLite хранилище. Същата база се чете и от сайта (sql.js в браузъра)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS products (
    code          TEXT PRIMARY KEY,          -- код от Технополис (/p/<код>)
    name          TEXT,
    url           TEXT,
    category      TEXT,
    target_price  REAL,                      -- желана цена, EUR
    brand         TEXT,
    image         TEXT,
    active        INTEGER NOT NULL DEFAULT 1, -- 0 = махнат от products.yaml
    legacy        INTEGER NOT NULL DEFAULT 0, -- 1 = внесен от стария CSV
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL REFERENCES products(code),
    checked_at  TEXT NOT NULL,               -- ISO 8601, UTC
    price       REAL NOT NULL,               -- EUR
    currency    TEXT NOT NULL DEFAULT 'EUR',
    in_stock    INTEGER,
    is_promo    INTEGER NOT NULL DEFAULT 0,
    promo_end   TEXT,
    source      TEXT NOT NULL DEFAULT 'scrape' -- 'scrape' | 'legacy_bgn'
);
CREATE INDEX IF NOT EXISTS idx_prices_code_time ON prices(code, checked_at);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    ok_count     INTEGER NOT NULL DEFAULT 0,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    errors       TEXT                        -- JSON: [{code, url, error}]
);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        # Класически журнал – без -wal файлове, за да е един файл в git
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # ---- продукти -------------------------------------------------------

    def sync_products(self, products) -> None:
        """Записва/обновява продуктите от YAML; липсващите маркира като неактивни."""
        now = utcnow_iso()
        codes = []
        for p in products:
            codes.append(p.code)
            self.conn.execute(
                """
                INSERT INTO products(code, name, url, category, target_price, active,
                                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    url = excluded.url,
                    category = excluded.category,
                    target_price = excluded.target_price,
                    active = excluded.active,
                    name = COALESCE(?, products.name),
                    updated_at = excluded.updated_at
                """,
                (p.code, p.name, p.url, p.category, p.target_price, int(p.active),
                 now, now, p.name),
            )
        if codes:
            marks = ",".join("?" * len(codes))
            self.conn.execute(
                f"UPDATE products SET active = 0, updated_at = ? "
                f"WHERE legacy = 0 AND active = 1 AND code NOT IN ({marks})",
                (now, *codes),
            )
        self.conn.commit()

    def update_product_details(self, code: str, *, name=None, brand=None, image=None,
                               keep_name: bool = False) -> None:
        self.conn.execute(
            """
            UPDATE products SET
                name  = CASE WHEN ? THEN name ELSE COALESCE(?, name) END,
                brand = COALESCE(?, brand),
                image = COALESCE(?, image),
                updated_at = ?
            WHERE code = ?
            """,
            (int(keep_name), name, brand, image, utcnow_iso(), code),
        )

    def product_name(self, code: str) -> str | None:
        row = self.conn.execute("SELECT name FROM products WHERE code = ?", (code,)).fetchone()
        return row["name"] if row else None

    # ---- цени -----------------------------------------------------------

    def last_price(self, code: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM prices WHERE code = ? ORDER BY checked_at DESC, id DESC LIMIT 1",
            (code,),
        ).fetchone()

    def min_price(self, code: str) -> float | None:
        row = self.conn.execute(
            "SELECT MIN(price) AS p FROM prices WHERE code = ?", (code,)
        ).fetchone()
        return row["p"] if row else None

    def add_price(self, snap, checked_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO prices(code, checked_at, price, currency, in_stock,
                               is_promo, promo_end, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'scrape')
            """,
            (
                snap.code, checked_at, snap.price, snap.currency,
                None if snap.in_stock is None else int(snap.in_stock),
                int(snap.is_promo), snap.promo_end,
            ),
        )

    # ---- изпълнения -----------------------------------------------------

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs(started_at) VALUES (?)", (utcnow_iso(),))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, ok: int, errors: list[dict]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, ok_count = ?, fail_count = ?, errors = ? WHERE id = ?",
            (utcnow_iso(), ok, len(errors), json.dumps(errors, ensure_ascii=False), run_id),
        )
        self.conn.commit()
