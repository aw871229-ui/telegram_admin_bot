#!/bin/bash
# ============================================================
# Serv00 保活脚本 — 检查机器人是否在运行，不在则重启
# 用法：
#   1. 添加到 crontab：
#      crontab -e
#      添加：*/10 * * * * /home/你的用户名/domains/你的域名/telegram_admin_bot/cron_keepalive.sh
# ============================================================

# 项目绝对路径（请改成你的实际路径）
PROJECT_DIR="/home/你的用户名/domains/你的域名/telegram_admin_bot"
SCREEN_NAME="tg_bot"

# 检查 screen 会话是否存活
if ! screen -ls 2>/dev/null | grep -q "$SCREEN_NAME"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 机器人不在运行，正在重启..." >> "$PROJECT_DIR/logs/keepalive.log"
    
    cd "$PROJECT_DIR" || exit 1
    
    # 重新启动
    screen -dmS "$SCREEN_NAME" \
        bash -c "cd '$PROJECT_DIR' && DISABLE_WEB=1 python3 -m bot.main >> logs/bot.log 2>&1"
    
    sleep 3
    if screen -ls 2>/dev/null | grep -q "$SCREEN_NAME"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 重启成功" >> "$PROJECT_DIR/logs/keepalive.log"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 重启失败" >> "$PROJECT_DIR/logs/keepalive.log"
    fi
fi