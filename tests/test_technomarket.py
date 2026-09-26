"""Тестове върху реални страници на Техномаркет (изтеглени от GitHub Actions, 26.09.2026)."""
import re
from pathlib import Path

import pytest

from scraper.config import extract_code
from scraper.parser import ParseError
from scraper.parser_technomarket import parse_technomarket_page
from scraper.shops import SHOP_BY_KEY, shop_for_url

FIX = Path(__file__).parent / "fixtures"
LAPTOP = (FIX / "technomarket_09225898.html").read_text(encoding="utf-8")
PHONE = (FIX / "technomarket_09238364.html").read_text(encoding="utf-8")
URL = "https://www.technomarket.bg/laptopi/lenovo-ideapad-slim-3-15irh10-83k10075bm-09225898"


def strip_ld(html):
    return re.sub(r'<script type="application/ld\+json">.*?</script>', "", html, flags=re.S)


def strip_dom(html, code):
    return html.replace(f'data-product="{code}"', 'data-product="x"')


def test_shop_detection_and_code():
    assert shop_for_url(URL).key == "technomarket"
    assert extract_code(URL) == "tm-09225898"
    assert extract_code("https://www.technomarket.bg/telefoni/"
                        "samsung-galaxy-s26-ultra-5g-256gb-ds-black-s948-09238364") == "tm-09238364"


def test_real_laptop_page():
    s = parse_technomarket_page(LAPTOP, "09225898")
    assert (s.price, s.currency, s.source) == (689.0, "EUR", "dom")
    assert s.name == "ЛАПТОП LENOVO IDEAPAD SLIM 3 15IRH10 83K10075BM"
    assert s.brand == "LENOVO"
    assert s.in_stock is True
    assert s.is_promo is False


def test_real_phone_page_thousands():
    s = parse_technomarket_page(PHONE, "09238364")
    assert (s.price, s.source) == (1249.0, "dom")
    assert s.name.startswith("МОБИЛЕН ТЕЛЕФОН SAMSUNG GALAXY S26 ULTRA")


def test_similar_products_are_ignored():
    # Подобните продукти (LOQ за 1 099 €, S26 за 899 €) не бива да се хващат
    assert parse_technomarket_page(LAPTOP, "09225898").price != 1099.0
    assert parse_technomarket_page(PHONE, "09238364").price != 899.0


def test_fallback_to_ld_json():
    s = parse_technomarket_page(strip_dom(LAPTOP, "09225898"), "09225898")
    assert (s.price, s.source) == (689.0, "ld+json")


def test_fallback_to_text():
    html = strip_ld(strip_dom(PHONE, "09238364"))
    s = parse_technomarket_page(html, "09238364")
    assert (s.price, s.source) == (1249.0, "text")


def test_old_price_marks_promo():
    html = LAPTOP.replace(
        '<span class="old-price"></span>',
        '<span class="old-price">ПЦ:<tm-price><span class="euro_price">769 €</span></tm-price></span>', 1)
    s = parse_technomarket_page(html, "09225898")
    assert s.price == 689.0 and s.is_promo is True


def test_wrong_product_is_error():
    with pytest.raises(ParseError):
        parse_technomarket_page(LAPTOP, "09999999")


def test_shop_parse_keeps_prefixed_code():
    s = SHOP_BY_KEY["technomarket"].parse(LAPTOP, "tm-09225898")
    assert s.code == "tm-09225898" and s.price == 689.0
