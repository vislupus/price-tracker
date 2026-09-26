"""Извличане на данни от продуктова страница на Технополис.

Страницата се рендира на сървъра (Angular SSR) и съдържа данните на три места.
Опитваме ги по ред, от най-стабилното към най-чупливото:

  1. <script type="application/ld+json"> с schema.org Product – стандарт,
     сайтовете рядко го пипат, защото е за Google.
  2. <script id="ng-state"> – вътрешното състояние на приложението.
     Оттук вземаме и дали цената е промоционална и до кога.
  3. Самият HTML (.product-box__price-value) – резервен вариант.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


class ParseError(Exception):
    pass


@dataclass
class Snapshot:
    code: str
    price: float
    currency: str = "EUR"
    name: str | None = None
    brand: str | None = None
    image: str | None = None
    in_stock: bool | None = None
    is_promo: bool = False
    promo_end: str | None = None  # ISO 8601
    source: str = "ld+json"       # откъде е взета цената (за диагностика)


def parse_price_text(text: str) -> float | None:
    """'1 299,00 €' / '1.299,00' / '269.00' / '269,00 лв.' -> float."""
    if not text:
        return None
    t = text.replace("\xa0", " ").replace("\u202f", " ")
    t = re.sub(r"[^\d,.]", "", t).strip(".,")  # 'лв.' оставя висяща точка
    if not t or not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        # последният разделител е десетичният
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = f"{head.replace(',', '')}.{tail}" if len(tail) != 3 else t.replace(",", "")
    elif t.count(".") > 1:
        head, _, tail = t.rpartition(".")
        t = f"{head.replace('.', '')}.{tail}"
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return parse_price_text(str(value))


def _iter_ld_objects(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        for obj in stack:
            if isinstance(obj, dict) and "@graph" in obj:
                stack.extend(obj["@graph"])
            yield obj


def _from_ld_json(soup: BeautifulSoup) -> dict:
    for obj in _iter_ld_objects(soup):
        if not isinstance(obj, dict) or obj.get("@type") != "Product":
            continue
        offers = obj.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        brand = obj.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        image = obj.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        availability = str(offers.get("availability") or "")
        return {
            "name": obj.get("name"),
            "sku": str(obj.get("sku") or "") or None,
            "brand": brand,
            "image": image,
            "price": _to_float(offers.get("price")),
            "currency": offers.get("priceCurrency"),
            "in_stock": ("InStock" in availability) if availability else None,
        }
    return {}


def _from_ng_state(soup: BeautifulSoup, code: str) -> dict:
    tag = soup.find("script", id="ng-state")
    if not tag:
        return {}
    try:
        state = json.loads(tag.string or tag.get_text() or "")
    except (json.JSONDecodeError, TypeError):
        return {}

    entity = (
        state.get("cx-state", {})
        .get("product", {})
        .get("details", {})
        .get("entities", {})
        .get(code, {})
    )
    value = None
    for scope in ("details", "variants", "list"):
        v = (entity.get(scope) or {}).get("value")
        if isinstance(v, dict) and v.get("price"):
            value = v
            break
    if not value:
        return {}

    price = value.get("price") or {}
    stock = value.get("stock") or {}
    status = stock.get("stockLevelStatus")
    return {
        "name": value.get("name"),
        "brand": value.get("brand"),
        "price": _to_float(price.get("value")),
        "currency": price.get("currencyIso"),
        "is_promo": bool(price.get("promoType")),
        "promo_end": price.get("endDate") if price.get("promoType") else None,
        "in_stock": (status == "inStock") if status else (not value.get("soldOut", False)),
    }


def _from_html(soup: BeautifulSoup) -> dict:
    out: dict = {}
    for sel in (
        ".pdp-details__start .product-box__price-value",
        "te-price .product-box__price-value",
        ".product-pdp__prices .price-value",
    ):
        el = soup.select_one(sel)
        if el:
            price = parse_price_text(el.get_text())
            if price:
                out["price"] = price
                break
    h1 = soup.select_one("h1.product-name") or soup.select_one(".product-name")
    if h1:
        out["name"] = " ".join(h1.get_text().split())
    text = soup.get_text(" ")
    out["currency"] = "EUR" if "€" in text else ("BGN" if "лв" in text else None)
    return out


def _normalize_iso(value: str | None) -> str | None:
    """'2026-10-07T20:59:59+0000' -> '2026-10-07T20:59:59+00:00'."""
    if not value:
        return None
    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)


def parse_product_page(html: str, code: str) -> Snapshot:
    soup = BeautifulSoup(html, "html.parser")

    ld = _from_ld_json(soup)
    ng = _from_ng_state(soup, code)
    hx = _from_html(soup) if not (ld.get("price") or ng.get("price")) else {}

    if ld.get("sku") and ld["sku"] != code:
        raise ParseError(
            f"Страницата е за продукт {ld['sku']}, а не за {code} – вероятно линкът пренасочва."
        )

    if ld.get("price"):
        price, source = ld["price"], "ld+json"
    elif ng.get("price"):
        price, source = ng["price"], "ng-state"
    elif hx.get("price"):
        price, source = hx["price"], "html"
    else:
        raise ParseError("Не е намерена цена на страницата (продуктът може да е спрян).")

    currency = (ld.get("currency") or ng.get("currency") or hx.get("currency") or "EUR").upper()
    if currency in ("€", "EURO"):
        currency = "EUR"

    in_stock = ld.get("in_stock")
    if in_stock is None:
        in_stock = ng.get("in_stock")

    name = ng.get("name") or ld.get("name") or hx.get("name")

    return Snapshot(
        code=code,
        price=price,
        currency=currency,
        name=" ".join(name.split()) if name else None,
        brand=ld.get("brand") or ng.get("brand"),
        image=ld.get("image"),
        in_stock=in_stock,
        is_promo=bool(ng.get("is_promo")),
        promo_end=_normalize_iso(ng.get("promo_end")),
        source=source,
    )
