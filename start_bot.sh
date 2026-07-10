#!/bin/bash
# ============================================================
# Serv00 启动脚本 — 用 screen 让机器人后台持续运行
# 用法：
#   1. 首次启动：  bash start_bot.sh
#   2. 查看状态：  screen -ls
#   3. 进入终端：  screen -r tg_bot
#   4. 退出(不中断)：Ctrl + A, 然后按 D
#   5. 停止机器人：screen -S tg_bot -X quit
# ============================================================

# 项目绝对路径（请改成你的实际路径）
PROJECT_DIR="/home/你的用户名/domains/你的域名/telegram_admin_bot"
SCREEN_NAME="tg_bot"

# 检查 screen 是否可用
if ! command -v screen &> /dev/null; then
    echo "❌ 未找到 screen 命令，请先安装：pkg install screen"
    exit 1
fi

# 如果 screen 会话已存在，先杀掉
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

# 在 screen 中启动
screen -dmS "$SCREEN_NAME" \
    bash -c "cd '$PROJECT_DIR' && DISABLE_WEB=1 python3 -m bot.main >> logs/bot.log 2>&1"

# 等待几秒检查是否启动成功
sleep 3
if screen -ls | grep -q "$SCREEN_NAME"; then
    echo "✅ 机器人已成功启动！"
    echo "   进入终端：screen -r $SCREEN_NAME"
    echo "   分离会话：Ctrl + A, D"
    echo "   停止机器人：screen -S $SCREEN_NAME -X quit"
else
    echo "❌ 启动失败，查看日志："
    tail -n 20 "$PROJECT_DIR/logs/bot.log"
fi