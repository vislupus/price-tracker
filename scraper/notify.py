"""Известия в Slack.

Поддържат се два начина (първият намерен се ползва):
  1. Бот токен  – SLACK_BOT_TOKEN (xoxb-...) + SLACK_CHANNEL_ID
  2. Webhook    – SLACK_WEBHOOK_URL (https://hooks.slack.com/services/...)

Стойностите се четат от променливи на средата. В GitHub Actions те идват от
Settings → Secrets and variables → Actions и никога не се пазят в кода.
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


class SlackNotifier:
    def __init__(self):
        self.token = os.getenv("SLACK_BOT_TOKEN", "").strip()
        self.channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
        self.webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()

    @property
    def mode(self) -> str | None:
        if self.token and self.channel:
            return "bot"
        if self.webhook:
            return "webhook"
        return None

    def send(self, text: str, blocks: list | None = None) -> bool:
        """Връща True при успех. Грешките се логват, но не спират скрипта."""
        payload: dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks

        try:
            if self.mode == "bot":
                resp = requests.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json={"channel": self.channel, "unfurl_links": False, **payload},
                    timeout=15,
                )
                data = resp.json()
                if not data.get("ok") and data.get("error") == "invalid_blocks" and blocks:
                    # Ако форматираното съобщение не мине, пращаме поне обикновен текст
                    return self.send(text)
                if not data.get("ok"):
                    print(f"::warning ::Slack отказа съобщението: {data.get('error')}")
                    return False
                return True

            if self.mode == "webhook":
                resp = requests.post(self.webhook, json=payload, timeout=15)
                if resp.status_code == 400 and "invalid_blocks" in resp.text and blocks:
                    return self.send(text)
                if resp.status_code != 200:
                    print(f"::warning ::Slack webhook върна {resp.status_code}: {resp.text[:200]}")
                    return False
                return True
        except requests.RequestException as e:
            print(f"::warning ::Неуспешна връзка със Slack: {e}")
            return False

        print("ℹ️  Slack не е настроен – съобщението само се показва тук:\n" + text)
        return False


def fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("Europe/Sofia")).strftime("%d.%m.%Y")
    except ValueError:
        return iso[:10]


def fmt_eur(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} €".replace(",", " ")


def price_alert_message(*, code, name, url, category, price, target, previous, lowest,
                        in_stock, promo_end, dashboard_url):
    lines = [f"*Цена:* {fmt_eur(price)}   ·   *цел:* {fmt_eur(target)}"]
    if previous is not None and previous != price:
        diff = price - previous
        arrow = "▼" if diff < 0 else "▲"
        lines.append(f"*Преди:* {fmt_eur(previous)} ({arrow} {fmt_eur(abs(diff))})")
    if lowest is not None and price <= lowest:
        lines.append("🏆 Най-ниската цена досега")
    elif lowest is not None:
        lines.append(f"*Най-ниска досега:* {fmt_eur(lowest)}")
    if promo_end:
        lines.append(f"⏳ Промоцията е до {fmt_date(promo_end)}")
    if in_stock is False:
        lines.append("⚠️ В момента няма наличност онлайн")

    links = [f"<{url}|Отвори в Технополис>"]
    if dashboard_url:
        links.append(f"<{dashboard_url.rstrip('/')}/#{code}|Графика>")

    text = f"🔔 {name} е {fmt_eur(price)} (цел {fmt_eur(target)})"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn",
                                     "text": f"🔔 *<{url}|{name}>*\n_{category}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "   ".join(links)}]},
    ]
    return text, blocks


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def errors_message(errors: list[dict], total: int):
    text = f"⚠️ {len(errors)} от {total} продукта не можаха да бъдат прочетени"
    reasons = {e["error"] for e in errors}

    if len(errors) > 1 and len(reasons) == 1:
        # Една и съща причина за всички – не я повтаряме
        reason = reasons.pop()
        names = ", ".join(f"<{e['url']}|{_cut(e['name'] or e['code'], 40)}>" for e in errors[:10])
        body = f"Причина: {_cut(reason, 400)}\n{names}"
    else:
        body = "\n".join(
            f"• <{e['url']}|{_cut(e['name'] or e['code'], 50)}> – {_cut(e['error'], 180)}"
            for e in errors[:10]
        )
    if len(errors) > 10:
        body += f"\n…и още {len(errors) - 10}"

    hint = "Провери линковете в products.yaml."
    if any("Cloudflare" in e["error"] for e in errors):
        hint = ("Cloudflare блокира IP адреса, от който върви проверката. "
                "Виж README → „Проверка от твоя компютър“.")

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": _cut(f"*{text}*\n{body}", 2900)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": hint}]},
    ]
    return text, blocks
