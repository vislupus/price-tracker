"""Поддържани магазини.

Всеки магазин знае как да вземе кода на продукта от линка и как да прочете
страницата. Кодът в базата е с префикс, за да не се смесват магазините
(Технополис е без префикс, за да остане съвместим със старата история).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from .parser import Snapshot, parse_product_page
from .parser_technomarket import parse_technomarket_page


@dataclass(frozen=True)
class Shop:
    key: str
    name: str
    domain: str
    code_re: re.Pattern
    prefix: str
    parse_page: Callable[[str, str], Snapshot]

    def raw_code(self, url: str) -> str | None:
        m = self.code_re.search(urlparse(url).path)
        return m.group(1) if m else None

    def db_code(self, raw: str) -> str:
        return f"{self.prefix}{raw}"

    def parse(self, html: str, db_code: str) -> Snapshot:
        raw = db_code[len(self.prefix):]
        snap = self.parse_page(html, raw)
        snap.code = db_code
        return snap


SHOPS = [
    Shop("technopolis", "Технополис", "technopolis.bg",
         re.compile(r"/p/(\d+)"), "", parse_product_page),
    Shop("technomarket", "Техномаркет", "technomarket.bg",
         re.compile(r"-(\d{6,})/?$"), "tm-", parse_technomarket_page),
]
SHOP_BY_KEY = {s.key: s for s in SHOPS}


def shop_for_url(url: str) -> Shop | None:
    host = (urlparse(url).hostname or "").lower()
    for shop in SHOPS:
        if host == shop.domain or host.endswith("." + shop.domain):
            return shop
    return None
