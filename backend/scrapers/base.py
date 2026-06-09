"""
scrapers/base.py — 爬虫基类，封装重试、延时、请求头轮换等反爬逻辑
"""
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
        "Accept-Encoding": "gzip, deflate, br",
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
