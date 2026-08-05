"""
scrapers/walmart.py — Walmart 爬虫（v2 重写）

改进点：
1. 多搜索词：MOZA RACING (2页) + MOZA (1页)
2. __NEXT_DATA__ JSON 优先解析（Walmart 用 Next.js）
3. 智能产品匹配（共享 match_product 方法）
4. 多策略 CSS 选择器 + 正则回退
5. Walmart 有 31+ 个 MOZA RACING 产品
"""
import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page, extract_price_from_text

logger = logging.getLogger(__name__)


class WalmartScraper(BaseScraper):
    channel_name = "Walmart"
    channel_url = "https://www.walmart.com"
    SEARCH_URL = "https://www.walmart.com/search?q={query}"

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
                    logger.warning(f"[Walmart] Failed to fetch: {query} page {page}")
                    continue

                # 检测 CAPTCHA/反爬页面
                if 'robot or human' in html.lower() or 'captcha' in html.lower()[:500]:
                    logger.warning(f"[Walmart] CAPTCHA/bot detection page detected for {query} page {page}")
                    continue

                page_products = self._parse_search_results(html)
                if not page_products:
                    logger.info(f"[Walmart] No products on {query} page {page}, stopping")
                    break

                all_products.extend(page_products)
                logger.info(f"[Walmart] {query} page {page}: found {len(page_products)} products")

        # 去重（按产品ID/URL）
        seen = set()
        unique = []
        for p in all_products:
            key = p.get('product_id', '') or p.get('url', '')
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        logger.info(f"[Walmart] Total unique products after dedup: {len(unique)}")

        fallback_url = self.SEARCH_URL.format(query="moza+racing")
        if not unique:
            logger.warning("[Walmart] No products found, returning all Missing")
            return [self._make_result(p['code'], p['name'], p['msrp'], None, fallback_url)
                    for p in self.products if p.get('status') == 'Active']

        return self._match_all_products(unique, fallback_url)

    def _parse_search_results(self, html: str) -> list[dict]:
        """解析 Walmart 搜索结果页"""
        products = []

        # 策略 1: 从 __NEXT_DATA__ JSON 提取（最可靠）
        products.extend(self._extract_from_next_data(html))

        # 策略 2: 从 JSON-LD 提取
        products.extend(self._extract_from_json_ld(html))

        # 策略 3: CSS 选择器
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
        """从 __NEXT_DATA__ script 标签中提取产品数据"""
        products = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            script = soup.find('script', id='__NEXT_DATA__')
            if not script or not script.string:
                return products

            data = json.loads(script.string)

            # Walmart Next.js 数据路径可能有多种
            paths_to_try = [
                # 搜索结果路径
                ('props', 'pageProps', 'initialData', 'searchResult', 'itemStacks'),
                ('props', 'pageProps', 'searchResult', 'itemStacks'),
                ('props', 'pageProps', 'initialData', 'searchResult', 'results'),
                ('props', 'pageProps', 'searchResults', 'results'),
                ('props', 'pageProps', 'items'),
            ]

            item_stacks = None
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
                    item_stacks = obj
                    break

            if item_stacks:
                # itemStacks 是一个列表，每个元素含 items
                if isinstance(item_stacks, list):
                    for stack in item_stacks:
                        if isinstance(stack, dict) and 'items' in stack:
                            for item in stack['items']:
                                self._parse_next_data_item(item, products)
                elif isinstance(item_stacks, list):
                    for item in item_stacks:
                        self._parse_next_data_item(item, products)

            # 如果上面没找到，尝试从 props.pageProps 中搜索所有含 'price' 的 dict
            if not products:
                page_props = data.get('props', {}).get('pageProps', {})
                self._deep_search_items(page_props, products)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"[Walmart] __NEXT_DATA__ extraction failed: {e}")

        return products

    def _parse_next_data_item(self, item: dict, products: list):
        """解析单个 __NEXT_DATA__ 产品项"""
        title = (item.get('name', '') or item.get('title', '')
                 or item.get('productDisplayName', ''))
        if not title:
            return

        # 价格提取（多种路径）
        price = None
        price_info = item.get('priceInfo', {})
        if isinstance(price_info, dict):
            price = price_info.get('currentPrice', {})
            if isinstance(price, dict):
                price = price.get('price')
            elif not isinstance(price, (int, float)):
                price = None
        if price is None:
            price = item.get('price')
            if isinstance(price, dict):
                price = price.get('currentPrice') or price.get('price')

        # 产品 ID 和 URL
        pid = item.get('usItemId', '') or item.get('productId', '') or item.get('id', '')
        canonical_url = item.get('canonicalUrl', '') or item.get('productUrl', '')
        if canonical_url and not canonical_url.startswith('http'):
            canonical_url = 'https://www.walmart.com' + canonical_url
        if not canonical_url and pid:
            canonical_url = f"https://www.walmart.com/ip/{pid}"

        products.append({
            'title': title,
            'price': float(price) if price else None,
            'url': canonical_url,
            'product_id': str(pid) if pid else '',
        })

    def _deep_search_items(self, obj: dict, products: list, depth: int = 0):
        """递归搜索 JSON 对象中所有看起来像产品的项"""
        if depth > 5 or not isinstance(obj, dict):
            return

        # 如果这个对象看起来像一个产品（有 name/title 和 price）
        title = obj.get('name', '') or obj.get('title', '')
        has_price = ('priceInfo' in obj or 'price' in obj
                     or 'currentPrice' in obj)
        if title and has_price and 'moza' in title.lower():
            self._parse_next_data_item(obj, products)
            return  # 已经解析了，不需要递归其子项

        for key, val in obj.items():
            if isinstance(val, dict):
                self._deep_search_items(val, products, depth + 1)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        self._deep_search_items(item, products, depth + 1)

    def _extract_from_json_ld(self, html: str) -> list[dict]:
        """从 JSON-LD 结构化数据中提取"""
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
                    if item.get('@type') == 'ItemList' and 'itemListElement' in item:
                        for el in item['itemListElement']:
                            prod = el.get('item', el)
                            if isinstance(prod, dict) and prod.get('name'):
                                offers = prod.get('offers', {})
                                price = offers.get('price') if isinstance(offers, dict) else None
                                url = prod.get('url', '')
                                if prod.get('name'):
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
            logger.debug(f"[Walmart] JSON-LD extraction failed: {e}")

        return products

    def _extract_from_html(self, html: str) -> list[dict]:
        """用 CSS 选择器提取产品"""
        products = []
        soup = BeautifulSoup(html, 'html.parser')

        # Walmart 多版本选择器
        item_selectors = [
            'div[data-item-id]',
            'div.search-result-listview-item',
            'div[class*="search-result"]',
            'div.mb0.ph1.pa0-xl.bb.b--light-gray',
            'article[data-testid="item-card"]',
            'div[data-testid="list-item"]',
        ]

        items = []
        for sel in item_selectors:
            items = soup.select(sel)
            if items:
                break

        # 备用：找所有产品链接
        if not items:
            links = soup.select('a[href*="/ip/"]')
            for link in links:
                parent = link.find_parent('div') or link.find_parent('article')
                if parent:
                    items.append(parent)

        for item in items:
            product = self._parse_html_item(item)
            if product:
                products.append(product)

        return products

    def _parse_html_item(self, item) -> dict | None:
        """解析单个 HTML 产品元素"""
        title = ''
        url = ''

        # 标题和链接
        link_selectors = [
            'a[href*="/ip/"]',
            'span.lh-title',
            'span[data-automation="product-title"]',
            'a[data-automation="productLink"]',
        ]
        for sel in link_selectors:
            el = item.select_one(sel)
            if el:
                if el.name == 'a':
                    title = el.get_text(strip=True)
                    href = el.get('href', '')
                    if href:
                        url = ('https://www.walmart.com' + href) if href.startswith('/') else href
                else:
                    title = el.get_text(strip=True)
                    parent_a = el.find_parent('a')
                    if parent_a:
                        href = parent_a.get('href', '')
                        if href:
                            url = ('https://www.walmart.com' + href) if href.startswith('/') else href
                break

        if not title:
            title_el = item.select_one('[data-automation="product-title"], .product-title, span.lh-copy')
            if title_el:
                title = title_el.get_text(strip=True)

        if not title:
            return None

        # 价格
        price = None
        price_selectors = [
            'span[data-automation="buy-price"]',
            'div[data-automation="price"] span',
            'span.price-group',
            'span[class*="price"]',
            'div[class*="Price"] span',
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

        # 产品 ID
        pid_match = re.search(r'/ip/(\d+)', url)
        pid = pid_match.group(1) if pid_match else ''

        return {
            'title': title,
            'price': price,
            'url': url,
            'product_id': pid,
        }

    def _extract_with_regex(self, html: str) -> list[dict]:
        """正则回退：从 HTML 中提取产品链接和价格"""
        products = []

        # Walmart 产品 URL 格式: /ip/{name}/{id}
        pattern = re.compile(
            r'href="(/ip/[^"]+/(\d+))"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)',
            re.IGNORECASE
        )
        for match in pattern.finditer(html):
            href = match.group(1)
            pid = match.group(2)
            title = match.group(3).strip()
            url = 'https://www.walmart.com' + href
            if title and len(title) > 5:
                products.append({
                    'title': title,
                    'price': None,
                    'url': url,
                    'product_id': pid,
                })

        # 在每个 URL 附近搜索价格
        for prod in products:
            search_href = prod['url'].replace('https://www.walmart.com', '')
            idx = html.find(search_href)
            if idx >= 0:
                nearby = html[idx:idx + 3000]
                price = extract_price_from_text(nearby)
                if price:
                    prod['price'] = price

        return products
