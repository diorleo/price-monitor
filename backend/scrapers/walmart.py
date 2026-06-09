"""
scrapers/walmart.py — Walmart 爬虫
"""
import re
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page

logger = logging.getLogger(__name__)


class WalmartScraper(BaseScraper):
    channel_name = "Walmart"
    channel_url = "https://www.walmart.com"
    SEARCH_URL = "https://www.walmart.com/search?q={query}"

    def scrape(self) -> list[dict]:
        results = []
        for product in [p for p in self.products if p['status'] == 'Active']:
            try:
                results.append(self._scrape_product(product))
            except Exception as e:
                logger.error(f"[Walmart] Error {product['code']}: {e}")
                results.append(self._make_result(product['code'], product['name'], product['msrp'], None, ""))
        return results

    def _scrape_product(self, product: dict) -> dict:
        query = product['name'].replace(' ', '+')
        url = self.SEARCH_URL.format(query=query[:60])
        html = fetch_page(url, retries=self.retries, delay=self.delay)
        if not html:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        soup = BeautifulSoup(html, 'html.parser')

        # Walmart renders data in __NEXT_DATA__ JSON
        import json
        script = soup.select_one('script#__NEXT_DATA__')
        if script:
            try:
                data = json.loads(script.string)
                items = (data.get('props', {}).get('pageProps', {})
                             .get('initialData', {}).get('searchResult', {})
                             .get('itemStacks', [{}])[0].get('items', []))
                if items:
                    item = items[0]
                    price = item.get('priceInfo', {}).get('currentPrice', {}).get('price')
                    pid = item.get('usItemId', '')
                    product_url = f"https://www.walmart.com/ip/{pid}" if pid else url
                    return self._make_result(product['code'], product['name'], product['msrp'],
                                             float(price) if price else None, product_url)
            except Exception:
                pass

        # HTML fallback
        price_el = soup.select_one('span[itemprop="price"]') or soup.select_one('span.price-characteristic')
        price = None
        if price_el:
            text = price_el.get('content') or price_el.get_text(strip=True).replace('$', '').replace(',', '')
            m = re.search(r'[\d]+\.?\d*', text)
            if m:
                try:
                    price = float(m.group())
                except ValueError:
                    pass

        return self._make_result(product['code'], product['name'], product['msrp'], price, url)
