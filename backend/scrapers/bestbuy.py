"""
scrapers/bestbuy.py — Best Buy 爬虫
"""
import re
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page

logger = logging.getLogger(__name__)


class BestBuyScraper(BaseScraper):
    channel_name = "Best Buy"
    channel_url = "https://www.bestbuy.com"
    SEARCH_URL = "https://www.bestbuy.com/site/searchpage.jsp?st={query}"

    def scrape(self) -> list[dict]:
        results = []
        active = [p for p in self.products if p['status'] == 'Active']
        for product in active:
            try:
                result = self._scrape_product(product)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"[BestBuy] Error {product['code']}: {e}")
                results.append(self._make_result(product['code'], product['name'], product['msrp'], None, ""))
        return results

    def _scrape_product(self, product: dict) -> dict:
        query = product['name'].replace(' ', '+')
        url = self.SEARCH_URL.format(query=query[:60])
        html = fetch_page(url, retries=self.retries, delay=self.delay)
        if not html:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select('li.sku-item')
        if not items:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        item = items[0]
        price = None
        price_el = item.select_one('div.priceView-customer-price span[aria-hidden]') \
                   or item.select_one('span.sr-only') \
                   or item.select_one('div.priceView-hero-price span')
        if price_el:
            text = price_el.get_text(strip=True).replace('$', '').replace(',', '')
            m = re.search(r'[\d]+\.?\d*', text)
            if m:
                try:
                    price = float(m.group())
                except ValueError:
                    pass

        link_el = item.select_one('a.image-link') or item.select_one('a.sku-title')
        product_url = ""
        if link_el:
            href = link_el.get('href', '')
            product_url = ("https://www.bestbuy.com" + href) if href.startswith('/') else href

        return self._make_result(product['code'], product['name'], product['msrp'], price, product_url)
