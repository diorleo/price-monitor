"""
scrapers/mozaofficial.py — MOZA 官方网站爬虫 (mozaracing.com)
官方店价格即 MSRP，状态应始终为 Normal
"""
import re
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page

logger = logging.getLogger(__name__)


class MozaOfficialScraper(BaseScraper):
    channel_name = "MOZA Official"
    channel_url = "https://mozaracing.com"
    SEARCH_URL = "https://mozaracing.com/collections/all"

    def scrape(self) -> list[dict]:
        results = []
        # 先抓全量列表，再匹配
        html = fetch_page(self.SEARCH_URL, retries=self.retries, delay=self.delay)
        catalog = {}
        if html:
            catalog = self._parse_catalog(html)

        for product in [p for p in self.products if p['status'] == 'Active']:
            key = product['code'].upper()
            entry = catalog.get(key) or catalog.get(product['name'].upper())
            if entry:
                results.append(self._make_result(
                    product['code'], product['name'], product['msrp'],
                    entry['price'], entry['url']
                ))
            else:
                # 直接搜索
                results.append(self._search_product(product))

        return results

    def _parse_catalog(self, html: str) -> dict:
        soup = BeautifulSoup(html, 'html.parser')
        catalog = {}
        for item in soup.select('div.product-item') or soup.select('li.product-item'):
            title_el = item.select_one('h3.product-title') or item.select_one('a.product-title')
            price_el = item.select_one('span.price') or item.select_one('span.money')
            link_el = item.select_one('a[href*="/products/"]')
            if not (title_el and price_el):
                continue
            title = title_el.get_text(strip=True).upper()
            price_text = price_el.get_text(strip=True).replace('$', '').replace(',', '')
            m = re.search(r'[\d]+\.?\d*', price_text)
            url = ""
            if link_el:
                href = link_el.get('href', '')
                url = ("https://mozaracing.com" + href) if href.startswith('/') else href
            if m:
                catalog[title] = {'price': float(m.group()), 'url': url}
        return catalog

    def _search_product(self, product: dict) -> dict:
        query = product['name'].replace(' ', '+').replace('MOZA+', '')
        url = f"https://mozaracing.com/search?q={query[:50]}"
        html = fetch_page(url, retries=self.retries, delay=self.delay)
        if not html:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        soup = BeautifulSoup(html, 'html.parser')
        price_el = soup.select_one('span.price') or soup.select_one('span.money')
        price = None
        product_url = url
        if price_el:
            text = price_el.get_text(strip=True).replace('$', '').replace(',', '')
            m = re.search(r'[\d]+\.?\d*', text)
            if m:
                try:
                    price = float(m.group())
                except ValueError:
                    pass

        link_el = soup.select_one('a[href*="/products/"]')
        if link_el:
            href = link_el.get('href', '')
            product_url = ("https://mozaracing.com" + href) if href.startswith('/') else href

        return self._make_result(product['code'], product['name'], product['msrp'], price, product_url)
