# MOZA RACING US Price Monitor

美国渠道价格自动监控系统，每日自动抓取 Amazon/BestBuy/B&H/Newegg/Adorama/Walmart/官方站 的 MOZA RACING 产品价格，对比 MSRP，检测异常，可视化展示。

---

## 快速启动

### Windows
双击运行：
```
start.bat
```

### macOS / Linux
```bash
chmod +x start.sh
./start.sh
```

启动后自动打开浏览器访问：**http://127.0.0.1:5000**

---

## 目录结构

```
PriceMonitor/
├── start.bat              # Windows 一键启动
├── start.sh               # macOS/Linux 一键启动
├── webapp/
│   └── index.html         # 前端 WebApp（双模式：在线/离线）
└── backend/
    ├── app.py             # Flask 主程序 + 所有 API 接口
    ├── database.py        # SQLite 初始化 + 种子数据
    ├── crawl_engine.py    # 爬取引擎（调度各渠道爬虫）
    ├── requirements.txt   # Python 依赖
    ├── data/
    │   └── price_monitor.db    # SQLite 数据库（自动生成）
    └── scrapers/
        ├── __init__.py    # 爬虫注册表
        ├── base.py        # 基类（重试/延时/请求头轮换）
        ├── amazon.py      # Amazon US
        ├── bestbuy.py     # Best Buy
        ├── bhphoto.py     # B&H Photo
        ├── newegg.py      # Newegg
        ├── adorama.py     # Adorama
        ├── walmart.py     # Walmart
        └── mozaofficial.py  # MOZA 官方站
```

---

## API 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dashboard` | 仪表盘统计数据 |
| GET | `/api/prices` | 价格快照列表（支持搜索/筛选/分页） |
| GET | `/api/history?product_code=X&channel=Y&days=30` | 历史价格趋势 |
| GET | `/api/products` | 产品列表 |
| POST | `/api/products` | 新增产品 |
| PUT | `/api/products/:id` | 更新产品 |
| DELETE | `/api/products/:id` | 删除产品 |
| GET | `/api/channels` | 渠道列表 |
| POST | `/api/channels` | 新增渠道 |
| PUT | `/api/channels/:id` | 更新渠道 |
| DELETE | `/api/channels/:id` | 删除渠道 |
| GET | `/api/tasks` | 任务日志 |
| POST | `/api/crawl` | 手动触发爬取 |
| GET | `/api/crawl/status` | 爬取任务状态 |
| GET | `/api/settings` | 获取设置 |
| POST | `/api/settings` | 保存设置 |
| GET | `/api/export?format=csv` | 导出 CSV |

---

## 离线模式

如果后端未启动，直接双击 `webapp/index.html` 打开，WebApp 会自动切换到**离线模拟模式**：
- 所有数据保存在浏览器 localStorage
- "Run Crawl" 按钮生成模拟随机价格数据
- 功能完整，但不连接真实电商网站

---

## 技术栈

- **前端**：纯 HTML + CSS + JavaScript（Chart.js 4.4）
- **后端**：Python 3.10+ / Flask 3.0 / APScheduler
- **数据库**：SQLite（本地文件，无需安装）
- **爬虫**：requests + BeautifulSoup4

---

## 定时爬取

系统默认每天 **08:00 美东时间（ET）** 自动执行爬取。可在 WebApp 的 **Settings** 页面修改时间和时区。

---

## 注意事项

1. **反爬**：Amazon 等平台有较强的反爬机制，首次可能返回空数据，属正常现象
2. **频率**：建议保持每天一次，避免过于频繁触发封禁
3. **代理**：如遇持续被封，可在 `scrapers/base.py` 中添加代理支持
4. **数据库**：位于 `backend/data/price_monitor.db`，可用 DB Browser for SQLite 直接查看
