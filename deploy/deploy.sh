#!/bin/bash
# ===== huidao.cc 一键部署脚本 =====
# 在全新的 Ubuntu 22.04/24.04 服务器上运行此脚本
# 使用方法: chmod +x deploy.sh && sudo ./deploy.sh

set -e

DOMAIN="huidao.cc"
PROJECT_DIR="/opt/huidao"
REPO_ARCHIVE_URL=""  # 留空则使用本地文件

echo "=========================================="
echo "  huidao.cc 部署脚本"
echo "=========================================="

# 1. 系统更新和基础包
echo "[1/7] 安装系统依赖..."
apt-get update && apt-get upgrade -y
apt-get install -y \
    curl wget git unzip \
    apt-transport-https ca-certificates \
    gnupg lsb-release software-properties-common

# 2. 安装 Docker
echo "[2/7] 安装 Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl enable docker
    systemctl start docker
fi

# 安装 Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    apt-get install -y docker-compose-plugin
fi
echo "Docker version: $(docker --version)"

# 3. 创建项目目录
echo "[3/7] 创建项目目录..."
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR

# 如果文件不在当前目录，提示用户上传
if [ ! -f "docker-compose.yml" ]; then
    echo ""
    echo "⚠️  请将项目文件上传到 $PROJECT_DIR/"
    echo "   可以用 scp 或 rsync 上传整个项目目录"
    echo "   例如: scp -r ./ai-crypto-monitor/* user@server:$PROJECT_DIR/"
    echo ""
    echo "   上传完成后重新运行此脚本。"
    exit 1
fi

# 4. 配置环境变量
echo "[4/7] 检查环境配置..."
if [ ! -f ".env" ]; then
    if [ -f "deploy/.env.production" ]; then
        cp deploy/.env.production .env
        echo "⚠️  已创建 .env 文件，请编辑填写密码和 API Key："
        echo "   nano $PROJECT_DIR/.env"
        echo ""
        echo "   必须修改的项目："
        echo "   - POSTGRES_PASSWORD (数据库密码)"
        echo "   - OPENAI_API_KEY (OpenAI API密钥)"
        echo "   - EMAIL (你的邮箱，用于SSL证书)"
        echo ""
        read -p "编辑完成后按 Enter 继续..."
    else
        echo "❌ 缺少 .env 配置文件，请先配置"
        exit 1
    fi
fi

# 加载环境变量
source .env

# 5. 首次启动（HTTP模式，用于获取SSL证书）
echo "[5/7] 首次启动服务 (HTTP模式)..."

# 使用初始化配置（无SSL）
cp deploy/nginx/conf.d/huidao-init.conf deploy/nginx/conf.d/default.conf 2>/dev/null || true
# 暂时移除SSL配置
rm -f deploy/nginx/conf.d/huidao.conf.bak
if [ -f deploy/nginx/conf.d/huidao.conf ]; then
    mv deploy/nginx/conf.d/huidao.conf deploy/nginx/conf.d/huidao.conf.bak
fi

docker compose up -d db app nginx

echo "等待服务启动..."
sleep 10

# 检查服务是否正常
if curl -s http://localhost:8000/api/health > /dev/null; then
    echo "✅ 应用服务正常"
else
    echo "⚠️  应用服务可能需要更多启动时间"
fi

# 6. 获取 SSL 证书
echo "[6/7] 获取 SSL 证书..."
echo "确保 DNS 已解析 $DOMAIN -> $(curl -s ifconfig.me)"
echo ""
read -p "确认 DNS 已配置好？(y/n) " confirm
if [ "$confirm" = "y" ]; then
    docker compose run --rm certbot certonly \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email ${EMAIL:-admin@$DOMAIN} \
        --agree-tos \
        --no-eff-email \
        -d $DOMAIN \
        -d www.$DOMAIN

    # 切换到SSL配置
    rm -f deploy/nginx/conf.d/default.conf
    rm -f deploy/nginx/conf.d/huidao-init.conf
    if [ -f deploy/nginx/conf.d/huidao.conf.bak ]; then
        mv deploy/nginx/conf.d/huidao.conf.bak deploy/nginx/conf.d/huidao.conf
    fi

    # 重新启动 nginx 使用SSL
    docker compose restart nginx
    echo "✅ SSL 证书已配置"
else
    echo "跳过 SSL 配置，当前使用 HTTP 模式"
    echo "DNS 配置好后运行: cd $PROJECT_DIR && sudo ./deploy.sh"
fi

# 7. 设置自动续期
echo "[7/7] 配置证书自动续期..."
cat > /etc/cron.d/certbot-renew << 'CRON'
0 3 * * * root cd /opt/huidao && docker compose run --rm certbot renew --quiet && docker compose restart nginx
CRON

echo ""
echo "=========================================="
echo "  ✅ 部署完成！"
echo "=========================================="
echo ""
echo "  网站地址: https://$DOMAIN"
echo "  API文档:  https://$DOMAIN/docs"
echo "  健康检查: https://$DOMAIN/api/health"
echo ""
echo "  常用命令:"
echo "  - 查看日志: cd $PROJECT_DIR && docker compose logs -f"
echo "  - 重启服务: cd $PROJECT_DIR && docker compose restart"
echo "  - 停止服务: cd $PROJECT_DIR && docker compose down"
echo "  - 更新代码: cd $PROJECT_DIR && docker compose build && docker compose up -d"
echo ""
