#!/bin/bash
# ============================================================
# 打包脚本 — 将项目打包为 Hugging Face Spaces 可上传的 ZIP
# 用法：
#   bash package_for_spaces.sh
#   输出：tg-admin-bot-for-spaces.zip
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

OUTPUT_NAME="tg-admin-bot-for-spaces"

echo "📦 正在打包项目为 Hugging Face Spaces 格式..."

# 创建临时目录
TMP_DIR=$(mktemp -d)
mkdir -p "$TMP_DIR/$OUTPUT_NAME"

# 复制必要文件（排除敏感和临时文件）
rsync -av \
  --exclude='.env' \
  --exclude='*.sqlite3' \
  --exclude='*.sqlite3-wal' \
  --exclude='*.sqlite3-shm' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='logs' \
  --exclude='.git' \
  --exclude='package_for_spaces.sh' \
  ./ "$TMP_DIR/$OUTPUT_NAME/"

# 创建 ZIP
cd "$TMP_DIR"
zip -r "$SCRIPT_DIR/$OUTPUT_NAME.zip" "$OUTPUT_NAME/"

# 清理
rm -rf "$TMP_DIR"

echo "✅ 打包完成！"
echo "   文件：$SCRIPT_DIR/$OUTPUT_NAME.zip"
echo "   大小：$(du -h "$SCRIPT_DIR/$OUTPUT_NAME.zip" | cut -f1)"
echo ""
echo "使用说明："
echo "   1. 登录 Hugging Face，创建 Space（Docker SDK）"
echo "   2. 进入 Space → Files → Add file → Upload files"
echo "   3. 解压 zip，拖拽所有文件上传"
echo "   4. 在 Settings → Repository Secrets 设置环境变量"
echo "   5. 在 Settings → Persistent Storage 创建 /data 存储"
echo "   6. 等待构建完成，机器人自动启动"