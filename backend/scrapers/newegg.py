"""
scrapers/newegg.py — Newegg 爬虫（v2 重写）

改进点：
1. 多搜索词 + 分页：MOZA RACING (2页) + MOZA (1页)
2. 智能产品匹配（共享 match_product 方法）
3. 多策略 CSS 选择器 + 正则回退
4. Newegg 有 24+ 个 MOZA RACING 产品

注意：Newegg 部分价格通过 JS 渲染，需要多策略提取
"""
import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page, extract_price_from_text

logger = logging.getLogger(__name__)


class NeweggScraper(BaseScraper):
    channel_name = "Newegg"
    channel_url = "https://www.newegg.com"
    SEARCH_URL = "https://www.newegg.com/p/pl?d={query}"

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
                    logger.warning(f"[Newegg] Failed to fetch: {query} page {page}")
                    continue

                page_products = self._parse_search_results(html)
                if not page_products:
                    logger.info(f"[Newegg] No products on {query} page {page}, stopping")
                    break

                all_products.extend(page_products)
                logger.info(f"[Newegg] {query} page {page}: found {len(page_products)} products")

        # 去重（按产品URL）
        seen = set()
        unique = []
        for p in all_products:
            key = p.get('url', '') or p.get('title', '')
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        logger.info(f"[Newegg] Total unique products after dedup: {len(unique)}")

        fallback_url = self.SEARCH_URL.format(query="moza+racing")
        if not unique:
            logger.warning("[Newegg] No products found, returning all Missing")
            return [self._make_result(p['code'], p['name'], p['msrp'], None, fallback_url)
                    for p in self.products if p.get('status') == 'Active']

        return self._match_all_products(unique, fallback_url)

    def _parse_search_results(self, html: str) -> list[dict]:
        """解析 Newegg 搜索结果页"""
        products = []

        # 策略 1: 从 __NEXT_DATA__ JSON 提取
        products.extend(self._extract_from_next_data(html))

        # 策略 2: 从 JSON-LD 提取
        products.extend(self._extract_from_json_ld(html))

        # 策略 3: CSS 选择器（多版本兼容）
        if not products:
            products.extend(self._extract_from_html(html))

        # 策略 4: 正则回退
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

    def _extract_from_next_data(self, html: str) -> list[dict]:
        """从 __NEXT_DATA__ script 提取产品"""
        products = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            script = soup.find('script', id='__NEXT_DATA__')
            if not script or not script.string:
                return products

            data = json.loads(script.string)

            # Newegg 的 Next.js 数据路径
            paths_to_try = [
                ('props', 'pageProps', 'searchResult', 'items'),
                ('props', 'pageProps', 'initialData', 'searchResult', 'items'),
                ('props', 'pageProps', 'products'),
                ('props', 'pageProps', 'data', 'Result', 'Items'),
                ('props', 'pageProps', 'searchResult', 'ProductList'),
            ]

            items = []
            for path in paths_to_try:
                obj = data
                found = True
                for key in path:
                    if isinstance(obj, dict) and key in obj:
                        obj = obj[key]
                    else:
                        found = False
                        break
                if found and obj:
                    items = obj
                    break

            for item in items:
                if not isinstance(item, dict):
                    continue
                title = item.get('Title', '') or item.get('title', '') or item.get('name', '')
                price = item.get('Price', '') or item.get('price', '')
                if isinstance(price, dict):
                    price = price.get('CurrentPrice') or price.get('currentPrice')
                url = item.get('LinkUrl', '') or item.get('url', '') or ''
                item_id = item.get('ItemId', '') or item.get('id', '')

                if title:
                    parsed_price = extract_price_from_text(str(price)) if price else None
                    if url and not url.startswith('http'):
                        url = 'https://www.newegg.com' + url
                    products.append({
                        'title': title,
                        'price': parsed_price,
                        'url': url or f"https://www.newegg.com/p/{item_id}" if item_id else '',
                    })
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"[Newegg] __NEXT_DATA__ extraction failed: {e}")

        return products

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
                    if item.get('@type') == 'Product':
                        title = item.get('name', '')
                        offers = item.get('offers', {})
                        if isinstance(offers, dict):
                            price = offers.get('price')
                        elif isinstance(offers, list) and offers:
                            price = offers[0].get('price')
                        else:
                            price = None
                        url = item.get('url', '')
                        if title:
                            products.append({
                                'title': title,
                                'price': float(price) if price else None,
                                'url': url,
                            })
                    elif item.get('@type') == 'ItemList' and 'itemListElement' in item:
                        for el in item['itemListElement']:
                            prod = el.get('item', el)
                            if isinstance(prod, dict) and prod.get('name'):
                                offers = prod.get('offers', {})
                                price = offers.get('price') if isinstance(offers, dict) else None
                                products.append({
                                    'title': prod.get('name', ''),
                                    'price': float(price) if price else None,
                                    'url': prod.get('url', ''),
                                })
        except Exception as e:
            logger.debug(f"[Newegg] JSON-LD extraction failed: {e}")

        return products

    def _extract_from_html(self, html: str) -> list[dict]:
        """用 CSS 选择器提取产品"""
        products = []
        soup = BeautifulSoup(html, 'html.parser')

        # 多版本选择器
        item_selectors = [
            'div.item-container',
            'div.item-cell',
            'div.list-item',
            'div[class*="item-container"]',
            'div[class*="product-card"]',
            'article[class*="product"]',
        ]

        items = []
        for sel in item_selectors:
            items = soup.select(sel)
            if items:
                logger.debug(f"[Newegg] Found {len(items)} items with: {sel}")
                break

        # 备用：找包含产品链接的元素
        if not items:
            links = soup.select('a[href*="/p/"]')
            for link in links:
                parent = link.find_parent('div') or link.find_parent('li')
                if parent and parent not in items:
                    items.append(parent)
            if items:
                logger.debug(f"[Newegg] Found {len(items)} items via /p/ links")

        for item in items:
            product = self._parse_html_item(item)
            if product:
                products.append(product)

        return products

    def _parse_html_item(self, item) -> dict | None:
        """解析单个产品元素"""
        title = ''
        url = ''

        # 提取标题和链接
        link_selectors = [
            'a.item-title',
            'a.title',
            'a[href*="/p/"]',
            'a[href*="/product/"]',
        ]
        for sel in link_selectors:
            el = item.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                href = el.get('href', '')
                if href:
                    url = href if href.startswith('http') else "https://www.newegg.com" + href
                break

        if not title:
            return None

        # 提取价格
        price = None
        price_selectors = [
            'li.price-current strong',
            'li.price-current',
            'span.price-current-label',
            'div.price-current strong',
            'div.product-price',
            'span.product-price',
            'div[class*="price"]',
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
        }

    def _extract_with_regex(self, html: str) -> list[dict]:
        """正则回退：从 HTML 中提取产品链接和价格"""
        products = []

        # 找 Newegg 产品链接
        pattern = re.compile(
            r'href="(https://www\.newegg\.com/p/[^"]+)"[^>]*>([^<]+)',
            re.IGNORECASE
        )
        for match in pattern.finditer(html):
            url = match.group(1)
            title = match.group(2).strip()
            if title and len(title) > 5:
                # 在 URL 附近搜索价格
                idx = html.find(url)
                nearby = html[idx:idx + 3000] if idx >= 0 else ''
                price = extract_price_from_text(nearby) if nearby else None
                products.append({
                    'title': title,
                    'price': price,
                    'url': url,
                })

        return products
