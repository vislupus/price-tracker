"""Извличане на данни от продуктова страница на Техномаркет.

Методи по ред (първият, който даде цена, печели):

  1. блокът <div class="action" data-product="<код>"> – точно цената, която
     се вижда до бутона „Добави в количка“, заедно със старата цена (ПЦ)
     и наличността. Подобните продукти по-долу са в блокове без този код;
  2. schema.org JSON-LD (Product с "sku" = кода);
  3. microdata / meta тагове и вградено JSON – ако сайтът ги добави;
  4. текстът след „Код на продукта: <код>“ до бутона – краен резервен вариант.
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


# ---- 1. блокът на продукта ----------------------------------------------

def _from_dom(soup: BeautifulSoup, code: str) -> dict:
    for block in soup.select("[data-product]"):
        if str(block.get("data-product", "")).lstrip("0") != code.lstrip("0"):
            continue
        price_el = block.select_one(".price-wrapper .price") or block.select_one(".price")
        if not price_el:
            continue
        # <span>1,249</span><span>.</span><span>00 </span><span>€</span> -> "1,249.00€"
        price = parse_price_text(price_el.get_text("", strip=True))
        if not price:
            continue
        old_el = block.select_one(".old-price")
        old = parse_price_text(old_el.get_text("", strip=True)) if old_el else None
        has_cart = block.select_one('[data-action="addCart"]') is not None
        return {"price": price, "old_price": old, "in_stock": True if has_cart else None,
                "limited": block.select_one(".limited-item") is not None}
    return {}


# ---- 2–3. стандартни структурирани данни --------------------------------

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

def _from_text(soup: BeautifulSoup, code: str) -> dict:
    for bad in soup(["script", "style", "noscript", "template"]):
        bad.decompose()
    h1 = soup.find("h1")
    name = " ".join(h1.get_text().split()) if h1 else None

    # Цената често е разделена на няколко тага (<span>689</span>.<sup>00</sup>) –
    # сливаме текста в един ред и махаме интервалите около десетичния разделител.
    text = " ".join(soup.get_text(" ").split())
    text = re.sub(r"(\d)\s*([.,])\s*(\d{2})(?!\d)", r"\1\2\3", text)

    # Блокът започва от „Код на продукта: <нашия код>“ и свършва при бутона.
    m = re.search(r"Код на продукта:\s*0*" + re.escape(code.lstrip("0")) + r"\b", text)
    if not m:
        return {"name": name}
    end = text.find("Добави в количка", m.end())
    block = text[m.end(): end if end != -1 else m.end() + 1500]

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

    dom = _from_dom(soup, code)
    ld = _from_ld_json(soup)
    if ld.get("sku") and ld["sku"].lstrip("0") != code.lstrip("0"):
        raise ParseError(f"Страницата е за продукт {ld['sku']}, а не за {code} "
                         "– вероятно линкът пренасочва.")
    have = dom.get("price") or ld.get("price")
    md = _from_microdata(soup) if not have else {}
    js = _from_embedded_json(soup, code) if not (have or md.get("price")) else {}
    tx = _from_text(BeautifulSoup(html, "html.parser"), code)  # име, резервна цена

    if dom.get("price"):
        price, source = dom["price"], "dom"
    elif ld.get("price"):
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
    in_stock = dom.get("in_stock")
    if in_stock is None:
        in_stock = ld.get("in_stock") if ld.get("in_stock") is not None else tx.get("in_stock")
    name = tx.get("name") or ld.get("name") or js.get("name")
    old = dom.get("old_price") or tx.get("old_price")

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
