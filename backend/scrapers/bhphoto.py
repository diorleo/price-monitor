"""
scrapers/bhphoto.py — B&H Photo 爬虫
"""
import re
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page

logger = logging.getLogger(__name__)


class BHPhotoScraper(BaseScraper):
    channel_name = "B&H Photo"
    channel_url = "https://www.bhphotovideo.com"
    SEARCH_URL = "https://www.bhphotovideo.com/c/search?q={query}&sto=1"

    def scrape(self) -> list[dict]:
        results = []
        for product in [p for p in self.products if p['status'] == 'Active']:
            try:
                results.append(self._scrape_product(product))
            except Exception as e:
                logger.error(f"[B&H] Error {product['code']}: {e}")
                results.append(self._make_result(product['code'], product['name'], product['msrp'], None, ""))
        return results

    def _scrape_product(self, product: dict) -> dict:
        query = product['name'].replace(' ', '+')
        url = self.SEARCH_URL.format(query=query[:60])
        html = fetch_page(url, retries=self.retries, delay=self.delay)
        if not html:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        soup = BeautifulSoup(html, 'html.parser')
        # B&H search result cards
        cards = soup.select('div[data-selenium="productItem"]') or soup.select('div.product-info')
        if not cards:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        card = cards[0]
        price = None
        price_el = card.select_one('span[data-selenium="price"]') or card.select_one('span.price')
        if price_el:
            text = price_el.get_text(strip=True).replace('$', '').replace(',', '')
            m = re.search(r'[\d]+\.?\d*', text)
            if m:
                try:
                    price = float(m.group())
                except ValueError:
                    pass

        link_el = card.select_one('a[data-selenium="itemLink"]') or card.select_one('a.title')
        product_url = ""
        if link_el:
            href = link_el.get('href', '')
            product_url = ("https://www.bhphotovideo.com" + href) if href.startswith('/') else href

        return self._make_result(product['code'], product['name'], product['msrp'], price, product_url)
