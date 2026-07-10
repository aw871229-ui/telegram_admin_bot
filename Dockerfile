FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 数据库目录
RUN mkdir -p /app/data

# 暴露 Web 管理后台端口
EXPOSE 8080

# 启动机器人
CMD ["python3", "-m", "bot.main"]