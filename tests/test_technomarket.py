import json
from pathlib import Path

import pytest

from scraper.config import extract_code
from scraper.parser import ParseError
from scraper.parser_technomarket import parse_technomarket_page
from scraper.shops import SHOP_BY_KEY, shop_for_url

FIXTURE = (Path(__file__).parent / "fixtures" / "technomarket_09225898.html").read_text(encoding="utf-8")
URL = "https://www.technomarket.bg/laptopi/lenovo-ideapad-slim-3-15irh10-83k10075bm-09225898"


def test_shop_detection_and_code():
    assert shop_for_url(URL).key == "technomarket"
    assert extract_code(URL) == "tm-09225898"
    assert extract_code("https://www.technomarket.bg/telefoni/"
                        "samsung-galaxy-s26-ultra-5g-256gb-ds-black-s948-09238364") == "tm-09238364"


def test_text_fallback_takes_own_price_not_related():
    s = parse_technomarket_page(FIXTURE, "09225898")
    assert (s.price, s.source, s.currency) == (689.0, "text", "EUR")
    assert s.name == "ЛАПТОП LENOVO IDEAPAD SLIM 3 15IRH10 83K10075BM"
    assert s.in_stock is True
    assert s.is_promo is False


def test_shop_parse_keeps_prefixed_code():
    s = SHOP_BY_KEY["technomarket"].parse(FIXTURE, "tm-09225898")
    assert s.code == "tm-09225898" and s.price == 689.0


def test_discount_detected_from_old_price():
    html = FIXTURE.replace('<div class="price"><span>689</span>.<sup>00</sup> €</div>',
                           '<div>разлика 80€</div><div class="old">ПЦ: 769.00 €</div>'
                           '<div class="price">689.00 €</div>')
    s = parse_technomarket_page(html, "09225898")
    assert s.price == 689.0 and s.is_promo is True


def test_thousands_separator():
    html = FIXTURE.replace("<span>689</span>.<sup>00</sup> €", "1,249.00 €")
    assert parse_technomarket_page(html, "09225898").price == 1249.0


def test_ld_json_preferred():
    ld = {"@context": "https://schema.org", "@type": "Product", "name": "X", "sku": "09225898",
          "offers": {"@type": "Offer", "price": "679.00", "priceCurrency": "EUR",
                     "availability": "https://schema.org/InStock"}}
    html = FIXTURE.replace("</head>", f'<script type="application/ld+json">{json.dumps(ld)}</script></head>')
    s = parse_technomarket_page(html, "09225898")
    assert (s.price, s.source) == (679.0, "ld+json")


def test_embedded_angular_state():
    state = '{&q;product&q;:{&q;code&q;:&q;09225898&q;,&q;name&q;:&q;X&q;,&q;price&q;:{&q;value&q;:675}}}'
    html = FIXTURE.replace("</body>", f'<script id="serverApp-state" type="application/json">{state}</script></body>')
    s = parse_technomarket_page(html, "09225898")
    assert (s.price, s.source) == (675.0, "json")


def test_wrong_product_is_error():
    with pytest.raises(ParseError):
        parse_technomarket_page(FIXTURE, "09999999")


def test_out_of_stock():
    html = FIXTURE.replace("Ограничена наличност", "Изчерпан")
    assert parse_technomarket_page(html, "09225898").in_stock is False
