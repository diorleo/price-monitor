"""
scrapers/base.py — 爬虫基类，封装重试、延时、请求头轮换、产品匹配等共享逻辑
"""
import re
import time
import random
import logging
import requests
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.8",
    "en;q=0.9,en-US;q=0.8",
]


def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }


def fetch_page(url: str, retries: int = 3, delay: float = 2.0, timeout: int = 20) -> str | None:
    """带重试的 HTTP GET，返回 HTML 文本或 None"""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url,
                headers=get_headers(),
                timeout=timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            jitter = random.uniform(0.5, 1.5)
            time.sleep(delay * jitter)
            return resp.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            logger.warning(f"[Fetch] HTTP {status} on {url} (attempt {attempt}/{retries})")
            if status in (403, 429, 503):
                time.sleep(delay * attempt * 3)
        except requests.exceptions.ConnectionError:
            logger.warning(f"[Fetch] ConnectionError on {url} (attempt {attempt}/{retries})")
            time.sleep(delay * attempt)
        except requests.exceptions.Timeout:
            logger.warning(f"[Fetch] Timeout on {url} (attempt {attempt}/{retries})")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"[Fetch] Unexpected error on {url}: {e}")
            break
    return None


# ═══════════════════════════════════════════════════════════════
# 共享：MOZA 产品型号词模式 & 关键词提取
# ═══════════════════════════════════════════════════════════════

# MOZA 产品型号词模式（含不带数字的型号如 KS, ES, FSR, CS）
MODEL_PATTERN = re.compile(
    r'\b[Rr]\d+\b'                          # R系列: R3, R5, R9, R12, R16, R21, R25
    r'|\b[A-Z]{2,4}\d+\b'                   # 字母+数字: CRP2, SRP2, AB9, AY210, AB6
    r'|\b[A-Z]{2}-[A-Z]\d*\b'               # 连字符型号: SR-P
    r'|\b[A-Z]{2}-[A-Z]\b'                  # 连字符无数字: SR-P
    r'|\b(?:KS|ES|FSR|CS|mBooster|MTLP|AMPCD|CM2|HGP|HBP|SGP|TSW|MRP|MFY|MHG|MTP|MTQ|ESX|AB6|AB9|AY90|AY210|MH16|MA3X|Z-Axis)\b'
    , re.IGNORECASE
)

# 系列关键词（辅助匹配，权重较低）
SERIES_PATTERN = re.compile(
    r'\b(Flight|Racing|Sim|Bundle|Pedal|Wheel|Base|Grip|Throttle|Rudder|Dashboard|Shifter|Clutch|Truck|Formula|Yoke|Panel|Stalks|Adapter|Clamp|Plate|Mod|Kit|Damper|Hub|Stick|Sidestick|Handbrake|Switch|Knob|Performance|Inversion|Extension|Quick Release|Table|Multi-?function)\b'
    , re.IGNORECASE
)


def extract_keywords(name: str) -> list[str]:
    """从产品名中提取关键型号词，如 R5, CRP2, SRP2, R3, R9, KS, ES 等"""
    keywords = MODEL_PATTERN.findall(name)
    series = SERIES_PATTERN.findall(name)
    keywords.extend(series)
    return keywords


def _keyword_in_text(kw: str, text: str) -> bool:
    """检查关键词是否作为独立词出现在文本中（词边界匹配）"""
    # 对短关键词（2-3字母如 ES, KS, CS）使用严格的词边界
    if len(kw) <= 3:
        pattern = r'\b' + re.escape(kw) + r'\b'
        return bool(re.search(pattern, text, re.IGNORECASE))
    # 长关键词可以直接做子串匹配
    return kw.lower() in text


def match_product(product: dict, search_results: list[dict],
                  min_score: int = 15) -> dict | None:
    """
    将我们的产品与搜索结果进行智能匹配。
    型号词匹配权重最高，使用词边界避免错误匹配。

    Args:
        product: {code, name, catalog, msrp, status}
        search_results: [{title, price, url, ...}, ...]
        min_score: 最低匹配分数

    Returns: 匹配的搜索结果 dict 或 None
    """
    product_name = product['name'].lower()
    keywords = extract_keywords(product['name'])

    # 型号词（R5, CRP2, KS, ES 等）是强匹配信号
    model_keywords = [kw for kw in keywords
                      if MODEL_PATTERN.match(kw)]

    best_match = None
    best_score = 0

    for result in search_results:
        result_title = result.get('title', '').lower()
        if not result_title:
            continue

        # 只考虑包含 "moza" 的结果（排除不相关产品）
        if 'moza' not in result_title:
            continue

        score = 0
        model_matched = False
        wrong_model = False

        # 检查结果标题中包含哪些型号词
        result_models = set()
        for mk in model_keywords:
            if _keyword_in_text(mk, result_title):
                result_models.add(mk.lower())

        # 关键约束：如果产品有型号词，但结果中不含任何该型号词
        # 且结果中含有其他型号词，则跳过（明显是不同产品）
        product_models_lower = {mk.lower() for mk in model_keywords}
        if product_models_lower:
            if not product_models_lower & result_models:
                # 结果不含我们产品的型号词
                if result_models:
                    # 结果含有其他型号词 → 不同产品，跳过
                    continue
                else:
                    # 结果没有型号词 → 大幅减分但不直接跳过
                    score -= 30

        # 关键词匹配（使用词边界）
        for kw in keywords:
            if _keyword_in_text(kw, result_title):
                score += 10
                if kw in model_keywords:
                    model_matched = True
                    score += 15  # 型号匹配额外加分

        # 如果产品有型号但结果中没有对应型号，大幅减分
        if model_keywords and not model_matched:
            score -= 30

        # 产品名子串匹配
        name_words = product_name.split()
        for word in name_words:
            if len(word) > 2 and word.lower() in result_title:
                score += 2

        # 完全匹配
        if product_name in result_title or result_title in product_name:
            score += 20

        if score > best_score:
            best_score = score
            best_match = result

    if best_match and best_score >= min_score:
        return best_match

    return None


def extract_price_from_text(text: str) -> float | None:
    """从文本中提取价格，支持 $XXX.XX 和 SGD XXX.XX 等格式"""
    # 先找 $ 价格
    m = re.search(r'\$\s*([\d,]+\.?\d{2})', text)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            pass

    # 找 SGD 或其他货币
    m = re.search(r'(?:SGD|USD|EUR)\s*([\d,]+\.?\d{2})', text)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            pass

    # 纯数字价格
    m = re.search(r'([\d,]+\.?\d{2})', text)
    if m:
        try:
            val = float(m.group(1).replace(',', ''))
            if val > 1:  # 过滤掉 0.00 等
                return val
        except ValueError:
            pass

    return None


class BaseScraper(ABC):
    """所有渠道爬虫的基类"""

    channel_name: str = ""
    channel_url: str = ""

    def __init__(self, products: list[dict], delay: float = 2.0, retries: int = 3):
        self.products = products   # [{code, name, catalog, msrp, status}, ...]
        self.delay = delay
        self.retries = retries

    @abstractmethod
    def scrape(self) -> list[dict]:
        """
        执行爬取，返回列表，每条记录：
        {
          channel, product_code, product_name, msrp,
          listing_price, product_url, crawl_time, status
        }
        """
        raise NotImplementedError

    def _make_result(self, code: str, name: str, msrp: float,
                     price: float | None, url: str) -> dict:
        from datetime import datetime, timezone
        crawl_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if price is None:
            diff = None
            diff_pct = None
            status = "Missing"
        else:
            diff = round(price - msrp, 2)
            diff_pct = round((price - msrp) / msrp * 100, 2) if msrp > 0 else 0
            status = self._calc_status(diff_pct)
        return {
            "channel": self.channel_name,
            "product_code": code,
            "product_name": name,
            "msrp": msrp,
            "listing_price": price,
            "price_diff": diff,
            "diff_pct": diff_pct,
            "status": status,
            "product_url": url,
            "crawl_time": crawl_time,
        }

    @staticmethod
    def _calc_status(diff_pct: float) -> str:
        if diff_pct is None:
            return "Missing"
        if abs(diff_pct) <= 1:
            return "Normal"
        if diff_pct < -20:
            return "Critical"
        if diff_pct < 0:
            return "Low"
        if diff_pct > 10:
            return "High"
        return "Normal"

    # 共享方法：批量匹配产品
    def _match_all_products(self, search_results: list[dict],
                            fallback_url: str = "") -> list[dict]:
        """用 match_product 将所有产品匹配到搜索结果，返回结果列表"""
        results = []
        active = [p for p in self.products if p.get('status') == 'Active']

        for product in active:
            matched = match_product(product, search_results)
            if matched:
                price = matched.get('price')
                url = matched.get('url', '')
                logger.info(f"[{self.channel_name}] Matched {product['code']} -> "
                           f"{matched.get('title', '')[:50]} @ ${price}")
                results.append(self._make_result(
                    product['code'], product['name'], product['msrp'], price, url))
            else:
                logger.info(f"[{self.channel_name}] No match for "
                           f"{product['code']} ({product['name'][:40]})")
                results.append(self._make_result(
                    product['code'], product['name'], product['msrp'], None, fallback_url))

        return results
