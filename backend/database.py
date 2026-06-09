"""
database.py — SQLite 数据库初始化与 ORM 工具函数
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'price_monitor.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()

    # 产品表
    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        code     TEXT UNIQUE NOT NULL,
        name     TEXT NOT NULL,
        catalog  TEXT NOT NULL DEFAULT '',
        msrp     REAL NOT NULL,
        status   TEXT NOT NULL DEFAULT 'Active',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )
    """)

    # 渠道表
    c.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT UNIQUE NOT NULL,
        url         TEXT NOT NULL,
        listing_url TEXT NOT NULL DEFAULT '',
        type        TEXT NOT NULL DEFAULT 'Authorized',
        freq        TEXT NOT NULL DEFAULT 'daily',
        status      TEXT NOT NULL DEFAULT 'Active',
        note        TEXT DEFAULT '',
        created_at  TEXT DEFAULT (datetime('now'))
    )
    """)

    # 价格监控结果表（最新快照）
    c.execute("""
    CREATE TABLE IF NOT EXISTS price_snapshots (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id    INTEGER NOT NULL,
        channel       TEXT NOT NULL,
        product_code  TEXT NOT NULL,
        product_name  TEXT NOT NULL,
        msrp          REAL NOT NULL,
        listing_price REAL,
        price_diff    REAL,
        diff_pct      REAL,
        status        TEXT NOT NULL DEFAULT 'Normal',
        product_url   TEXT DEFAULT '',
        crawl_time    TEXT NOT NULL,
        task_id       INTEGER,
        FOREIGN KEY(channel_id) REFERENCES channels(id),
        FOREIGN KEY(product_code) REFERENCES products(code)
    )
    """)

    # 价格历史表（追加，不删除）
    c.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id    INTEGER NOT NULL,
        channel       TEXT NOT NULL,
        product_code  TEXT NOT NULL,
        product_name  TEXT NOT NULL,
        msrp          REAL NOT NULL,
        listing_price REAL,
        price_diff    REAL,
        diff_pct      REAL,
        status        TEXT NOT NULL DEFAULT 'Normal',
        product_url   TEXT DEFAULT '',
        crawl_time    TEXT NOT NULL,
        date          TEXT NOT NULL,
        task_id       INTEGER
    )
    """)

    # 任务日志表
    c.execute("""
    CREATE TABLE IF NOT EXISTS task_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'running',
        start_time  TEXT NOT NULL,
        end_time    TEXT,
        products    INTEGER DEFAULT 0,
        channels    INTEGER DEFAULT 0,
        anomalies   INTEGER DEFAULT 0,
        errors      TEXT DEFAULT '[]',
        details     TEXT DEFAULT ''
    )
    """)

    # 设置表（单行 KV）
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")


def seed_defaults():
    """写入默认产品和渠道数据（如果表为空）"""
    conn = get_conn()
    c = conn.cursor()

    # 检查产品表是否已有数据
    if c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        products = [
            # AS 系列 — 飞行模拟
            ('AS017','MOZA AB6 Flight Simulator','Bundle',399,'Active'),
            ('AS001','MOZA AB9 Force Feedback base','Base',499,'Active'),
            ('AS011','MOZA AY210 Force Feedback YOKE','Base',699,'Active'),
            ('AS018','MOZA MHG Flight Stick','Grip',99,'Active'),
            ('AS002','MOZA MH16 Flightstick','Grip',149,'Active'),
            ('AS005','MOZA MA3X Sidestick','Grip',79,'Active'),
            ('AS012','MOZA MFY YOKE','Grip',149,'Active'),
            ('AS008','MOZA MTP Throttle Panel','Throttle',329,'Active'),
            ('AS014','MOZA MTQ Throttle Panel','Throttle',199,'Active'),
            ('AS009','MOZA MTLP Take-off Landing Panel','Throttle',149,'Active'),
            ('AS019','MOZA MRP Rudder Pedals','Rudder',349,'Active'),
            ('AS003','MOZA Z-Axis Module','Accessory',89,'Active'),
            ('AS004','MOZA Flight Base Table Clamp','Accessory',59,'Active'),
            ('AS013','MOZA Table Clamp For Yoke','Accessory',25,'Active'),
            ('AS006','MOZA Flight Support Plate','Accessory',25,'Active'),
            ('AS015','MOZA TQB Throttle Module','Accessory',39,'Active'),
            ('AS016','MOZA TQA Throttle Module','Accessory',39,'Active'),
            ('AS020','MOZA MRP Adjustable Damper','Accessory',65,'Active'),
            # RS 系列 — 赛车模拟
            ('RS053','MOZA R3 Racing Wheel and Pedals','Bundle',339,'Active'),
            ('RS074','MOZA R3 Racing Wheel and Pedals for PC','Bundle',279,'Active'),
            ('RS20','MOZA R5 Racing Simulator','Bundle',399,'Active'),
            ('RS071','MOZA Truck Driving Simulator','Bundle',499,'Active'),
            ('RS080','MOZA R9 V3 Direct Drive Wheel Base','Wheel Base',329,'Active'),
            ('RS081','MOZA R12 V2 Direct Drive Wheel Base','Wheel Base',429,'Active'),
            ('RS090','MOZA R21 Ultra Direct Drive Wheel Base','Wheel Base',699,'Active'),
            ('RS091','MOZA R25 Ultra True Torque DD Wheel Base','Wheel Base',899,'Active'),
            ('RS052','MOZA ESX Steering Wheel For XBOX','Steering Wheel',129,'Active'),
            ('RS057','MOZA CS V2P Steering Wheel','Steering Wheel',229,'Active'),
            ('RS093','MOZA CS Pro Steering Wheel','Steering Wheel',329,'Active'),
            ('RS25','MOZA RS V2 Steering Wheel','Steering Wheel',369,'Active'),
            ('RS047','MOZA KS Steering Wheel','Steering Wheel',229,'Active'),
            ('RS095','MOZA KS Pro Steering Wheel','Steering Wheel',329,'Active'),
            ('RS056','MOZA GS V2P Formula Wheel','Steering Wheel',369,'Active'),
            ('RS068','MOZA FSR V2 Formula Wheel','Steering Wheel',649,'Active'),
            ('RS064','MOZA Vision GS Steering Wheel','Steering Wheel',699,'Active'),
            ('RS060','MOZA TSW Steering Wheel','Steering Wheel',229,'Active'),
            ('RS096','MOZA Lamborghini REVUELTO Simracing Steering Wheel','Steering Wheel',399,'Active'),
            ('RS070','MOZA Lamborghini Essenza SCV12 Sim-Racing Steering Wheel','Steering Wheel',1299,'Active'),
            ('RS097','MOZA Porsche MISSION R Simracing Steering Wheel','Steering Wheel',1299,'Active'),
            ('RS11','MOZA SR-P Pedals','Pedal',129,'Active'),
            ('RS098','MOZA SR-P 2 Pedals','Pedal',149,'Active'),
            ('RS066','MOZA CRP2 Pedals','Pedal',369,'Active'),
            ('RS076','MOZA mBooster Active Pedal','Pedal',799,'Active'),
            ('RS082','MOZA mBooster Pedal Set','Pedal',999,'Active'),
            ('RS19','MOZA SR-P Lite Clutch Pedal','Pedal',39.9,'Active'),
            ('RS111','MOZA SR-P Clutch Pedal','Pedal',45.9,'Active'),
            ('RS099','MOZA SR-P 2 Clutch Pedal','Pedal',45.9,'Active'),
            ('RS067','MOZA CRP2 Clutch Pedal','Pedal',99,'Active'),
            ('RS072','MOZA CM2 Racing Dash','Accessory',199,'Active'),
            ('RS063','MOZA E-Stop Switch','Accessory',35,'Active'),
            ('RS31','MOZA HBP Handbrake','Accessory',99,'Active'),
            ('RS039','MOZA HGP Shifter','Accessory',149,'Active'),
            ('RS059','MOZA SGP Sequential Shifter','Accessory',129,'Active'),
            ('RS089','MOZA Universal Mounting Plate','Accessory',29,'Active'),
            ('RS079','MOZA Active Shifter Knobs','Accessory',39,'Active'),
            ('RS12','MOZA Table Clamp','Accessory',39,'Active'),
            ('RS062','MOZA Clamp For Truck Wheel','Accessory',49,'Active'),
            ('RS061','MOZA Extension Rod','Accessory',99,'Active'),
            ('RS07','MOZA Quick Release Adapter','Accessory',49,'Active'),
            ('RS032','MOZA ES Formula Wheel Mod','Accessory',39,'Active'),
            ('RS046','MOZA 12-inch Wheel Mod for ES','Accessory',69,'Active'),
            ('RS094','MOZA Paddles Add-on Kit','Accessory',45,'Active'),
            ('RS050','MOZA Universal Hub Kit','Accessory',39,'Active'),
            ('RS065','MOZA Multi-function Stalks','Accessory',199,'Active'),
            ('RS077','MOZA Multi-function Stalks Mount Adapter','Accessory',19,'Active'),
            ('RS22','MOZA SR-P Lite Performance Kit','Accessory',29,'Active'),
            ('RS17','MOZA SR-P Accessory Kit','Accessory',15,'Active'),
            ('RS069','MOZA CRP2 Performance Kit','Accessory',19.9,'Active'),
            ('RS075','MOZA Pedals Inversion Kit','Accessory',179,'Active'),
            ('RS073','MOZA Long Throttle Plate','Accessory',29,'Active'),
            ('RS083','MOZA mBooster Base Plate','Accessory',129,'Active'),
            ('RS078','MOZA mBooster Base Extension Plate','Accessory',39,'Active'),
        ]
        c.executemany(
            "INSERT OR IGNORE INTO products(code,name,catalog,msrp,status) VALUES(?,?,?,?,?)",
            products
        )
        print(f"[DB] Seeded {len(products)} products")

    # 检查渠道表是否已有数据
    if c.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 0:
        channels = [
            ('Amazon US','https://www.amazon.com','https://www.amazon.com/s?k=moza+racing','Third-party','daily','Active','Primary market'),
            ('Best Buy','https://www.bestbuy.com','https://www.bestbuy.com/site/searchpage.jsp?st=moza+racing','Authorized','daily','Active',''),
            ('B&H Photo','https://www.bhphotovideo.com','https://www.bhphotovideo.com/c/search?q=moza+racing','Authorized','daily','Active',''),
            ('Newegg','https://www.newegg.com','https://www.newegg.com/p/pl?d=moza+racing','Third-party','daily','Active',''),
            ('Adorama','https://www.adorama.com','https://www.adorama.com/l/?searchinfo=moza+racing','Authorized','daily','Active',''),
            ('MOZA Official','https://mozaracing.com','https://mozaracing.com/collections/all','Official','daily','Active',''),
            ('Walmart','https://www.walmart.com','https://www.walmart.com/search?q=moza+racing','Third-party','daily','Active',''),
        ]
        c.executemany(
            "INSERT OR IGNORE INTO channels(name,url,listing_url,type,freq,status,note) VALUES(?,?,?,?,?,?,?)",
            channels
        )
        print(f"[DB] Seeded {len(channels)} channels")

    # 默认设置
    defaults = {
        'crawl_time': '08:00',
        'tz': 'ET',
        'retry': '3',
        'delay': '2',
        'thresh_low': '5',
        'thresh_high': '10',
        'thresh_critical': '20',
        'auto_export': 'yes',
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

    conn.commit()
    conn.close()
