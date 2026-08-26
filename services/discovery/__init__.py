"""Discovery search parsers (Block C.2).

Search across marketplace SEARCH RESULTS (not a single product URL):

- Wildberries: public JSON search API (search.wb.ru) — fast, no browser needed;
- Ozon / Yandex Market: JS-rendered → Playwright page when available,
  graceful degradation to plain httpx HTML link extraction (partial results).

Every listing: {url, sku, title, price, seller, thumbnail_url}.
"""
