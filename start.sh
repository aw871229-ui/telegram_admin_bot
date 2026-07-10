#!/bin/bash
# ============================================================
# Hugging Face Spaces 启动脚本
# ============================================================

set -e

echo "=========================================="
echo "  Telegram 管理员机器人 - 启动中..."
echo "=========================================="

# 如果 /data 目录存在（Hugging Face 持久化存储挂载），将数据库链接到 /data
if [ -d "/data" ] && [ -w "/data" ]; then
    echo "检测到 /data 持久化存储目录"
    
    # 如果 /data 下已有数据库文件，直接使用
    if [ -f "/data/bot.sqlite3" ]; then
        echo "使用已有的数据库文件"
        ln -sf /data/bot.sqlite3 /app/data/bot.sqlite3
    else
        echo "创建新的数据库文件在持久化存储中"
        # 确保 /app/data 存在且为软链接
        rm -f /app/data/bot.sqlite3 2>/dev/null || true
        ln -sf /data/bot.sqlite3 /app/data/bot.sqlite3
    fi
    
    # 如果 /data 下有日志目录，也链接过去
    if [ -d "/data/logs" ]; then
        rm -rf /app/logs 2>/dev/null || true
        ln -sf /data/logs /app/logs
    else
        mkdir -p /data/logs
        rm -rf /app/logs 2>/dev/null || true
        ln -sf /data/logs /app/logs
    fi
else
    echo "未检测到持久化存储，使用容器内存储"
fi

# 确保必要的目录存在
mkdir -p /app/data /app/logs

# 打印环境变量（隐藏 Token 中间部分）
TOKEN_MASK="${BOT_TOKEN:0:6}...${BOT_TOKEN: -4}"
echo "BOT_TOKEN: $TOKEN_MASK"
echo "SUPER_ADMINS: $SUPER_ADMINS"
echo "数据库路径: $(readlink -f /app/data/bot.sqlite3 2>/dev/null || echo '/app/data/bot.sqlite3')"

# 启动机器人
echo "=========================================="
echo "  正在启动机器人..."
echo "  Web 后台: http://0.0.0.0:8080"
echo "=========================================="

# 进入项目目录
cd /app

# 启动机器人（前台运行，日志输出到 stdout）
python3 -m bot.main