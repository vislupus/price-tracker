import re
from pathlib import Path

import pytest

from scraper.config import extract_code
from scraper.main import should_alert
from scraper.parser import ParseError, parse_price_text, parse_product_page

FIXTURE = (Path(__file__).parent / "fixtures" / "product_304598.html").read_text(encoding="utf-8")


def test_full_page():
    s = parse_product_page(FIXTURE, "304598")
    assert s.price == 269.0
    assert s.currency == "EUR"
    assert s.name == "Стерео слушалки BOSE QUIETCOMFORT BLUE DUSK"
    assert s.brand == "BOSE"
    assert s.in_stock is True
    assert s.is_promo is True
    assert s.promo_end == "2026-10-07T20:59:59+00:00"
    assert s.source == "ld+json"


def test_fallback_to_ng_state():
    html = re.sub(r'<script type="application/ld\+json">.*?</script>', "", FIXTURE, flags=re.S)
    s = parse_product_page(html, "304598")
    assert (s.price, s.source) == (269.0, "ng-state")


def test_fallback_to_html():
    html = re.sub(r"<script.*?</script>", "", FIXTURE, flags=re.S)
    s = parse_product_page(html, "304598")
    assert (s.price, s.currency, s.source) == (269.0, "EUR", "html")


def test_redirect_to_other_product_is_error():
    with pytest.raises(ParseError):
        parse_product_page(FIXTURE, "999999")


def test_no_price_is_error():
    with pytest.raises(ParseError):
        parse_product_page("<html><body>Няма такъв продукт</body></html>", "1")


@pytest.mark.parametrize("text,expected", [
    ("269.00", 269.0),
    ("269,00 €", 269.0),
    ("1 299,00 €", 1299.0),
    ("1\xa0299.90", 1299.9),
    ("1.299,50", 1299.5),
    ("Цена: 49.99 лв.", 49.99),
    ("", None),
])
def test_parse_price_text(text, expected):
    assert parse_price_text(text) == expected


def test_extract_code():
    assert extract_code("https://www.technopolis.bg/bg/X/p/513937") == "513937"
    assert extract_code("https://www.technopolis.bg/bg/X/p/513937?foo=1") == "513937"
    assert extract_code("https://www.technopolis.bg/bg/X") is None


@pytest.mark.parametrize("price,target,prev,daily,expected", [
    (250, None, 300, False, False),   # няма цел
    (260, 250, 240, False, False),    # над целта
    (250, 250, None, False, True),    # първа проверка и е под целта
    (240, 250, 260, False, True),     # пресича прага
    (240, 250, 240, False, False),    # вече е известено, не се е променила
    (230, 250, 240, False, True),     # поевтиня още
    (240, 250, 240, True, True),      # всеки ден
])
def test_should_alert(price, target, prev, daily, expected):
    assert should_alert(price, target, prev, daily) is expected