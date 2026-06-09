"""
crawl_engine.py — 爬取引擎：调度各爬虫、写入数据库、生成日志
"""
import json
import logging
from datetime import datetime, timezone

from database import get_conn, init_db
from scrapers import get_scraper

logger = logging.getLogger(__name__)


def _get_settings() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}


def _get_products() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT code, name, catalog, msrp, status FROM products WHERE status='Active'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_active_channels() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, url, listing_url, type, freq, status FROM channels WHERE status='Active'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _calc_status(diff_pct: float | None, thresh_low: float, thresh_high: float, thresh_crit: float) -> str:
    if diff_pct is None:
        return "Missing"
    if abs(diff_pct) <= 1.0:
        return "Normal"
    if diff_pct < -thresh_crit:
        return "Critical"
    if diff_pct < -thresh_low:
        return "Low"
    if diff_pct > thresh_high:
        return "High"
    return "Normal"


def run_crawl(task_id: int) -> dict:
    """
    执行一次完整的爬取任务，结果写入数据库。
    返回 summary dict: {success, products, channels, anomalies, errors}
    """
    settings = _get_settings()
    delay = float(settings.get('delay', 2))
    retries = int(settings.get('retry', 3))
    thresh_low = float(settings.get('thresh_low', 5))
    thresh_high = float(settings.get('thresh_high', 10))
    thresh_crit = float(settings.get('thresh_critical', 20))

    products = _get_products()
    channels = _get_active_channels()

    if not products:
        return {"success": False, "error": "No active products found"}
    if not channels:
        return {"success": False, "error": "No active channels found"}

    all_results = []
    errors = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conn = get_conn()
    c = conn.cursor()

    # 清空本次快照
    c.execute("DELETE FROM price_snapshots")

    for channel in channels:
        ch_name = channel['name']
        scraper = get_scraper(ch_name, products, delay=delay, retries=retries)

        if scraper is None:
            logger.warning(f"[Engine] No scraper registered for channel: {ch_name}")
            errors.append(f"No scraper for: {ch_name}")
            continue

        logger.info(f"[Engine] Crawling {ch_name}...")

        try:
            results = scraper.scrape()
            # 修正 status 根据阈值
            for r in results:
                if r.get('diff_pct') is not None:
                    r['status'] = _calc_status(r['diff_pct'], thresh_low, thresh_high, thresh_crit)
            all_results.extend(results)

            # 写入快照
            for r in results:
                c.execute("""
                    INSERT INTO price_snapshots
                    (channel_id, channel, product_code, product_name, msrp,
                     listing_price, price_diff, diff_pct, status, product_url, crawl_time, task_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    channel['id'], r['channel'], r['product_code'], r['product_name'],
                    r['msrp'], r.get('listing_price'), r.get('price_diff'), r.get('diff_pct'),
                    r['status'], r.get('product_url', ''), r['crawl_time'], task_id
                ))
                # 追加历史
                c.execute("""
                    INSERT INTO price_history
                    (channel_id, channel, product_code, product_name, msrp,
                     listing_price, price_diff, diff_pct, status, product_url, crawl_time, date, task_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    channel['id'], r['channel'], r['product_code'], r['product_name'],
                    r['msrp'], r.get('listing_price'), r.get('price_diff'), r.get('diff_pct'),
                    r['status'], r.get('product_url', ''), r['crawl_time'], today, task_id
                ))
        except Exception as e:
            logger.error(f"[Engine] Channel {ch_name} failed: {e}")
            errors.append(f"{ch_name}: {str(e)[:100]}")

    # 更新任务日志
    anomalies = len([r for r in all_results if r.get('status') not in ('Normal', None)])
    end_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    c.execute("""
        UPDATE task_logs SET
            status=?, end_time=?, products=?, channels=?, anomalies=?, errors=?,
            details=?
        WHERE id=?
    """, (
        'success' if not errors else 'partial',
        end_time,
        len(all_results),
        len(channels),
        anomalies,
        json.dumps(errors),
        f"Crawled {len(all_results)} listings across {len(channels)} channels. "
        f"{anomalies} anomalies. {len(errors)} channel errors.",
        task_id
    ))

    conn.commit()
    conn.close()

    logger.info(f"[Engine] Done. {len(all_results)} results, {anomalies} anomalies, {len(errors)} errors.")
    return {
        "success": True,
        "products": len(all_results),
        "channels": len(channels),
        "anomalies": anomalies,
        "errors": errors,
    }
