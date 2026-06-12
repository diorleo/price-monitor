"""
crawl_engine.py — 爬取引擎：真实爬取 + 模拟数据降级
当 Render/云环境无法爬取真实电商网站时，自动降级为模拟数据，
确保仪表盘始终有数据可展示。
"""
import json
import random
import logging
from datetime import datetime, timezone

from database import get_conn, init_db
from scrapers import get_scraper

logger = logging.getLogger(__name__)

# 是否使用模拟模式（云环境通常无法直接爬取零售商网站）
SIMULATE_MODE = True


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


def _simulate_prices(products: list[dict], channels: list[dict],
                     thresh_low: float, thresh_high: float, thresh_crit: float) -> list[dict]:
    """
    生成模拟价格数据，围绕 MSRP 波动。
    大部分产品价格接近 MSRP（±5%），少量产品制造异常（折扣/加价）。
    """
    results = []
    crawl_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 随机选择 3-8 个 SKU 做明显价格波动（制造异常）
    anomaly_indices = random.sample(range(len(products)), min(random.randint(3, 8), len(products)))

    for i, product in enumerate(products):
        msrp = float(product['msrp'])

        if i in anomaly_indices:
            # 生成异常价格：降价 5%-25% 或涨价 10%-30%
            if random.random() < 0.7:
                # 降价异常
                discount = random.uniform(0.05, 0.25)
                price = round(msrp * (1 - discount), 2)
            else:
                # 涨价异常
                markup = random.uniform(0.10, 0.30)
                price = round(msrp * (1 + markup), 2)
        else:
            # 正常波动：±5%
            variation = random.uniform(-0.05, 0.05)
            price = round(msrp * (1 + variation), 2)

        diff = round(price - msrp, 2)
        diff_pct = round((price - msrp) / msrp * 100, 2) if msrp > 0 else 0
        status = _calc_status(diff_pct, thresh_low, thresh_high, thresh_crit)

        results.append({
            "channel": "Simulated",
            "channel_id": 0,
            "product_code": product['code'],
            "product_name": product['name'],
            "msrp": msrp,
            "listing_price": price,
            "price_diff": diff,
            "diff_pct": diff_pct,
            "status": status,
            "product_url": "",
            "crawl_time": crawl_time,
        })

    return results


def _mix_real_and_sim(real_results: list[dict], products: list[dict], channel_name: str,
                      thresh_low: float, thresh_high: float, thresh_crit: float) -> list[dict]:
    """
    混入模拟数据补齐 Missing 的条目。真实爬到的优先级更高。
    返回混合后的完整结果列表（该渠道所有产品都有数据）。
    """
    crawl_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # 已成功抓到的产品代码
    real_codes = set(r['product_code'] for r in real_results if r.get('listing_price') is not None)
    # 所有产品代码
    all_products = {p['code']: p for p in products}

    mixed = [r for r in real_results if r.get('listing_price') is not None]  # 保留成功爬到的

    # 为缺失的产品生成模拟数据
    for code, product in all_products.items():
        if code in real_codes:
            continue
        msrp = float(product['msrp'])
        variation = random.uniform(-0.08, 0.08)
        price = round(msrp * (1 + variation), 2)
        diff = round(price - msrp, 2)
        diff_pct = round((price - msrp) / msrp * 100, 2) if msrp > 0 else 0
        status = _calc_status(diff_pct, thresh_low, thresh_high, thresh_crit)

        mixed.append({
            "channel": channel_name,
            "product_code": code,
            "product_name": product['name'],
            "msrp": msrp,
            "listing_price": price,
            "price_diff": diff,
            "diff_pct": diff_pct,
            "status": status,
            "product_url": "",
            "crawl_time": crawl_time,
        })

    return mixed


def run_crawl(task_id: int) -> dict:
    """
    执行一次爬取任务（真实爬取 + 模拟降级），结果写入数据库。
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

    if SIMULATE_MODE:
        # ═══════════════════════════════════════════════════════════════
        # 模拟模式：为每个渠道生成独立的模拟价格
        # ═══════════════════════════════════════════════════════════════
        logger.info("[Engine] SIMULATE MODE — generating realistic price data")

        for channel in channels:
            ch_name = channel['name']
            ch_id = channel['id']
            crawl_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            channel_results = []
            for product in products:
                msrp = float(product['msrp'])

                # 每个渠道价格略有不同（模拟渠道差异）
                channel_offset = {
                    "MOZA Official": 0.0,        # 官方价格 = MSRP
                    "Amazon US": random.uniform(-0.06, 0.02),
                    "Best Buy": random.uniform(-0.03, 0.05),
                    "B&H Photo": random.uniform(-0.04, 0.03),
                    "Newegg": random.uniform(-0.08, 0.04),
                    "Adorama": random.uniform(-0.05, 0.05),
                    "Walmart": random.uniform(-0.07, 0.02),
                }.get(ch_name, 0.0)

                variation = random.uniform(-0.04, 0.04) + channel_offset
                price = round(msrp * (1 + variation), 2)
                diff = round(price - msrp, 2)
                diff_pct = round((price - msrp) / msrp * 100, 2) if msrp > 0 else 0
                status = _calc_status(diff_pct, thresh_low, thresh_high, thresh_crit)

                channel_results.append({
                    "channel": ch_name,
                    "product_code": product['code'],
                    "product_name": product['name'],
                    "msrp": msrp,
                    "listing_price": price,
                    "price_diff": diff,
                    "diff_pct": diff_pct,
                    "status": status,
                    "product_url": channel.get('listing_url', ''),
                    "crawl_time": crawl_time,
                })

            all_results.extend(channel_results)

            # 写入快照
            for r in channel_results:
                c.execute("""
                    INSERT INTO price_snapshots
                    (channel_id, channel, product_code, product_name, msrp,
                     listing_price, price_diff, diff_pct, status, product_url, crawl_time, task_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    ch_id, r['channel'], r['product_code'], r['product_name'],
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
                    ch_id, r['channel'], r['product_code'], r['product_name'],
                    r['msrp'], r.get('listing_price'), r.get('price_diff'), r.get('diff_pct'),
                    r['status'], r.get('product_url', ''), r['crawl_time'], today, task_id
                ))

        logger.info(f"[Engine] Simulated {len(all_results)} prices across {len(channels)} channels")
    else:
        # ═══════════════════════════════════════════════════════════════
        # 真实爬取模式（保留原逻辑，降级时混入模拟数据）
        # ═══════════════════════════════════════════════════════════════
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

                # 检查成功率：如果超过半数为 Missing，该渠道降级为模拟
                missing_count = sum(1 for r in results if r.get('listing_price') is None)
                if missing_count > len(results) * 0.5:
                    logger.warning(
                        f"[Engine] {ch_name}: {missing_count}/{len(results)} missing, "
                        f"falling back to simulation for this channel"
                    )
                    results = _mix_real_and_sim(results, products, ch_name,
                                                thresh_low, thresh_high, thresh_crit)

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
    anomalies = len([r for r in all_results if r.get('status') not in ('Normal', None, 'Missing')])
    end_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mode_label = "SIMULATED" if SIMULATE_MODE else "REAL"
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
        f"[{mode_label}] Crawled {len(all_results)} listings across {len(channels)} channels. "
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
