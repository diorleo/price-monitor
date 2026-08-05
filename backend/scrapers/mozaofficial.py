"""
scrapers/mozaofficial.py — MOZA 官方网站爬虫 (mozaracing.com)

改进点：
1. 多策略解析：Shopify JSON → CSS 选择器 → 正则回退
2. 智能产品匹配（共享 match_product 方法）
3. 支持 collections/all 和 collections/{category} 页面
4. Shopify 产品 JSON API 回退
5. 官方店价格即 MSRP，状态应始终为 Normal
"""
import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper, fetch_page, match_product, extract_price_from_text

logger = logging.getLogger(__name__)


class MozaOfficialScraper(BaseScraper):
    channel_name = "MOZA Official"
    channel_url = "https://mozaracing.com"

    # Shopify collections 页面
    COLLECTIONS_URL = "https://mozaracing.com/collections/all"
    # Shopify JSON API（获取产品列表 JSON）
    PRODUCTS_JSON_URL = "https://mozaracing.com/products.json"
    # 分页参数
    PRODUCTS_JSON_PAGED = "https://mozaracing.com/products.json?page={page}"

    def scrape(self) -> list[dict]:
        """多策略获取全量产品列表，然后智能匹配"""
        all_products = []

        # 策略 1: Shopify JSON API（最可靠）
        all_products.extend(self._fetch_from_json_api())

        # 如果 JSON API 获取到足够产品，直接匹配
        if len(all_products) < 10:
            # 策略 2: 从 collections/all 页面解析
            html = fetch_page(self.COLLECTIONS_URL, retries=self.retries, delay=self.delay)
            if html:
                all_products.extend(self._parse_collections_page(html))

        # 去重
        seen = set()
        unique = []
        for p in all_products:
            key = p.get('url', '') or p.get('title', '')
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        logger.info(f"[MOZA Official] Total products found: {len(unique)}")

        fallback_url = self.COLLECTIONS_URL
        if not unique:
            logger.warning("[MOZA Official] No products found")
            return [self._make_result(p['code'], p['name'], p['msrp'], None, fallback_url)
                    for p in self.products if p.get('status') == 'Active']

        return self._match_all_products(unique, fallback_url)

    def _fetch_from_json_api(self) -> list[dict]:
        """从 Shopify products.json API 获取产品列表"""
        products = []
        for page in range(1, 6):  # 最多 5 页
            url = self.PRODUCTS_JSON_PAGED.format(page=page)
            try:
                from .base import get_headers
                import requests
                resp = requests.get(url, headers=get_headers(), timeout=20)
                resp.raise_for_status()
                data = resp.json()
                page_products = data.get('products', [])
                if not page_products:
                    logger.info(f"[MOZA Official] JSON API page {page}: no products, stopping")
                    break

                for prod in page_products:
                    parsed = self._parse_shopify_json_product(prod)
                    if parsed:
                        products.append(parsed)

                logger.info(f"[MOZA Official] JSON API page {page}: {len(page_products)} products")
            except Exception as e:
                logger.debug(f"[MOZA Official] JSON API page {page} failed: {e}")
                break

        return products

    def _parse_shopify_json_product(self, prod: dict) -> dict | None:
        """解析 Shopify JSON API 单个产品"""
        title = prod.get('title', '')
        if not title:
            return None

        # Shopify 产品 handle → URL
        handle = prod.get('handle', '')
        url = f"https://mozaracing.com/products/{handle}" if handle else ''

        # 从 variants 提取价格（取第一个 variant）
        price = None
        variants = prod.get('variants', [])
        if variants and isinstance(variants, list):
            v = variants[0]
            # Shopify price 格式: "149.00" (字符串)
            price_str = str(v.get('price', '') or v.get('compare_at_price', ''))
            if price_str:
                price = extract_price_from_text(price_str)
                if price is None:
                    try:
                        price = float(price_str)
                    except ValueError:
                        pass

        return {
            'title': title,
            'price': price,
            'url': url,
        }

    def _parse_collections_page(self, html: str) -> list[dict]:
        """从 collections/all 页面 HTML 解析产品"""
        products = []
        soup = BeautifulSoup(html, 'html.parser')

        # Shopify 多版本选择器
        item_selectors = [
            'div.grid__item',
            'div.product-card',
            'div[class*="product-item"]',
            'li.grid__item',
            'div[class*="card"]',
            'article[class*="product"]',
            'div.product-block',
        ]

        items = []
        for sel in item_selectors:
            items = soup.select(sel)
            if items:
                logger.debug(f"[MOZA Official] Found {len(items)} items with: {sel}")
                break

        # 备用：找所有产品链接
        if not items:
            links = soup.select('a[href*="/products/"]')
            for link in links:
                parent = link.find_parent('div') or link.find_parent('li')
                if parent and parent not in items:
                    items.append(parent)

        for item in items:
            product = self._parse_html_item(item)
            if product:
                products.append(product)

        # 如果还是没有，用正则提取
        if not products:
            products.extend(self._extract_with_regex(html))

        return products

    def _parse_html_item(self, item) -> dict | None:
        """解析单个 HTML 产品元素"""
        title = ''
        url = ''

        # 标题和链接
        link_selectors = [
            'a[href*="/products/"]',
            '.product-title a',
            '.card-title a',
            '.product-name a',
            'a.product-card__title',
            '.product-item__title',
        ]
        for sel in link_selectors:
            el = item.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                href = el.get('href', '')
                if href:
                    url = ('https://mozaracing.com' + href) if href.startswith('/') else href
                break

        if not title:
            title_el = item.select_one('.product-title, .card-title, .product-name, .product-item__title')
            if title_el:
                title = title_el.get_text(strip=True)
            if not title:
                title_el = item.select_one('h2, h3, h4')
                if title_el:
                    title = title_el.get_text(strip=True)

        if not title:
            return None

        # 价格
        price = None
        price_selectors = [
            'span.price-item',
            'span.money',
            'span[class*="price"]',
            'div.price',
            'span.price',
            '.product-price',
            '.product-card__price',
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

        # Shopify 产品链接格式: /products/{handle}
        pattern = re.compile(
            r'href="(/products/[^"?]+)"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)',
            re.IGNORECASE
        )
        seen_handles = set()
        for match in pattern.finditer(html):
            href = match.group(1)
            if href in seen_handles:
                continue
            seen_handles.add(href)

            title = match.group(2).strip()
            url = 'https://mozaracing.com' + href

            if title and len(title) > 3:
                # 在 URL 附近搜索价格
                idx = html.find(href)
                nearby = html[idx:idx + 3000] if idx >= 0 else ''
                price = extract_price_from_text(nearby) if nearby else None

                products.append({
                    'title': title,
                    'price': price,
                    'url': url,
                })

        return products
