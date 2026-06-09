"""
scrapers/newegg.py — Newegg 爬虫
"""
import re
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page

logger = logging.getLogger(__name__)


class NeweggScraper(BaseScraper):
    channel_name = "Newegg"
    channel_url = "https://www.newegg.com"
    SEARCH_URL = "https://www.newegg.com/p/pl?d={query}&N=100161801"

    def scrape(self) -> list[dict]:
        results = []
        for product in [p for p in self.products if p['status'] == 'Active']:
            try:
                results.append(self._scrape_product(product))
            except Exception as e:
                logger.error(f"[Newegg] Error {product['code']}: {e}")
                results.append(self._make_result(product['code'], product['name'], product['msrp'], None, ""))
        return results

    def _scrape_product(self, product: dict) -> dict:
        query = product['name'].replace(' ', '+')
        url = self.SEARCH_URL.format(query=query[:50])
        html = fetch_page(url, retries=self.retries, delay=self.delay)
        if not html:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select('div.item-container') or soup.select('div.item-cell')
        if not items:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        item = items[0]
        price = None
        price_el = (item.select_one('li.price-current strong') or
                    item.select_one('li.price-current') or
                    item.select_one('span.price-current-label'))
        if price_el:
            text = price_el.get_text(strip=True).replace('$', '').replace(',', '').strip()
            m = re.search(r'[\d]+\.?\d*', text)
            if m:
                try:
                    price = float(m.group())
                except ValueError:
                    pass

        link_el = item.select_one('a.item-title') or item.select_one('a.item-img')
        product_url = ""
        if link_el:
            href = link_el.get('href', '')
            product_url = href if href.startswith('http') else "https://www.newegg.com" + href

        return self._make_result(product['code'], product['name'], product['msrp'], price, product_url)
