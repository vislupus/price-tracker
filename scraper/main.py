"""Ежедневна проверка на цените.

    python -m scraper                 # нормално изпълнение
    python -m scraper --dry-run       # само показва, не пише в базата и не праща Slack
    python -m scraper --no-notify     # записва, но не праща Slack
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

from .config import ConfigError, load_config
from .db import Database, utcnow_iso
from .fetch import FetchError, fetch_html, make_session
from .notify import SlackNotifier, errors_message, fmt_eur, price_alert_message
from .parser import ParseError, parse_product_page

ROOT = Path(__file__).resolve().parent.parent
IN_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"


def log(level: str, msg: str) -> None:
    """В GitHub Actions ползва анотации (::notice / ::warning / ::error)."""
    icons = {"notice": "✅", "warning": "⚠️", "error": "❌", "info": "  "}
    if IN_ACTIONS and level in ("notice", "warning", "error"):
        print(f"::{level} ::{msg}")
    else:
        print(f"{icons.get(level, '')} {msg}")


def should_alert(price: float, target: float | None, previous: float | None,
                 repeat_daily: bool) -> bool:
    if target is None or price > target:
        return False
    if repeat_daily or previous is None:
        return True
    # Само при пресичане на прага или допълнително поевтиняване
    return previous > target or price < previous


def write_step_summary(rows: list[dict], errors: list[dict]) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    out = ["## Цени днес", "", "| Продукт | Категория | Цена | Цел | Промяна |", "|---|---|---:|---:|---:|"]
    for r in rows:
        change = "—"
        if r["previous"] is not None and r["previous"] != r["price"]:
            d = r["price"] - r["previous"]
            change = f"{'▼' if d < 0 else '▲'} {abs(d):.2f}"
        hit = " 🔔" if r["alert"] else ""
        out.append(f"| [{r['name']}]({r['url']}) | {r['category']} | {fmt_eur(r['price'])}{hit} "
                   f"| {fmt_eur(r['target'])} | {change} |")
    if errors:
        out += ["", "### Грешки", ""]
        out += [f"- [{e['name'] or e['code']}]({e['url']}): {e['error']}" for e in errors]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def run(config_path: Path, db_path: Path, dry_run: bool, notify: bool) -> int:
    try:
        config = load_config(config_path)
    except ConfigError as e:
        log("error", str(e).replace("\n", " "))
        return 2

    products = config.active_products
    if not products:
        log("warning", "Няма активни продукти в products.yaml.")
        return 0

    db = Database(db_path if not dry_run else ":memory:")
    db.sync_products(config.products)
    run_id = db.start_run()

    slack = SlackNotifier()
    notify = notify and not dry_run
    if notify and not slack.mode:
        log("warning", "Slack не е настроен (липсват SLACK_BOT_TOKEN/SLACK_CHANNEL_ID "
                       "или SLACK_WEBHOOK_URL) – известията се пропускат.")
    dashboard_url = os.getenv("DASHBOARD_URL", "").strip() or None

    session = make_session()
    checked_at = utcnow_iso()
    rows: list[dict] = []
    errors: list[dict] = []

    for i, p in enumerate(products):
        if i:
            time.sleep(config.settings.request_delay + random.uniform(0, 1))
        try:
            html = fetch_html(session, p.url)
            snap = parse_product_page(html, p.code)
        except (FetchError, ParseError) as e:
            errors.append({"code": p.code, "url": p.url,
                           "name": p.name or db.product_name(p.code), "error": str(e)})
            log("error", f"{p.code} {p.url} – {e}")
            continue
        except Exception as e:  # noqa: BLE001 – не спираме заради един продукт
            errors.append({"code": p.code, "url": p.url,
                           "name": p.name or db.product_name(p.code),
                           "error": f"{type(e).__name__}: {e}"})
            log("error", f"{p.code} – неочаквана грешка: {e!r}")
            continue

        if snap.currency != "EUR":
            log("warning", f"{p.code}: валутата е {snap.currency}, очакваше се EUR.")

        prev_row = db.last_price(p.code)
        previous = prev_row["price"] if prev_row else None
        lowest_before = db.min_price(p.code)

        db.update_product_details(p.code, name=snap.name, brand=snap.brand,
                                  image=snap.image, keep_name=bool(p.name))
        db.add_price(snap, checked_at)

        name = p.name or snap.name or p.code
        alert = should_alert(snap.price, p.target_price, previous,
                             config.settings.repeat_alerts_daily)
        rows.append({"name": name, "url": p.url, "category": p.category, "price": snap.price,
                     "target": p.target_price, "previous": previous, "alert": alert})

        promo = " (промо)" if snap.is_promo else ""
        log("notice", f"{name}: {fmt_eur(snap.price)}{promo} [{snap.source}]")

        if alert and notify:
            text, blocks = price_alert_message(
                code=p.code, name=name, url=p.url, category=p.category, price=snap.price,
                target=p.target_price, previous=previous, lowest=lowest_before,
                in_stock=snap.in_stock, promo_end=snap.promo_end, dashboard_url=dashboard_url,
            )
            slack.send(text, blocks)
        elif alert:
            log("info", f"🔔 (без известие) {name} е под целта {fmt_eur(p.target_price)}")

    db.finish_run(run_id, ok=len(rows), errors=errors)
    db.close()

    if errors and notify and config.settings.notify_on_errors:
        text, blocks = errors_message(errors, len(products))
        slack.send(text, blocks)

    write_step_summary(rows, errors)
    print(f"\nГотово: {len(rows)} успешни, {len(errors)} с грешка.")

    # Червено в Actions само ако нищо не е минало – единични счупени линкове
    # се виждат като предупреждения и в Slack.
    return 1 if not rows else 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Проверка на цени в Технополис")
    ap.add_argument("--config", default=str(ROOT / "products.yaml"))
    ap.add_argument("--db", default=str(ROOT / "data" / "prices.db"))
    ap.add_argument("--dry-run", action="store_true", help="без запис в базата и без Slack")
    ap.add_argument("--no-notify", action="store_true", help="без Slack")
    args = ap.parse_args(argv)
    sys.exit(run(Path(args.config), Path(args.db), args.dry_run, not args.no_notify))


if __name__ == "__main__":
    main()
