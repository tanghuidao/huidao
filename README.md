# huidao.cc — AI 资讯聚合与监测平台

huidao.cc 是一个自动化的多源资讯聚合、分类、评分与简报系统，内容对公众免费开放（CC BY 4.0）。

## 架构

```
├── frontend/          # 前端（Vue 3 + Chart.js 单页应用，暗/亮双主题）
├── backend/           # FastAPI 后端（采集、分类、评分、简报、调度）
│   └── app/
│       ├── routers/   # API 路由（sources/articles/briefings/...）
│       ├── services/  # 采集器、分类器、摘要器、调度器
│       └── models.py  # SQLAlchemy 数据模型（PostgreSQL）
├── deploy/            # Nginx 配置与部署脚本
├── scripts/           # 运维/数据修复脚本
├── docker-compose.yml # 五容器编排：app / db / redis / nginx / certbot
└── Dockerfile         # 后端+前端打包镜像
```

## 信息源

当前 60 个信息源（RSS 为主），覆盖：
- **加密货币**：CoinDesk、The Block、Decrypt、Cointelegraph、Odaily、PANews、TechFlow、ChainCatcher 等
- **科技媒体**：MIT Technology Review、TechCrunch、The Verge、Wired、Ars Technica 等
- **财经媒体**：Bloomberg、WSJ、FT、Nikkei Asia、SCMP、NYT 等
- **公链生态**：Ethereum、Solana、Arbitrum、Optimism、Polkadot、Chainlink 等
- **监管机构**：美联储、SEC、CFTC、ECB、日银、MAS、香港 SFC、ESMA、BIS 等

> 部分源因官方 RSS 失效，改用 Google News RSS 定向订阅（`site:域名` 或主题关键词）。

## 本地开发

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # 填入配置
python run.py
```

## 生产部署（Docker）

```bash
cp deploy/.env.production .env   # 填入真实配置
docker compose up -d --build
```

前端变更后需重建镜像（代码打包进镜像）：

```bash
docker compose build app && docker compose up -d app
```

## 许可

网站公开内容遵循 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.zh)。
