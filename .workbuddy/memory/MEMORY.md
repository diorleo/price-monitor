# MOZA RACING US Price Monitor — 项目记忆

## 项目定位
美国渠道价格自动监控系统，监控 MOZA RACING 产品在 Amazon/BestBuy/B&H/Newegg/Adorama/官方站/Walmart 的售价，对比 MSRP，检测异常。

## 交付物
- `webapp/index.html` — 完整双模式 WebApp（后端在线用 API；file:// 打开降级模拟模式）
- `backend/app.py` — Flask 后端主程序（已实现）
- `backend/database.py` — SQLite 数据库初始化
- `backend/crawl_engine.py` — 爬取引擎
- `backend/scrapers/` — 7 个渠道爬虫（Amazon/BestBuy/B&H/Newegg/Adorama/Walmart/MOZA Official）
- `start.bat` / `start.sh` — 一键启动脚本
- `AS23海外产品MSRP-20260101.xlsx` / `RS21海外产品MSRP-20260106.xlsx` — 原始 MSRP 数据源（72 个 SKU）

## 产品体系
- AS 系列：飞行模拟器（18 个 SKU），产品代码 AS001-AS020
- RS 系列：赛车模拟器（54 个 SKU），产品代码 RS11-RS111
- 两个系列共 72 个 SKU，均内置于 WebApp 和 SQLite

## 技术架构（完整后端实现）
- 前端：纯 HTML + CSS + JavaScript，Chart.js 4.4（CDN），双模式（在线/离线）
- 后端：Python Flask 3.0 + APScheduler + SQLite
- 爬虫：requests + BeautifulSoup4，各渠道独立 scraper
- 数据库：`backend/data/price_monitor.db`（6 张表）
- 启动：双击 `start.bat`（Windows），访问 http://127.0.0.1:5000

## API 接口清单
- GET /api/dashboard — 仪表盘统计
- GET/POST/PUT/DELETE /api/products — 产品 CRUD
- GET/POST/PUT/DELETE /api/channels — 渠道 CRUD
- GET /api/prices — 价格快照（支持 q/channel/status/catalog/page/page_size 筛选）
- GET /api/history — 历史价格趋势（product_code/channel/days）
- GET /api/tasks — 任务日志
- POST /api/crawl — 手动触发爬取
- GET /api/crawl/status — 爬取状态轮询
- GET/POST /api/settings — 设置读写
- GET /api/export — 导出 CSV

## 用户
销售部门 / 渠道管理 / 市场团队，需要简单易用界面
