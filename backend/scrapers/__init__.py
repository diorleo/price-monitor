"""
scrapers/__init__.py — 爬虫注册表
"""
from .amazon import AmazonScraper
from .bestbuy import BestBuyScraper
from .bhphoto import BHPhotoScraper
from .newegg import NeweggScraper
from .adorama import AdoramaScraper
from .walmart import WalmartScraper
from .mozaofficial import MozaOfficialScraper

SCRAPER_REGISTRY = {
    "Amazon US": AmazonScraper,
    "Best Buy": BestBuyScraper,
    "B&H Photo": BHPhotoScraper,
    "Newegg": NeweggScraper,
    "Adorama": AdoramaScraper,
    "Walmart": WalmartScraper,
    "MOZA Official": MozaOfficialScraper,
}


def get_scraper(channel_name: str, products, delay=2.0, retries=3):
    """根据渠道名获取对应爬虫实例，找不到时返回 None"""
    cls = SCRAPER_REGISTRY.get(channel_name)
    if cls:
        return cls(products, delay=delay, retries=retries)
    return None
