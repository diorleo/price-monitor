"""
scrapers/amazon.py — Amazon US 爬虫（v2 重写）

改进点：
1. 多搜索词 + 分页：MOZA RACING (2页) + MOZA (1页) + MOZA R9 (1页)
2. 智能产品匹配（共享 match_product 方法）
3. 多策略价格提取：CSS选择器 + 正则回退
4. 支持多货币格式（$ / SGD / USD）
"""
import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page, match_product, extract_price_from_text

logger = logging.getLogger(__name__)


class AmazonScraper(BaseScraper):
    channel_name = "Amazon US"
    channel_url = "https://www.amazon.com"
    SEARCH_URL = "https://www.amazon.com/s?k={query}&ref=nb_sb_noss"

    SEARCH_QUERIES = [
        ("moza+racing", 2),
        ("moza", 1),
        ("moza+r9", 1),
    ]

    def scrape(self) -> list[dict]:
        """多搜索词 + 分页遍历，合并去重后匹配所有产品"""
        all_products = []

        for query, max_pages in self.SEARCH_QUERIES:
            for page in range(1, max_pages + 1):
                url = self.SEARCH_URL.format(query=query)
                if page > 1:
                    url += f"&page={page}"

                html = fetch_page(url, retries=self.retries, delay=self.delay)
                if not html:
                    logger.warning(f"[Amazon] Failed to fetch: {query} page {page}")
                    continue

                page_products = self._parse_search_results(html)
                if not page_products:
                    logger.info(f"[Amazon] No products on {query} page {page}, stopping")
                    break

                all_products.extend(page_products)
                logger.info(f"[Amazon] {query} page {page}: found {len(page_products)} products")

        # 去重（按 ASIN/URL）
        seen = set()
        unique = []
        for p in all_products:
            key = p.get('asin', '') or p.get('url', '')
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        logger.info(f"[Amazon] Total unique products after dedup: {len(unique)}")

        fallback_url = self.SEARCH_URL.format(query="moza+racing")
        if not unique:
            logger.warning("[Amazon] No products found, returning all Missing")
            return [self._make_result(p['code'], p['name'], p['msrp'], None, fallback_url)
                    for p in self.products if p.get('status') == 'Active']

        return self._match_all_products(unique, fallback_url)

    def _parse_search_results(self, html: str) -> list[dict]:
        """解析 Amazon 搜索结果页"""
        products = []
        soup = BeautifulSoup(html, 'html.parser')

        # Amazon 搜索结果卡片
        result_divs = soup.select('div[data-component-type="s-search-result"]')
        if not result_divs:
            # 备用选择器
            result_divs = soup.select('div[data-asin]')

        for div in result_divs:
            product = self._parse_item(div)
            if product:
                products.append(product)

        return products

    def _parse_item(self, item) -> dict | None:
        """解析单个搜索结果"""
        title = ''
        url = ''
        asin = ''

        # 提取 ASIN
        asin = item.get('data-asin', '')

        # 提取产品标题和链接
        link_selectors = [
            'a.a-link-normal[href*="/dp/"] h2 span',
            'a.a-link-normal[href*="/dp/"]',
            'h2 a.a-link-normal',
            'a.s-no-outline h2 span',
            'a[href*="/dp/"]',
        ]
        for sel in link_selectors:
            el = item.select_one(sel)
            if el:
                if el.name == 'a':
                    title = el.get_text(strip=True)
                    href = el.get('href', '')
                else:
                    title = el.get_text(strip=True)
                    parent_a = el.find_parent('a')
                    href = parent_a.get('href', '') if parent_a else ''

                if href:
                    if href.startswith('http'):
                        url = href.split('?')[0]
                    else:
                        url = "https://www.amazon.com" + href.split('?')[0]

                    # 从 URL 提取 ASIN
                    asin_match = re.search(r'/dp/([A-Z0-9]{10})', href)
                    if asin_match:
                        asin = asin_match.group(1)
                break

        if not title:
            # 尝试从 h2 获取
            h2 = item.select_one('h2')
            if h2:
                title = h2.get_text(strip=True)

        if not title:
            return None

        # 提取价格
        price = None
        price_selectors = [
            'span.a-price span.a-offscreen',
            'span.a-price-whole',
            'span#priceblock_ourprice',
            'span#priceblock_dealprice',
            'span.a-offscreen',
        ]
        for sel in price_selectors:
            el = item.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                price = extract_price_from_text(text)
                if price:
                    break

        # 正则回退
        if price is None:
            text = item.get_text()
            price = extract_price_from_text(text)

        return {
            'title': title,
            'price': price,
            'url': url,
            'asin': asin,
        }
