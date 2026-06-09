"""
scrapers/amazon.py — Amazon US 爬虫
爬取策略：通过关键词搜索页 + 产品 ASIN 页获取价格
注意：Amazon 反爬较强，建议配合代理或适当延时
"""
import re
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page

logger = logging.getLogger(__name__)


class AmazonScraper(BaseScraper):
    channel_name = "Amazon US"
    channel_url = "https://www.amazon.com"

    SEARCH_URL = "https://www.amazon.com/s?k=moza+racing+{query}&ref=nb_sb_noss"
    PRICE_SELECTORS = [
        "span.a-price-whole",
        "span#priceblock_ourprice",
        "span#priceblock_dealprice",
        "span.a-offscreen",
    ]

    def scrape(self) -> list[dict]:
        results = []
        active = [p for p in self.products if p['status'] == 'Active']

        for product in active:
            try:
                result = self._scrape_product(product)
                if result:
                    results.append(result)
                    logger.info(f"[Amazon] {product['code']} → ${result.get('listing_price', 'N/A')}")
            except Exception as e:
                logger.error(f"[Amazon] Error scraping {product['code']}: {e}")
                results.append(self._make_result(
                    product['code'], product['name'], product['msrp'], None, ""
                ))

        return results

    def _scrape_product(self, product: dict) -> dict | None:
        # 用产品名称搜索
        query = product['name'].replace(' ', '+').replace('MOZA+', '')
        url = self.SEARCH_URL.format(query=query[:50])
        html = fetch_page(url, retries=self.retries, delay=self.delay)
        if not html:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        soup = BeautifulSoup(html, 'html.parser')

        # 提取搜索结果第一条
        result_divs = soup.select('div[data-component-type="s-search-result"]')
        if not result_divs:
            return self._make_result(product['code'], product['name'], product['msrp'], None, url)

        first = result_divs[0]

        # 提取价格
        price = self._extract_price(first)

        # 提取产品链接
        link_tag = first.select_one('a.a-link-normal[href*="/dp/"]')
        product_url = ""
        if link_tag:
            href = link_tag.get('href', '')
            if href.startswith('http'):
                product_url = href.split('?')[0]
            else:
                product_url = "https://www.amazon.com" + href.split('?')[0]

        return self._make_result(product['code'], product['name'], product['msrp'], price, product_url)

    def _extract_price(self, soup_elem) -> float | None:
        for selector in self.PRICE_SELECTORS:
            el = soup_elem.select_one(selector)
            if el:
                text = el.get_text(strip=True).replace(',', '').replace('$', '')
                match = re.search(r'[\d]+\.?\d*', text)
                if match:
                    try:
                        return float(match.group())
                    except ValueError:
                        pass

        # 备用：用正则在整个文本中找价格
        text = soup_elem.get_text()
        match = re.search(r'\$\s*([\d,]+\.\d{2})', text)
        if match:
            try:
                return float(match.group(1).replace(',', ''))
            except ValueError:
                pass
        return None
