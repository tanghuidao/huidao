# huidao.cc 上线部署指南

## 总览

将 AI + Crypto / Web3 全球动态监测系统部署到 huidao.cc，使用 Docker 容器化，PostgreSQL 数据库，Nginx 反代 + Let's Encrypt SSL。

## 第一步：购买云服务器

**推荐配置：**
- CPU: 2核
- 内存: 4GB（最低2GB可跑，4GB更稳）
- 硬盘: 40GB SSD
- 系统: Ubuntu 22.04 / 24.04 LTS
- 带宽: 3-5Mbps

**推荐平台（按场景）：**

| 平台 | 优势 | 月费参考 | 是否需要备案 |
|------|------|----------|-------------|
| 阿里云轻量应用服务器 | 国内访问快 | ¥50-100/月 | 需要 |
| 腾讯云轻量云 | 国内访问快 | ¥45-95/月 | 需要 |
| DigitalOcean | 免备案，速度不错 | $12-24/月 | 不需要 |
| Vultr | 免备案，东京/新加坡节点 | $12-24/月 | 不需要 |
| Bandwagon (搬瓦工) | 便宜，CN2线路 | $50/年 | 不需要 |

> **如果选阿里云（你已有阿里云账号）**：推荐「轻量应用服务器」2核2G ¥54/月 或 2核4G ¥100/月。但需要做 ICP 备案（约5-15工作日）。
>
> **如果想快速上线不备案**：选海外服务器（推荐新加坡或日本节点），国内访问延迟会高一些但可接受。

## 第二步：DNS 配置

在阿里云域名管理控制台：https://dc.console.aliyun.com/next/index#/domain-list/all

1. 找到 `huidao.cc`，点击「解析」
2. 添加两条记录：

| 记录类型 | 主机记录 | 记录值 | TTL |
|----------|----------|--------|-----|
| A | @ | 你的服务器IP | 10分钟 |
| A | www | 你的服务器IP | 10分钟 |

配置后等待 5-10 分钟 DNS 生效。验证：`ping huidao.cc` 看是否解析到你的服务器 IP。

## 第三步：服务器初始化

SSH 登录到服务器后执行：

```bash
# 1. 更新系统
sudo apt update && sudo apt upgrade -y

# 2. 安装 Docker (一键脚本)
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable docker

# 3. 安装 Docker Compose 插件
sudo apt install -y docker-compose-plugin

# 4. 验证安装
docker --version
docker compose version
```

## 第四步：上传项目

从本地上传项目到服务器：

```bash
# 方法1: scp 上传（在本地执行）
scp -r ./ai-crypto-monitor root@你的服务器IP:/opt/huidao

# 方法2: 如果项目在 Git 仓库
ssh root@你的服务器IP
cd /opt && git clone 你的仓库地址 huidao
```

## 第五步：配置环境变量

```bash
cd /opt/huidao
cp deploy/.env.production .env
nano .env
```

**必须修改的配置项：**

```env
# 数据库密码（改为强密码）
POSTGRES_PASSWORD=你的强密码_建议16位以上随机字符串
DATABASE_URL=postgresql://huidao:你的强密码@db:5432/monitor

# OpenAI API Key
OPENAI_API_KEY=sk-你的密钥

# 你的邮箱（SSL证书用）
EMAIL=你的真实邮箱
```

> **关于 OpenAI API Key：** 
> - 访问 https://platform.openai.com/api-keys 创建
> - 如果无法访问 OpenAI，可以使用兼容 API（如 DeepSeek、通义千问）
> - 修改 OPENAI_BASE_URL 为对应的 API 地址即可
> - 系统在没有 API Key 时会自动使用规则引擎 fallback，基础功能不受影响

## 第六步：启动服务

```bash
cd /opt/huidao

# 首次启动（使用 HTTP 模式）
cp deploy/nginx/conf.d/huidao-init.conf deploy/nginx/conf.d/default.conf

# 构建并启动
docker compose up -d --build

# 查看启动日志
docker compose logs -f

# 检查状态（所有容器都应该是 healthy）
docker compose ps
```

等待 30 秒后，访问 `http://huidao.cc` 应该能看到系统界面。

## 第七步：配置 SSL (HTTPS)

确保 DNS 已生效后：

```bash
cd /opt/huidao

# 获取 SSL 证书
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email 你的邮箱 \
    --agree-tos \
    --no-eff-email \
    -d huidao.cc \
    -d www.huidao.cc

# 切换到 HTTPS 配置
rm deploy/nginx/conf.d/default.conf
rm deploy/nginx/conf.d/huidao-init.conf
cp deploy/nginx/conf.d/huidao.conf.bak deploy/nginx/conf.d/huidao.conf 2>/dev/null || true

# 重启 nginx
docker compose restart nginx
```

现在访问 `https://huidao.cc` 应该可以正常打开了。

## 第八步：配置自动续期

```bash
# 添加 cron 任务，每天凌晨3点检查续期
echo "0 3 * * * root cd /opt/huidao && docker compose run --rm certbot renew --quiet && docker compose restart nginx" | sudo tee /etc/cron.d/certbot-renew
```

## 日常运维命令

```bash
cd /opt/huidao

# 查看所有服务状态
docker compose ps

# 查看应用日志
docker compose logs -f app

# 重启全部服务
docker compose restart

# 仅重启应用（代码更新后）
docker compose build app && docker compose up -d app

# 进入数据库
docker compose exec db psql -U huidao -d monitor

# 备份数据库
docker compose exec db pg_dump -U huidao monitor > backup_$(date +%Y%m%d).sql

# 恢复数据库
docker compose exec -T db psql -U huidao monitor < backup_20260605.sql

# 查看磁盘使用
docker system df

# 清理无用镜像
docker system prune -f
```

## 备案说明（如使用国内服务器）

如果服务器在中国大陆，需要做 ICP 备案：

1. 登录阿里云备案系统：https://beian.aliyun.com
2. 按提示填写主体信息（个人/企业）
3. 上传证件照片
4. 提交管局审核（通常 5-15 个工作日）
5. 备案通过后，在网站底部放置备案号

> 在备案期间，可以先用服务器 IP 直接访问，或使用海外服务器临时上线。

## 架构图

```
用户浏览器
    │
    ▼ HTTPS (443)
┌─────────┐
│  Nginx  │  ← Let's Encrypt SSL
│ (反代)   │
└────┬────┘
     │ HTTP (8000)
┌────▼─────┐
│  FastAPI  │  ← Python 应用
│  (App)    │
└────┬─────┘
     │ TCP (5432)
┌────▼──────┐
│ PostgreSQL │  ← 持久化存储
│   (DB)     │
└───────────┘
```

## 后续可选优化

- [ ] 添加 Redis 缓存（提高频繁查询性能）
- [ ] 配置 CloudFlare CDN（加速全球访问）
- [ ] 添加系统监控（Prometheus + Grafana）
- [ ] 设置服务器防火墙（只开放 80/443）
- [ ] 配置日志轮转（防止磁盘占满）
- [ ] 开发 Android APP
