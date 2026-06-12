"""
app.py — MOZA RACING US Price Monitor 后端服务
Flask + APScheduler + SQLite
"""
import json
import csv
import io
import logging
import os
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_file, Response
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

from database import init_db, seed_defaults, get_conn
from crawl_engine import run_crawl

# ── 日志 ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

# ── Flask ────────────────────────────────────────────────────────────────────
# 用绝对路径定位 webapp 静态文件夹，兼容 gunicorn 从任意工作目录启动
_HERE = os.path.dirname(os.path.abspath(__file__))
_WEBAPP = os.path.join(_HERE, '..', 'webapp')
app = Flask(__name__, static_folder=_WEBAPP, static_url_path='')
CORS(app)  # 允许前端跨域调用

# ── 安全头（覆盖 Render 默认 CSP，允许 Chart.js 正常运行）──────────────────
@app.after_request
def _relax_csp(response):
    """移除 Render 强制的严格 CSP，允许 inline-script / eval（Chart.js 需要）"""
    response.headers['Content-Security-Policy'] = (
        "default-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https:; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https:; "
        "font-src 'self' https://cdn.jsdelivr.net; "
    )
    return response

# ── APScheduler ──────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(daemon=True)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

crawl_lock = threading.Lock()


# ── 首页 ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return app.send_static_file('index.html')


# ═══════════════════════════════════════════════════════════════════════════════
# API: Dashboard
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    conn = get_conn()
    c = conn.cursor()

    total_products = c.execute("SELECT COUNT(*) FROM products WHERE status='Active'").fetchone()[0]
    total_channels = c.execute("SELECT COUNT(*) FROM channels WHERE status='Active'").fetchone()[0]

    anomalies = c.execute(
        "SELECT COUNT(*) FROM price_snapshots WHERE status NOT IN ('Normal', 'Missing')"
    ).fetchone()[0]
    critical = c.execute(
        "SELECT COUNT(*) FROM price_snapshots WHERE status='Critical'"
    ).fetchone()[0]
    missing = c.execute(
        "SELECT COUNT(*) FROM price_snapshots WHERE status='Missing'"
    ).fetchone()[0]
    normal = c.execute(
        "SELECT COUNT(*) FROM price_snapshots WHERE status='Normal'"
    ).fetchone()[0]

    last_log = c.execute(
        "SELECT start_time, end_time FROM task_logs WHERE status!='running' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    # 各渠道异常数统计
    channel_anomalies = c.execute("""
        SELECT channel, COUNT(*) as cnt
        FROM price_snapshots
        WHERE status NOT IN ('Normal', 'Missing')
        GROUP BY channel
        ORDER BY cnt DESC
    """).fetchall()

    # 最近5条异常
    recent_anomalies = c.execute("""
        SELECT channel, product_code, product_name, msrp, listing_price,
               price_diff, diff_pct, status, product_url, crawl_time
        FROM price_snapshots
        WHERE status NOT IN ('Normal', 'Missing')
        ORDER BY ABS(diff_pct) DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    return jsonify({
        "total_products": total_products,
        "total_channels": total_channels,
        "anomalies": anomalies,
        "critical": critical,
        "missing": missing,
        "normal": normal,
        "last_crawl": last_log['end_time'] if last_log else None,
        "channel_anomalies": [dict(r) for r in channel_anomalies],
        "recent_anomalies": [dict(r) for r in recent_anomalies],
    })


# ═══════════════════════════════════════════════════════════════════════════════
# API: Price Monitor (快照)
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/prices', methods=['GET'])
def api_prices():
    q = request.args.get('q', '').strip()
    channel = request.args.get('channel', '')
    status = request.args.get('status', '')
    catalog = request.args.get('catalog', '')
    page = max(1, int(request.args.get('page', 1)))
    page_size = min(200, int(request.args.get('page_size', 50)))

    conn = get_conn()
    c = conn.cursor()

    where = []
    params = []
    if q:
        where.append("(ps.product_code LIKE ? OR ps.product_name LIKE ? OR ps.channel LIKE ?)")
        params += [f'%{q}%', f'%{q}%', f'%{q}%']
    if channel:
        where.append("ps.channel = ?")
        params.append(channel)
    if status:
        where.append("ps.status = ?")
        params.append(status)
    if catalog:
        where.append("p.catalog = ?")
        params.append(catalog)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = c.execute(
        f"SELECT COUNT(*) FROM price_snapshots ps LEFT JOIN products p ON ps.product_code=p.code {where_clause}",
        params
    ).fetchone()[0]

    offset = (page - 1) * page_size
    rows = c.execute(
        f"""SELECT ps.*, p.catalog
            FROM price_snapshots ps
            LEFT JOIN products p ON ps.product_code=p.code
            {where_clause}
            ORDER BY ABS(COALESCE(ps.diff_pct,0)) DESC, ps.crawl_time DESC
            LIMIT ? OFFSET ?""",
        params + [page_size, offset]
    ).fetchall()

    conn.close()
    return jsonify({
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "data": [dict(r) for r in rows]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# API: Price History (历史趋势)
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/history', methods=['GET'])
def api_history():
    product_code = request.args.get('product_code', '')
    channel = request.args.get('channel', '')
    days = min(365, int(request.args.get('days', 30)))

    if not product_code:
        return jsonify({"error": "product_code required"}), 400

    conn = get_conn()
    c = conn.cursor()

    where = ["product_code = ?"]
    params = [product_code]
    if channel:
        where.append("channel = ?")
        params.append(channel)

    rows = c.execute(
        f"""SELECT date, channel, listing_price, msrp, diff_pct, status
            FROM price_history
            WHERE {' AND '.join(where)}
            ORDER BY date ASC, channel ASC
            LIMIT ?""",
        params + [days * 10]
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ═══════════════════════════════════════════════════════════════════════════════
# API: Products
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/products', methods=['GET'])
def api_products():
    q = request.args.get('q', '')
    catalog = request.args.get('catalog', '')
    status = request.args.get('status', '')

    where, params = [], []
    if q:
        where.append("(code LIKE ? OR name LIKE ?)")
        params += [f'%{q}%', f'%{q}%']
    if catalog:
        where.append("catalog = ?")
        params.append(catalog)
    if status:
        where.append("status = ?")
        params.append(status)

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    rows = conn.execute(f"SELECT * FROM products {clause} ORDER BY catalog, code", params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/products', methods=['POST'])
def api_product_create():
    d = request.get_json()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO products(code,name,catalog,msrp,status) VALUES(?,?,?,?,?)",
            (d['code'], d['name'], d.get('catalog', ''), float(d['msrp']), d.get('status', 'Active'))
        )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE code=?", (d['code'],)).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route('/api/products/<int:pid>', methods=['PUT'])
def api_product_update(pid):
    d = request.get_json()
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE products SET code=?,name=?,catalog=?,msrp=?,status=?,updated_at=datetime('now') WHERE id=?",
            (d['code'], d['name'], d.get('catalog', ''), float(d['msrp']), d.get('status', 'Active'), pid)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route('/api/products/<int:pid>', methods=['DELETE'])
def api_product_delete(pid):
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# API: Channels
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/channels', methods=['GET'])
def api_channels():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM channels ORDER BY id").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/channels', methods=['POST'])
def api_channel_create():
    d = request.get_json()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO channels(name,url,listing_url,type,freq,status,note) VALUES(?,?,?,?,?,?,?)",
            (d['name'], d['url'], d.get('listing_url', ''), d.get('type', 'Authorized'),
             d.get('freq', 'daily'), d.get('status', 'Active'), d.get('note', ''))
        )
        conn.commit()
        row = conn.execute("SELECT * FROM channels WHERE name=?", (d['name'],)).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route('/api/channels/<int:cid>', methods=['PUT'])
def api_channel_update(cid):
    d = request.get_json()
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE channels SET name=?,url=?,listing_url=?,type=?,freq=?,status=?,note=? WHERE id=?",
            (d['name'], d['url'], d.get('listing_url', ''), d.get('type', 'Authorized'),
             d.get('freq', 'daily'), d.get('status', 'Active'), d.get('note', ''), cid)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM channels WHERE id=?", (cid,)).fetchone()
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route('/api/channels/<int:cid>', methods=['DELETE'])
def api_channel_delete(cid):
    conn = get_conn()
    conn.execute("DELETE FROM channels WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# API: Task Logs
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/tasks', methods=['GET'])
def api_tasks():
    limit = min(100, int(request.args.get('limit', 20)))
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM task_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['errors'] = json.loads(d['errors'] or '[]')
        except Exception:
            d['errors'] = []
        result.append(d)
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════════
# API: Trigger Crawl
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/crawl', methods=['POST'])
def api_crawl():
    if not crawl_lock.acquire(blocking=False):
        return jsonify({"error": "Crawl already in progress"}), 409

    conn = get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    today_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    c = conn.cursor()
    c.execute(
        "INSERT INTO task_logs(title, status, start_time, details) VALUES(?,?,?,?)",
        (f"Manual Crawl — {today_label}", "running", now, "Crawl triggered manually via API.")
    )
    task_id = c.lastrowid
    conn.commit()
    conn.close()

    def _do_crawl():
        try:
            run_crawl(task_id)
        finally:
            crawl_lock.release()

    t = threading.Thread(target=_do_crawl, daemon=True)
    t.start()

    return jsonify({"ok": True, "task_id": task_id, "message": "Crawl started"})


@app.route('/api/crawl/status', methods=['GET'])
def api_crawl_status():
    running = not crawl_lock.acquire(blocking=False)
    if not running:
        crawl_lock.release()
    conn = get_conn()
    last = conn.execute(
        "SELECT * FROM task_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return jsonify({
        "running": running,
        "last_task": dict(last) if last else None,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# API: Settings
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/settings', methods=['GET'])
def api_settings_get():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})


@app.route('/api/settings', methods=['POST'])
def api_settings_set():
    d = request.get_json()
    conn = get_conn()
    for k, v in d.items():
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
    conn.commit()
    conn.close()
    _reschedule_cron()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# API: Export
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/api/export', methods=['GET'])
def api_export():
    fmt = request.args.get('format', 'csv').lower()
    channel = request.args.get('channel', '')
    status = request.args.get('status', '')

    where, params = [], []
    if channel:
        where.append("channel = ?")
        params.append(channel)
    if status:
        where.append("status = ?")
        params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    rows = conn.execute(
        f"""SELECT channel, product_code, product_name, msrp, listing_price,
                   price_diff, diff_pct, status, product_url, crawl_time
            FROM price_snapshots {clause}
            ORDER BY channel, product_code""",
        params
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Channel", "Product Code", "Product Name", "MSRP",
                     "Listing Price", "Price Diff", "Diff %", "Status", "URL", "Crawl Time"])
    for r in rows:
        writer.writerow([
            r['channel'], r['product_code'], r['product_name'],
            f"${r['msrp']:.2f}" if r['msrp'] else '',
            f"${r['listing_price']:.2f}" if r['listing_price'] else 'N/A',
            f"${r['price_diff']:.2f}" if r['price_diff'] is not None else 'N/A',
            f"{r['diff_pct']:.1f}%" if r['diff_pct'] is not None else 'N/A',
            r['status'], r['product_url'] or '', r['crawl_time']
        ])

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"moza_price_monitor_{date_str}.csv"

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ═══════════════════════════════════════════════════════════════════════════════
# APScheduler: 定时爬取
# ═══════════════════════════════════════════════════════════════════════════════
def _scheduled_crawl():
    """定时任务：自动爬取"""
    if not crawl_lock.acquire(blocking=False):
        logger.warning("[Scheduler] Crawl already running, skipping scheduled run")
        return
    conn = get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    today_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    c = conn.cursor()
    c.execute(
        "INSERT INTO task_logs(title, status, start_time, details) VALUES(?,?,?,?)",
        (f"Scheduled Crawl — {today_label}", "running", now, "Automatic daily crawl.")
    )
    task_id = c.lastrowid
    conn.commit()
    conn.close()
    try:
        run_crawl(task_id)
        logger.info(f"[Scheduler] Crawl task {task_id} completed")
    finally:
        crawl_lock.release()


def _reschedule_cron():
    """根据 settings 中 crawl_time 和 tz 更新定时任务"""
    conn = get_conn()
    rows = {r['key']: r['value'] for r in conn.execute("SELECT key,value FROM settings").fetchall()}
    conn.close()

    crawl_time = rows.get('crawl_time', '08:00')
    tz_setting = rows.get('tz', 'ET')

    tz_map = {
        'ET': 'America/New_York',
        'CT': 'America/Chicago',
        'MT': 'America/Denver',
        'PT': 'America/Los_Angeles',
        'UTC': 'UTC',
    }
    tz_name = tz_map.get(tz_setting, 'America/New_York')

    try:
        hour, minute = crawl_time.split(':')
    except ValueError:
        hour, minute = '8', '0'

    scheduler.remove_all_jobs()
    scheduler.add_job(
        _scheduled_crawl,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=tz_name),
        id='daily_crawl',
        replace_existing=True,
    )
    logger.info(f"[Scheduler] Next crawl scheduled at {crawl_time} {tz_setting} ({tz_name})")


# ── 启动 ─────────────────────────────────────────────────────────────────────
# 初始化数据库（gunicorn 启动时也会执行，用 try/except 防止启动崩溃）
try:
    init_db()
    seed_defaults()
    _reschedule_cron()
    logger.info("Database and scheduler initialized successfully")
except Exception as e:
    logger.error(f"Startup error: {e}", exc_info=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info("=" * 60)
    logger.info("  MOZA RACING US Price Monitor — Backend Server")
    logger.info(f"  http://0.0.0.0:{port}")
    logger.info("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
