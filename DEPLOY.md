# MOZA RACING US Price Monitor — 部署指南

## 部署架构

- **代码托管**：GitHub（diorleo/price-monitor）
- **后端托管**：Render（免费 Web Service）
- **数据库**：SQLite + Render Disk（持久化存储）
- **前端**：由 Flask 静态文件服务提供

---

## 第一步：创建 GitHub 仓库

1. 打开 https://github.com/new
2. 填写：
   - Repository name: `price-monitor`
   - 选择 **Private**（推荐，不公开产品价格数据）
   - 不要勾选 Initialize README
3. 点击 **Create repository**

---

## 第二步：推送代码到 GitHub

在你的电脑上打开终端（CMD 或 PowerShell），进入项目目录：

```bash
cd C:\Users\leo\WorkBuddy\PriceMonitor

# 初始化 git
git init

# 添加所有文件
git add .

# 首次提交
git commit -m "Initial commit: MOZA Price Monitor"

# 关联远程仓库（替换为你的实际地址）
git remote add origin https://github.com/diorleo/price-monitor.git

# 推送
git branch -M main
git push -u origin main
```

---

## 第三步：在 Render 部署

### 3.1 注册/登录 Render

访问 https://render.com，用 GitHub 账号（diorleo）登录，这样可以直接授权访问你的仓库。

### 3.2 创建 Web Service

1. 点击右上角 **New +** → **Web Service**
2. 选择 **Connect a repository** → 找到 `diorleo/price-monitor`
3. 填写配置：

| 字段 | 值 |
|------|-----|
| Name | `moza-price-monitor` |
| Runtime | `Python 3` |
| Build Command | `pip install -r backend/requirements.txt` |
| Start Command | `gunicorn --chdir backend app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120` |
| Instance Type | `Free` |

4. 点击 **Advanced** → **Add Disk**：
   - Name: `data`
   - Mount Path: `/opt/render/project/src/backend/data`
   - Size: `1 GB`

5. 点击 **Create Web Service**

### 3.3 等待部署完成

Render 会自动：
- 拉取你的 GitHub 代码
- 安装依赖
- 启动服务

部署完成后会给你一个访问地址，格式为：
```
https://moza-price-monitor.onrender.com
```

---

## 第四步：访问应用

打开 Render 给的地址即可，功能与本地完全一致。

**注意（免费版限制）**：
- 免费版在 15 分钟无请求后会自动休眠，下次访问需等待约 30 秒冷启动
- 如需保持常驻，可升级到 Starter 计划（$7/月）

---

## 后续更新代码

每次修改代码后，只需：

```bash
git add .
git commit -m "描述你的改动"
git push
```

Render 会自动检测 GitHub 变更并重新部署。

---

## 常见问题

**Q: 数据库数据会丢失吗？**
A: 不会，配置了 Render Disk 持久化存储。

**Q: 如何查看日志？**
A: Render 控制台 → 你的服务 → Logs 标签。

**Q: 爬虫能正常运行吗？**
A: 可以，但各电商平台可能封锁云服务器 IP，建议用代理或手动触发并验证结果。
