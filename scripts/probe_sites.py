"""Проверява дали сайтове пускат заявки от текущата машина (напр. GitHub Actions).

За всеки адрес се пробват същите три начина като в scraper-а:
curl_cffi/chrome, curl_cffi/safari и обикновен requests. Показва се
статусът, дали е блокирано от защита срещу ботове и дали в страницата
има машинно четима цена (schema.org / meta тагове).

    python scripts/probe_sites.py                         # адресите от scripts/probe_sites.txt
    python scripts/probe_sites.py https://a.bg https://b.bg
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

DEFAULT_LIST = Path(__file__).with_name("probe_sites.txt")
TIMEOUT = 20
LANG = {"Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8"}


def strategies():
    out = []
    if cffi_requests is not None:
        for browser in ("chrome", "safari"):
            s = cffi_requests.Session(impersonate=browser)
            s.headers.update(LANG)
            out.append((f"curl_cffi/{browser}", s))
    s = requests.Session()
    s.headers.update(LANG)
    out.append(("requests", s))
    return out


BLOCK_MARKERS = (
    "just a moment", "attention required", "access denied", "cf-chl",
    "captcha", "are you a robot", "request blocked", "pardon our interruption",
)


def classify(resp) -> tuple[str, str]:
    """-> (кратък статус, подробности)."""
    h = {k.lower(): v for k, v in resp.headers.items()}
    body = (resp.text or "")[:20000].lower()
    server = h.get("server", "")
    extra = []
    if server:
        extra.append(f"server={server}")
    if "cf-mitigated" in h:
        extra.append(f"cf-mitigated={h['cf-mitigated']}")
    for key in ("x-datadome", "x-akamai-session-info", "x-iinfo", "x-px"):
        if key in h:
            extra.append(key)

    blocked = (
        "cf-mitigated" in h
        or any(m in body for m in BLOCK_MARKERS) and resp.status_code in (403, 429, 503)
        or resp.status_code in (401, 403, 429)
    )
    if resp.status_code == 200 and not blocked:
        return "OK", ", ".join(extra)
    if blocked:
        return "БЛОКИРАН", ", ".join([f"HTTP {resp.status_code}", *extra])
    return f"HTTP {resp.status_code}", ", ".join(extra)


def find_price(html: str) -> str:
    """Търси цена в schema.org JSON-LD, microdata или Open Graph."""
    soup = BeautifulSoup(html, "html.parser")

    def walk(obj):
        if isinstance(obj, list):
            for o in obj:
                yield from walk(o)
        elif isinstance(obj, dict):
            yield obj
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    yield from walk(v)

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in walk(data):
            if obj.get("@type") in ("Offer", "AggregateOffer") and (obj.get("price") or obj.get("lowPrice")):
                price = obj.get("price") or obj.get("lowPrice")
                return f"ld+json: {price} {obj.get('priceCurrency', '')}".strip()

    el = soup.find(attrs={"itemprop": "price"})
    if el:
        return f"microdata: {el.get('content') or el.get_text(strip=True)}"
    for prop in ("product:price:amount", "og:price:amount"):
        el = soup.find("meta", attrs={"property": prop})
        if el and el.get("content"):
            return f"meta: {el['content']}"
    return "—"


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    return " ".join(m.group(1).split())[:60] if m else ""


def probe(url: str) -> list[dict]:
    results = []
    for name, session in strategies():
        t0 = time.monotonic()
        try:
            resp = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            status, detail = classify(resp)
            price = find_price(resp.text) if status == "OK" else ""
            title = title_of(resp.text)
        except Exception as e:  # noqa: BLE001
            status, detail, price, title = "ГРЕШКА", f"{type(e).__name__}: {str(e)[:80]}", "", ""
        results.append({
            "url": url, "method": name, "status": status, "detail": detail,
            "price": price, "title": title, "ms": int((time.monotonic() - t0) * 1000),
        })
        time.sleep(1)
    return results


def verdict(rows: list[dict]) -> str:
    ok = [r["method"] for r in rows if r["status"] == "OK"]
    if len(ok) == len(rows):
        return "✅ минава"
    if ok:
        return "🟡 само чрез " + ", ".join(ok)
    if any(r["status"] == "БЛОКИРАН" for r in rows):
        return "⛔ блокиран"
    statuses = {r["status"] for r in rows}
    if statuses == {"HTTP 404"}:
        return "❓ 404 – няма такава страница"
    return "❓ грешка: " + ", ".join(sorted(statuses))


def load_urls(argv: list[str]) -> list[str]:
    raw = argv or DEFAULT_LIST.read_text(encoding="utf-8").splitlines()
    urls = []
    for line in raw:
        for part in line.split():
            if part.startswith("#"):
                break
            if part.startswith("http"):
                urls.append(part)
    return urls


def main() -> None:
    urls = load_urls(sys.argv[1:])
    if not urls:
        print("Няма адреси за проверка.")
        return

    try:
        r = requests.get("https://api.ipify.org", timeout=10)
        ip = r.text.strip() if r.ok and re.fullmatch(r"[\d.:a-fA-F]+", r.text.strip()) else "неизвестен"
    except requests.RequestException:
        ip = "неизвестен"
    print(f"Проверка от IP {ip}, {len(urls)} адреса\n")

    all_rows = []
    summary = []
    for url in urls:
        rows = probe(url)
        all_rows += rows
        v = verdict(rows)
        price = next((r["price"] for r in rows if r["price"] and r["price"] != "—"), "—")
        summary.append((url, v, price))
        print(f"{v:<28} {url}")
        for r in rows:
            print(f"    {r['method']:<18} {r['status']:<10} {r['ms']:>6} ms  {r['detail']}"
                  f"{'  | ' + r['price'] if r['price'] else ''}")
        print()

    out = os.getenv("GITHUB_STEP_SUMMARY")
    if out:
        md = [f"## Проверка на сайтове от IP `{ip}`", "",
              "| Сайт | Резултат | Цена в страницата |", "|---|---|---|"]
        md += [f"| {u} | {v} | {p} |" for u, v, p in summary]
        md += ["", "<details><summary>Подробно по методи</summary>", "",
               "| Сайт | Метод | Статус | ms | Детайли | Заглавие |", "|---|---|---|---:|---|---|"]
        md += [f"| {r['url']} | {r['method']} | {r['status']} | {r['ms']} | {r['detail']} "
               f"| {r['title'].replace('|', '/')} |" for r in all_rows]
        md += ["", "</details>"]
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
