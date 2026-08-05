"""
scrapers/bestbuy.py — Best Buy 爬虫（v3 重写）

改进点：
1. 多搜索词 + 分页遍历，覆盖 Best Buy 不一致的搜索算法
   - "MOZA RACING" (3页): 赛车产品主力
   - "MOZA" (3页): 飞行模拟 + 全品类
   - "MOZA R9" (1页): R9/R12 等隐藏产品
2. SKU 去重，避免重复抓取
3. 多策略 CSS 选择器 + 正则回退
4. 添加 intl=nosplash 参数避免国际重定向
5. 提取库存状态、SKU 等更多信息
"""
import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page, match_product

logger = logging.getLogger(__name__)


class BestBuyScraper(BaseScraper):
    channel_name = "Best Buy"
    channel_url = "https://www.bestbuy.com"
    SEARCH_URL = "https://www.bestbuy.com/site/searchpage.jsp?st={query}&intl=nosplash"

    # 多搜索词配置: (搜索词, 最大页数)
    # Best Buy 搜索算法不一致——"MOZA RACING" 不返回 R9/R12，
    # 但 "MOZA R9" 能返回。需要多词覆盖。
    SEARCH_QUERIES = [
        ("MOZA+RACING", 3),
        ("MOZA", 3),
        ("MOZA+R9", 1),
    ]

    def scrape(self) -> list[dict]:
        """多搜索词 + 分页遍历，合并去重后匹配所有产品"""
        results = []
        active = [p for p in self.products if p['status'] == 'Active']

        if not active:
            return results

        # ── 多搜索词 + 分页 ──
        all_products = []
        for query, max_pages in self.SEARCH_QUERIES:
            for page in range(1, max_pages + 1):
                search_url = self.SEARCH_URL.format(query=query)
                if page > 1:
                    search_url += f"&cp={page}"

                html = fetch_page(search_url, retries=self.retries, delay=self.delay)
                if not html:
                    logger.warning(f"[BestBuy] Failed to fetch: {query} page {page}")
                    continue

                page_products = self._parse_search_results(html)
                if not page_products:
                    logger.info(f"[BestBuy] No products on {query} page {page}, stopping pagination")
                    break

                all_products.extend(page_products)
                logger.info(f"[BestBuy] {query} page {page}: found {len(page_products)} products")

        # ── SKU 去重 ──
        seen_skus = set()
        unique_products = []
        for p in all_products:
            sku = p.get('sku', '')
            url = p.get('url', '')
            # 优先用 SKU 去重，没有 SKU 时用 URL
            dedup_key = sku if sku else url
            if dedup_key and dedup_key not in seen_skus:
                seen_skus.add(dedup_key)
                unique_products.append(p)

        logger.info(f"[BestBuy] Total unique products after dedup: {len(unique_products)}")

        if not unique_products:
            logger.warning("[BestBuy] No products found in any search")
            fallback_url = self.SEARCH_URL.format(query="MOZA+RACING")
            return [self._make_result(p['code'], p['name'], p['msrp'], None, fallback_url)
                    for p in active]

        fallback_url = self.SEARCH_URL.format(query="MOZA+RACING")
        return self._match_all_products(unique_products, fallback_url)

    def _parse_search_results(self, html: str) -> list[dict]:
        """解析搜索结果页 HTML，返回产品列表"""
        products = []

        # ── 策略 1: 从 __NEXT_DATA__ JSON 中提取（最可靠）──
        products.extend(self._extract_from_next_data(html))

        # ── 策略 2: 从 JSON-LD 结构化数据中提取 ──
        products.extend(self._extract_from_json_ld(html))

        # ── 策略 3: 用 CSS 选择器解析 HTML ──
        products.extend(self._extract_from_html(html))

        # ── 策略 4: 用正则从 HTML 中提取产品链接和价格 ──
        if not products:
            products.extend(self._extract_with_regex(html))

        # 去重（按 URL 或标题）
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

            # Best Buy 的 Next.js 数据路径可能不同，尝试多种路径
            search_results = None
            paths_to_try = [
                ('props', 'pageProps', 'initialState', 'search', 'results'),
                ('props', 'pageProps', 'search', 'results'),
                ('props', 'pageProps', 'data', 'results'),
                ('props', 'pageProps', 'products'),
            ]
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
                    search_results = obj
                    break

            if not search_results:
                return products

            for item in search_results:
                if not isinstance(item, dict):
                    continue
                title = item.get('names', {}).get('title', '') or item.get('name', '')
                price = item.get('prices', {}).get('current', {}).get('price')
                if price is None:
                    price = item.get('salePrice') or item.get('regularPrice')
                sku = item.get('skuId') or item.get('sku', '')
                url = item.get('url', '') or item.get('pdpUrl', '')
                if url and not url.startswith('http'):
                    url = 'https://www.bestbuy.com' + url
                in_stock = item.get('inventory', {}).get('online', False)

                if title:
                    products.append({
                        'title': title,
                        'price': float(price) if price else None,
                        'url': url,
                        'sku': str(sku),
                        'in_stock': in_stock,
                    })
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"[BestBuy] __NEXT_DATA__ extraction failed: {e}")

        return products

    def _extract_from_json_ld(self, html: str) -> list[dict]:
        """从 JSON-LD 结构化数据中提取产品数据"""
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
                    # 可能在 @graph 里
                    if '@graph' in item:
                        items.extend(item['@graph'])
                        continue
                    if item.get('@type') not in ('Product', 'ItemList'):
                        continue

                    if item.get('@type') == 'ItemList' and 'itemListElement' in item:
                        for el in item['itemListElement']:
                            prod = el.get('item', el)
                            self._parse_json_ld_product(prod, products)
                    else:
                        self._parse_json_ld_product(item, products)
        except Exception as e:
            logger.debug(f"[BestBuy] JSON-LD extraction failed: {e}")

        return products

    def _parse_json_ld_product(self, item: dict, products: list):
        """解析单个 JSON-LD 产品对象"""
        title = item.get('name', '')
        if not title:
            return
        price = None
        offers = item.get('offers', {})
        if isinstance(offers, dict):
            price = offers.get('price')
            availability = offers.get('availability', '')
        elif isinstance(offers, list) and offers:
            price = offers[0].get('price')
            availability = offers[0].get('availability', '')
        else:
            availability = ''
        url = item.get('url', '')
        in_stock = 'InStock' in availability or 'in stock' in availability.lower()
        products.append({
            'title': title,
            'price': float(price) if price else None,
            'url': url,
            'sku': str(item.get('sku', '')),
            'in_stock': in_stock,
        })

    def _extract_from_html(self, html: str) -> list[dict]:
        """用 CSS 选择器从 HTML 中提取产品数据"""
        products = []
        soup = BeautifulSoup(html, 'html.parser')

        # 多种选择器策略（从旧到新）
        item_selectors = [
            'li.sku-item',
            'li[data-sku-id]',
            'div[data-sku-id]',
            'li.shop-sku-list-item',
            'div.list-item',
            'li[class*="sku"]',
            'div[class*="sku-item"]',
        ]

        items = []
        for sel in item_selectors:
            items = soup.select(sel)
            if items:
                logger.debug(f"[BestBuy] Found {len(items)} items with selector: {sel}")
                break

        # 如果选择器都没找到，尝试找所有包含产品链接的 li
        if not items:
            links = soup.select('a[href*="/product/"]')
            for link in links:
                parent = link.find_parent('li') or link.find_parent('div')
                if parent and parent not in items:
                    items.append(parent)
            if items:
                logger.debug(f"[BestBuy] Found {len(items)} items via product link parents")

        for item in items:
            product = self._parse_html_item(item)
            if product:
                products.append(product)

        return products

    def _parse_html_item(self, item) -> dict | None:
        """解析单个产品 HTML 元素"""
        # 提取产品链接和标题
        link_selectors = [
            'a.image-link',
            'a.sku-title',
            'a[class*="title"]',
            'a[href*="/product/"]',
            'h3 a',
            'h4 a',
        ]
        title = ''
        url = ''
        for sel in link_selectors:
            link_el = item.select_one(sel)
            if link_el:
                title = link_el.get_text(strip=True)
                href = link_el.get('href', '')
                if href:
                    url = ('https://www.bestbuy.com' + href) if href.startswith('/') else href
                break

        if not title:
            # 尝试从标题元素获取
            title_el = item.select_one('h3, h4, .title, [class*="title"]')
            if title_el:
                title = title_el.get_text(strip=True)

        if not title:
            return None

        # 提取价格
        price = None
        price_selectors = [
            'div.priceView-customer-price span[aria-hidden]',
            'div.priceView-hero-price span',
            'span.sr-only',
            'div[class*="price"] span',
            'span[class*="price"]',
            'div[class*="pricing"] span',
            'span[aria-hidden]',
        ]
        for sel in price_selectors:
            price_el = item.select_one(sel)
            if price_el:
                text = price_el.get_text(strip=True)
                m = re.search(r'\$?([\d,]+\.?\d*)', text)
                if m:
                    try:
                        price = float(m.group(1).replace(',', ''))
                        if price > 0:
                            break
                    except ValueError:
                        continue

        # 如果 CSS 选择器没找到价格，用正则在整个 item 文本中搜索
        if price is None:
            item_text = item.get_text()
            prices = re.findall(r'\$([\d,]+\.?\d{2})', item_text)
            if prices:
                try:
                    price = float(prices[0].replace(',', ''))
                except ValueError:
                    pass

        # 提取 SKU
        sku = ''
        sku_match = re.search(r'/sku/(\d+)', url)
        if sku_match:
            sku = sku_match.group(1)
        else:
            sku_attr = item.get('data-sku-id', '')
            if sku_attr:
                sku = sku_attr

        # 提取库存状态
        item_text = item.get_text().lower()
        in_stock = any(kw in item_text for kw in [
            'add to cart', 'pick up today', 'get it tomorrow', 'in stock',
            'free shipping', 'delivery available'
        ])

        return {
            'title': title,
            'price': price,
            'url': url,
            'sku': sku,
            'in_stock': in_stock,
        }

    def _extract_with_regex(self, html: str) -> list[dict]:
        """最后回退：用正则从 HTML 中提取产品链接和价格"""
        products = []

        # 找所有 /product/{slug}/{id}/sku/{sku} 格式的链接
        product_pattern = re.compile(
            r'href="((?:https://www\.bestbuy\.com)?/product/[^"]+/sku/\d+)"[^>]*>\s*'
            r'(?:<[^>]+>)*\s*([^<]+)',
            re.IGNORECASE
        )
        for match in product_pattern.finditer(html):
            url = match.group(1)
            title = match.group(2).strip()
            if not url.startswith('http'):
                url = 'https://www.bestbuy.com' + url
            if title and len(title) > 5:
                products.append({
                    'title': title,
                    'price': None,
                    'url': url,
                    'sku': '',
                    'in_stock': True,
                })

        # 在每个产品 URL 附近搜索价格
        for prod in products:
            # 搜索相对 URL（HTML 中存储的格式）
            search_url = prod['url']
            if search_url.startswith('https://www.bestbuy.com'):
                search_url = search_url[len('https://www.bestbuy.com'):]
            idx = html.find(search_url)
            if idx >= 0:
                # 在 URL 后 3000 字符内搜索价格
                nearby = html[idx:idx + 3000]
                price_match = re.search(r'\$([\d,]+\.?\d{2})', nearby)
                if price_match:
                    try:
                        prod['price'] = float(price_match.group(1).replace(',', ''))
                    except ValueError:
                        pass

        return products
