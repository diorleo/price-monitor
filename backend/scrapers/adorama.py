"""
scrapers/adorama.py — Adorama 爬虫（v2 重写）

改进点：
1. 多搜索词：MOZA RACING (2页) + MOZA (1页)
2. 智能产品匹配（共享 match_product 方法）
3. 多策略解析：JSON-LD → CSS选择器 → 正则回退
4. 注意：Adorama 不销售 MOZA RACING 模拟赛车产品，
   智能匹配会正确区分，未匹配产品返回 Missing。
"""
import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page, extract_price_from_text

logger = logging.getLogger(__name__)


class AdoramaScraper(BaseScraper):
    channel_name = "Adorama"
    channel_url = "https://www.adorama.com"
    SEARCH_URL = "https://www.adorama.com/l/?searchinfo={query}"

    SEARCH_QUERIES = [
        ("moza+racing", 2),
        ("moza", 1),
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
                    logger.warning(f"[Adorama] Failed to fetch: {query} page {page}")
                    continue

                page_products = self._parse_search_results(html)
                if not page_products:
                    logger.info(f"[Adorama] No products on {query} page {page}, stopping")
                    break

                all_products.extend(page_products)
                logger.info(f"[Adorama] {query} page {page}: found {len(page_products)} products")

        # 去重
        seen = set()
        unique = []
        for p in all_products:
            key = p.get('url', '') or p.get('title', '')
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        logger.info(f"[Adorama] Total unique products after dedup: {len(unique)}")

        fallback_url = self.SEARCH_URL.format(query="moza+racing")
        if not unique:
            logger.warning("[Adorama] No products found, returning all Missing")
            return [self._make_result(p['code'], p['name'], p['msrp'], None, fallback_url)
                    for p in self.products if p.get('status') == 'Active']

        return self._match_all_products(unique, fallback_url)

    def _parse_search_results(self, html: str) -> list[dict]:
        """解析 Adorama 搜索结果页"""
        products = []

        # 策略 1: JSON-LD
        products.extend(self._extract_from_json_ld(html))

        # 策略 2: CSS 选择器
        if not products:
            products.extend(self._extract_from_html(html))

        # 策略 3: 正则回退
        if not products:
            products.extend(self._extract_with_regex(html))

        # 去重
        seen = set()
        unique = []
        for p in products:
            key = p.get('url', '') or p.get('title', '')
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        return unique

    def _extract_from_json_ld(self, html: str) -> list[dict]:
        """从 JSON-LD 提取产品"""
        products = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            scripts = soup.find_all('script', type='application/ld+json')
            for script in scripts:
                if not script.string:
                    continue
                try:
                    data = json.loads(script.string)
                except json.JSONDecodeError:
                    continue

                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if '@graph' in item:
                        items.extend(item['@graph'])
                        continue
                    if item.get('@type') == 'ItemList' and 'itemListElement' in item:
                        for el in item['itemListElement']:
                            prod = el.get('item', el)
                            if isinstance(prod, dict) and prod.get('name'):
                                offers = prod.get('offers', {})
                                price = offers.get('price') if isinstance(offers, dict) else None
                                url = prod.get('url', '')
                                products.append({
                                    'title': prod.get('name', ''),
                                    'price': float(price) if price else None,
                                    'url': url,
                                })
                    elif item.get('@type') == 'Product':
                        offers = item.get('offers', {})
                        price = offers.get('price') if isinstance(offers, dict) else None
                        url = item.get('url', '')
                        if item.get('name'):
                            products.append({
                                'title': item.get('name', ''),
                                'price': float(price) if price else None,
                                'url': url,
                            })
        except Exception as e:
            logger.debug(f"[Adorama] JSON-LD extraction failed: {e}")

        return products

    def _extract_from_html(self, html: str) -> list[dict]:
        """用 CSS 选择器提取"""
        products = []
        soup = BeautifulSoup(html, 'html.parser')

        item_selectors = [
            'div.category-product-item',
            'div.product-item',
            'li.item',
            'div[class*="product"]',
            'article[class*="product"]',
        ]

        items = []
        for sel in item_selectors:
            items = soup.select(sel)
            if items:
                break

        # 备用：找产品链接
        if not items:
            links = soup.select('a[href*="/adorama/"]') or soup.select('a.product-link')
            for link in links:
                parent = link.find_parent('div') or link.find_parent('li')
                if parent:
                    items.append(parent)

        for item in items:
            product = self._parse_html_item(item)
            if product:
                products.append(product)

        return products

    def _parse_html_item(self, item) -> dict | None:
        """解析单个 HTML 元素"""
        title = ''
        url = ''

        link_selectors = [
            'a.item-title',
            'a[class*="product"]',
            'a[href*="/adorama/"]',
            'a.product-link',
        ]
        for sel in link_selectors:
            el = item.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                href = el.get('href', '')
                if href:
                    url = ('https://www.adorama.com' + href) if href.startswith('/') else href
                break

        if not title:
            title_el = item.select_one('.product-title, .item-title, h2, h3')
            if title_el:
                title = title_el.get_text(strip=True)

        if not title:
            return None

        # 价格
        price = None
        price_selectors = [
            'span.price-wrapper span.price',
            'span.our-price',
            'p.price',
            'span[class*="price"]',
            'div[class*="price"]',
        ]
        for sel in price_selectors:
            el = item.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                price = extract_price_from_text(text)
                if price:
                    break

        if price is None:
            text = item.get_text()
            price = extract_price_from_text(text)

        return {
            'title': title,
            'price': price,
            'url': url,
        }

    def _extract_with_regex(self, html: str) -> list[dict]:
        """正则回退"""
        products = []

        # Adorama 产品链接
        pattern = re.compile(
            r'href="(/adorama/[^"]+)"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)',
            re.IGNORECASE
        )
        for match in pattern.finditer(html):
            href = match.group(1)
            title = match.group(2).strip()
            url = 'https://www.adorama.com' + href

            if title and len(title) > 5:
                idx = html.find(href)
                nearby = html[idx:idx + 3000] if idx >= 0 else ''
                price = extract_price_from_text(nearby) if nearby else None
                products.append({
                    'title': title,
                    'price': price,
                    'url': url,
                })

        return products
