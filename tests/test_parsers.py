"""Marketplace detection and WB basket-addressing tests (no network)."""

import asyncio

import pytest

from parsers.base import ParseResult, detect_marketplace
from parsers.factory import get_parser
from parsers.wildberries import (
    WB_FALLBACK_BASKET,
    WildberriesParser,
    basket_for_vol,
)


def test_get_parser_unknown_marketplace_raises():
    with pytest.raises(ValueError):
        asyncio.run(get_parser("https://example.com/product/1"))


def test_detect_marketplace():
    assert detect_marketplace("https://www.wildberries.ru/catalog/1/detail.aspx") == "WB"
    assert detect_marketplace("https://www.ozon.ru/product/x-123/") == "Ozon"
    assert detect_marketplace("https://market.yandex.ru/product--x/123") == "YANDEX"
    assert detect_marketplace("https://example.com/x") == "UNKNOWN"


def test_basket_for_vol_known_ranges():
    assert basket_for_vol(0) == "01"
    assert basket_for_vol(143) == "01"
    assert basket_for_vol(144) == "02"
    assert basket_for_vol(1007) == "05"
    assert basket_for_vol(1411) == "20"


def test_basket_for_vol_fallback():
    assert basket_for_vol(50000) == WB_FALLBACK_BASKET


def test_wb_extract_sku():
    parser = WildberriesParser("https://www.wildberries.ru/catalog/12345678/detail.aspx")
    assert parser._extract_sku() == "12345678"
    assert WildberriesParser("https://wildberries.ru/a?nm=998877")._extract_sku() == "998877"


def test_parse_result_defaults():
    r = ParseResult(marketplace="WB")
    assert r.card_images == [] and r.review_images == []
    assert r.error is None
