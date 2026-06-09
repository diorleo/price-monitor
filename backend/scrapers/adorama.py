"""
scrapers/adorama.py — Adorama 爬虫
"""
import re
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page

logger = logging.getLogger(__name__)


class AdoramaScraper(BaseScraper):
    channel_name = "Adorama"
    channel_url = "https://www.adorama.com"
    SEARCH_URL = "https://www.adorama.com/l/?searchinfo={query}"

    def scrape(self) -> list[dict]:
        results = []
        for product in [p for p in self.products if p['status'] == 'Active']:
            try:
                results.append(self._scrape_product(product))
            except Exception as e:
                logger.error(f"[Adorama] Error {product['code']}: {e}")
                results.append(self._make_result(product['code'], product['name'], product['msrp'], None, ""))
        return results

    def _scrape_product(self, product: dict) -> dict:
        query = product['name'].replace(' ', '+')
        url = self.SEARCH_URL.format(query=query[:60])
        html = fetch_page(url, retries=self.retries, delay=self.delay)
        if not html:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select('div.category-product-item') or soup.select('li.item')
        if not items:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        item = items[0]
        price = None
        price_el = (item.select_one('span.price-wrapper span.price') or
                    item.select_one('span.our-price') or
                    item.select_one('p.price'))
        if price_el:
            text = price_el.get_text(strip=True).replace('$', '').replace(',', '')
            m = re.search(r'[\d]+\.?\d*', text)
            if m:
                try:
                    price = float(m.group())
                except ValueError:
                    pass

        link_el = item.select_one('a.item-title') or item.select_one('a[class*="product"]')
        product_url = ""
        if link_el:
            href = link_el.get('href', '')
            product_url = ("https://www.adorama.com" + href) if href.startswith('/') else href

        return self._make_result(product['code'], product['name'], product['msrp'], price, product_url)
