#!/bin/bash
# ============================================================
# 阿里云保活脚本 — 检查机器人是否在运行，不在则重启
# 添加到 crontab（每 10 分钟检查一次）：
#   crontab -e
#   添加：*/10 * * * * /root/telegram_admin_bot/cron_aliyun.sh
# ============================================================

PROJECT_DIR="/root/telegram_admin_bot"
SCREEN_NAME="tg_bot"

if ! command -v screen &> /dev/null; then
    exit 1
fi

if ! screen -ls 2>/dev/null | grep -q "$SCREEN_NAME"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 机器人不在运行，正在重启..." >> "$PROJECT_DIR/logs/keepalive.log"
    
    cd "$PROJECT_DIR" || exit 1
    
    screen -dmS "$SCREEN_NAME" \
        bash -c "cd '$PROJECT_DIR' && python3 -m bot.main >> logs/bot.log 2>&1"
    
    sleep 3
    if screen -ls 2>/dev/null | grep -q "$SCREEN_NAME"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 重启成功" >> "$PROJECT_DIR/logs/keepalive.log"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 重启失败" >> "$PROJECT_DIR/logs/keepalive.log"
    fi
fi