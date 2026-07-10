#!/bin/bash
# ============================================================
# 阿里云启动脚本 — 用 screen 让机器人后台持续运行
# 阿里云有公网 IP，Web 管理后台也开启，可直接访问 http://服务器IP:8080
# ============================================================
# 用法：
#   1. 首次启动：  bash start_aliyun.sh
#   2. 查看状态：  screen -ls
#   3. 进入终端：  screen -r tg_bot
#   4. 分离(不中断)：Ctrl + A, 然后按 D
#   5. 停止机器人：screen -S tg_bot -X quit
# ============================================================

# 改成你的实际路径
PROJECT_DIR="/root/telegram_admin_bot"
SCREEN_NAME="tg_bot"

# 检查 screen 是否可用
if ! command -v screen &> /dev/null; then
    echo "📦 正在安装 screen..."
    apt install -y screen > /dev/null 2>&1
fi

# 如果 screen 会话已存在，先杀掉重启
screen -S "$SCREEN_NAME" -X quit &>/dev/null

# 进入项目目录
cd "$PROJECT_DIR" || { echo "❌ 目录不存在：$PROJECT_DIR"; exit 1; }

# 检查 .env 是否存在
if [ ! -f ".env" ]; then
    echo "❌ 未找到 .env 文件！请先复制 .env.example 并配置。"
    echo "   cp .env.example .env"
    exit 1
fi

# 检查依赖是否已安装
if ! python3 -c "import aiogram" 2>/dev/null; then
    echo "📦 正在安装依赖..."
    pip3 install -r requirements.txt --break-system-packages
fi

# 创建日志目录
mkdir -p logs

echo "🚀 正在启动机器人（screen 会话: $SCREEN_NAME）..."
echo "   查看日志：tail -f $PROJECT_DIR/logs/bot.log"
echo "   Web 后台：http://服务器IP:8080"

# 在 screen 中启动（阿里云有公网IP，开启 Web 后台）
screen -dmS "$SCREEN_NAME" \
    bash -c "cd '$PROJECT_DIR' && python3 -m bot.main >> logs/bot.log 2>&1"

# 等待几秒检查是否启动成功
sleep 3
if screen -ls | grep -q "$SCREEN_NAME"; then
    echo ""
    echo "============================================"
    echo " ✅ 机器人已成功启动！"
    echo "============================================"
    echo "   进入终端：screen -r $SCREEN_NAME"
    echo "   分离会话：Ctrl + A, 然后按 D"
    echo "   停止机器人：screen -S $SCREEN_NAME -X quit"
    echo "   查看日志：tail -f logs/bot.log"
    echo "   Web管理后台：http://服务器IP:8080"
    echo "============================================"
else
    echo "❌ 启动失败，查看日志："
    tail -n 30 "$PROJECT_DIR/logs/bot.log"
fi