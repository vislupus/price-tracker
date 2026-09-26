"""Извличане на данни от продуктова страница на Техномаркет.

Методи по ред (първият, който даде цена, печели):

  1. schema.org JSON-LD / microdata / meta тагове – стандартните места;
  2. вграденото JSON състояние на приложението (ако има такова) – търси
     се обект с кода на продукта и поле за цена;
  3. текстът на страницата – блокът между заглавието (h1) и бутона
     „Добави в количка“. Там е цената на самия продукт; цените на
     подобните продукти и вноските са след бутона и не се броят.
"""
from __future__ import annotations

import html as htmllib
import json
import re

from bs4 import BeautifulSoup

from .parser import ParseError, Snapshot, _from_ld_json, parse_price_text

PRICE_RE = re.compile(
    r"(?P<prefix>ПЦ\s*:?\s*|разлика\s*)?"
    r"(?P<num>\d{1,3}(?:[ ,\u00a0\u202f]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*€"
)
OUT_OF_STOCK = ("изчерпан", "няма наличност", "не е наличен", "очаквайте скоро")


def _code_variants(code: str) -> set[str]:
    return {code, code.lstrip("0")}


# ---- 1. стандартни структурирани данни ---------------------------------

def _from_microdata(soup: BeautifulSoup) -> dict:
    el = soup.find(attrs={"itemprop": "price"})
    if el:
        price = parse_price_text(el.get("content") or el.get_text())
        cur = soup.find(attrs={"itemprop": "priceCurrency"})
        return {"price": price, "currency": (cur.get("content") if cur else None)}
    for prop in ("product:price:amount", "og:price:amount"):
        el = soup.find("meta", attrs={"property": prop})
        if el and el.get("content"):
            cur = soup.find("meta", attrs={"property": prop.replace("amount", "currency")})
            return {"price": parse_price_text(el["content"]),
                    "currency": cur.get("content") if cur else None}
    return {}


# ---- 2. вградено JSON състояние ----------------------------------------

def _json_scripts(soup: BeautifulSoup):
    for tag in soup.find_all("script"):
        kind = (tag.get("type") or "").lower()
        if "json" not in kind or "ld+json" in kind:
            continue
        raw = tag.string or tag.get_text() or ""
        if "&q;" in raw:  # по-старият Angular TransferState кодира кавичките
            raw = (raw.replace("&q;", '"').replace("&a;", "&").replace("&s;", "'")
                      .replace("&l;", "<").replace("&g;", ">"))
        try:
            yield json.loads(htmllib.unescape(raw) if raw.lstrip().startswith("&") else raw)
        except (json.JSONDecodeError, TypeError):
            continue


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _price_value(v):
    if isinstance(v, (int, float)) and v > 0:
        return round(float(v), 2)
    if isinstance(v, str):
        return parse_price_text(v)
    if isinstance(v, dict):
        for k in ("value", "amount", "current", "final", "price"):
            if k in v:
                return _price_value(v[k])
    return None


def _from_embedded_json(soup: BeautifulSoup, code: str) -> dict:
    codes = _code_variants(code)
    for data in _json_scripts(soup):
        for obj in _walk(data):
            ident = {str(obj.get(k)) for k in ("code", "sku", "productCode", "number", "id")
                     if obj.get(k) is not None}
            if not ident & codes:
                continue
            for key in ("finalPrice", "promoPrice", "salePrice", "price", "currentPrice"):
                price = _price_value(obj.get(key))
                if price:
                    name = obj.get("name") or obj.get("title")
                    return {"price": price, "name": name if isinstance(name, str) else None}
    return {}


# ---- 3. текстът на страницата ------------------------------------------

def _main_block_text(soup: BeautifulSoup) -> tuple[str, str | None]:
    for bad in soup(["script", "style", "noscript", "template"]):
        bad.decompose()
    h1 = soup.find("h1")
    name = " ".join(h1.get_text().split()) if h1 else None
    text = soup.get_text("\n")
    start = text.find(h1.get_text()) if h1 else 0
    start = max(start, 0)
    end = text.find("Добави в количка", start)
    if end == -1:
        end = start + 4000
    return text[start:end], name


def _from_text(soup: BeautifulSoup, code: str) -> dict:
    block, name = _main_block_text(soup)
    # Цената често е разделена на няколко тага (<span>689</span>.<sup>00</sup>) –
    # сливаме текста в един ред и махаме интервалите около десетичния разделител.
    block = " ".join(block.split())
    block = re.sub(r"(\d)\s*([.,])\s*(\d{2})(?!\d)", r"\1\2\3", block)
    m = re.search(r"Код на продукта:\s*(\d+)", block)
    if m and m.group(1).lstrip("0") != code.lstrip("0"):
        raise ParseError(f"Страницата е за продукт {m.group(1)}, а не за {code}.")

    current, old = None, None
    for t in PRICE_RE.finditer(block):
        value = parse_price_text(t.group("num"))
        prefix = (t.group("prefix") or "").lower()
        if prefix.startswith("пц"):
            old = value
        elif prefix.startswith("разлика"):
            continue
        else:
            current = value  # последната цена преди бутона е актуалната

    low = block.lower()
    in_stock = False if any(w in low for w in OUT_OF_STOCK) else (True if current else None)
    return {"price": current, "old_price": old, "name": name, "in_stock": in_stock}


# ---- обединяване ---------------------------------------------------------

def parse_technomarket_page(html: str, code: str) -> Snapshot:
    soup = BeautifulSoup(html, "html.parser")

    ld = _from_ld_json(soup)
    if ld.get("sku") and ld["sku"].lstrip("0") != code.lstrip("0"):
        ld = {}  # JSON-LD за друг продукт (напр. препоръчан) – не го ползваме
    md = _from_microdata(soup) if not ld.get("price") else {}
    js = _from_embedded_json(soup, code) if not (ld.get("price") or md.get("price")) else {}
    tx = _from_text(BeautifulSoup(html, "html.parser"), code)  # за име, наличност и стара цена

    if ld.get("price"):
        price, source = ld["price"], "ld+json"
    elif md.get("price"):
        price, source = md["price"], "microdata"
    elif js.get("price"):
        price, source = js["price"], "json"
    elif tx.get("price"):
        price, source = tx["price"], "text"
    else:
        raise ParseError("Не е намерена цена на страницата (продуктът може да е спрян).")

    currency = (ld.get("currency") or md.get("currency") or "EUR").upper()
    in_stock = ld.get("in_stock") if ld.get("in_stock") is not None else tx.get("in_stock")
    name = tx.get("name") or ld.get("name") or js.get("name")
    old = tx.get("old_price")

    return Snapshot(
        code=code,
        price=price,
        currency="EUR" if currency in ("€", "EURO") else currency,
        name=" ".join(name.split()) if name else None,
        brand=ld.get("brand"),
        image=ld.get("image"),
        in_stock=in_stock,
        is_promo=bool(old and old > price),
        promo_end=None,
        source=source,
    )
