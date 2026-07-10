# Telegram 群组/频道管理员机器人（商业版）

基于 `Python + aiogram 3 + SQLite + aiohttp Web` 的全功能 Telegram 管理机器人。

## 升级内容（相比 V1）

- Web 管理后台（数据统计面板、日志查看、成员数据、CSV 导出）
- 实时汇率 API 接入（免费，无需 key）
- 客服中转系统升级（会话状态管理、封禁/关闭按钮、支持被限制发言的用户通过机器人私聊客服）
- 频道管理（按钮发帖、定时公告、自动发布）
- 验证码持久化到数据库（重启不丢失）
- CSV 日志导出（Web + Telegram 双通道）
- Docker 一键部署
- 禁止转发指定频道消息
- 清理不活跃成员
- 管理员权限同步

## 文件结构

```
telegram_admin_bot/
├── bot/
│   ├── __init__.py
│   ├── main.py          # 主程序（命令、消息监听、过滤、记账、客服中转）
│   ├── config.py         # 配置管理
│   ├── db.py             # 数据库层（SQLite，16 张表）
│   ├── utils.py          # 工具函数
│   ├── exchange.py       # 实时汇率 API
│   ├── export.py         # CSV 导出
│   ├── services.py       # 客服中转服务 + 频道管理服务
│   └── web.py            # Web 管理后台
├── data/                 # 数据库存储目录
├── logs/                 # 日志目录（Serv00 自动创建）
├── requirements.txt      # Python 依赖
├── .env.example          # 环境配置样例
├── Dockerfile            # Docker 镜像配置
├── docker-compose.yml    # Docker Compose 配置
├── start_bot.sh          # Serv00 启动脚本（screen）
├── cron_keepalive.sh     # Serv00 保活脚本（cron）
└── README.md             # 本文件
```

## 功能总览

### 入群/离群管理

- 入群欢迎，`{name}` 自动 @ 新人
- 离群记录，写入操作日志
- 入群验证码（数据库持久化，重启不丢失）
- Silent 模式（新成员前 N 条消息自动审核，链接/转发会被删除）
- 被限制发言的用户自动提示私聊机器人联系客服

### 广告/垃圾过滤

- `/addword` / `/delword` 关键词过滤
- `/adddomain` / `/deldomain` 域名过滤
- 白名单用户不受过滤影响
- 刷屏检测（短时间大量消息/重复消息）
- 禁止转发指定频道消息
- 全局黑名单（一个群 ban 自动在所有群生效）

### 禁言/封禁/踢出

| 命令 | 作用 |
|---|---|
| `/mute` | 回复用户禁言，支持 1m/1h/1d/永久 |
| `/unmute` | 解除禁言 |
| `/ban` | 封禁 + 全局黑名单 |
| `/unban` | 解封 + 移出全局黑名单 |
| `/kick` | 踢出 |
| `/warn` | 警告，累计 N 次自动封禁 |

### 消息管理

- `/del` 回复消息删除
- `/clean 100` 批量清理
- `/lock` / `/unlock` 锁群
- `/slow 10` 慢速检测

### 频道管理

- `/post 频道ID 文字` — 发送到频道
- `/postbtn 频道ID 标题|按钮名1=URL1|按钮名2=URL2` — 带按钮发帖
- `/schedule 列表` — 查看定时公告
- `/schedule 删除 ID` — 删除定时公告
- 频道定时帖子自动发布（每分钟检查）

### 管理员功能

- 多层级管理员（超级管理员 / 普通管理员）
- 全局超级管理员（`.env` 配置）
- `/setadmin` / `/deladmin` 自定义管理员
- `/updategroup` 同步群管理员权限
- `/adminlist` 查看管理员
- `/logs` 操作日志
- `/stats` 统计面板
- `/broadcast` 全群广播
- `/export` CSV 文件导出（日志 + 账单）
- `/cleaninactive [天数]` 清理不活跃成员

### 群员自助

- `/rules` 查看群规
- `/report` 举报
- `/me` 查看自己的数据
- `/rank` 活跃榜

### 记账功能

| 指令 | 说明 |
|---|---|
| `+100` / `入款+100` | 正入账 |
| `-100` / `入款-100` | 负入账/冲正 |
| `+100/0.05` | 指定费率入账 |
| `下发100` | 正下发 |
| `下发-100` | 负下发 |
| `100*7.2` | 算式计算 |
| `+0` / `显示账单` | 查看账单 |
| `开始` / `开始记账` | 开启记账 |
| `关闭记账` | 静默记账 |
| `打开记账` | 恢复提醒 |
| `保存账单` | 存档编号 +1 |
| `清理当日账单` | 清空当前 |
| `删除历史账单` | 彻底删除 |
| `设置汇率 7.2` | 固定汇率 |
| `设置费率 0.05` | 固定费率 |
| `设置汇率上浮 0.1` | 上浮 |
| `设置汇率下浮 0.1` | 下浮 |
| `设置实时汇率` | 切换实时模式 |
| `z0` / `Z0` | 查看实时汇率 |
| `显示模式 1/2/3` | 账单排版样式 |
| `本群记账` | 查看群状态 |
| `设置不允许操作人` | 禁止指定人记账 |
| `删除不允许操作人` | 恢复记账权限 |
| `显示不允许操作人` | 黑名单列表 |

### 实时汇率

- 发送 `z0` 或 `Z0` 查看实时汇率
- `设置实时汇率` 切换为实时模式
- `设置汇率 7.2` 切换回固定汇率
- 支持 USD/CNY/EUR/GBP/JPY/KRW/RUB/THB
- 5 分钟缓存

### 私聊客服中转

**完整流程：**

1. 用户在群内被限制发言（禁言/锁群）
2. 用户私聊机器人
3. 机器人把消息转给所有客服管理员
4. 管理员收到消息后，点击「回复」按钮或直接回复消息
5. 机器人把管理员回复转回给用户
6. 用户收到回复，继续对话

**管理员按钮功能：**
- 「回复」 — 快速定位会话
- 「封禁客服」 — 禁止该用户使用客服 24 小时
- 「结束会话」 — 关闭该用户所有会话

**支持消息类型：** 文字、图片提示、文件提示、贴纸提示、语音提示、视频提示

### Web 管理后台

启动后访问 `http://你的服务器:8080`

功能：
- 选择群组查看统计
- 数据面板（成员数、消息数、今日操作）
- 操作日志查看
- 记账明细查看
- 成员数据排名
- 日志 CSV 导出
- 账单 CSV 导出

## 安装部署

### 方式一：Python 直接运行

```bash
cd telegram_admin_bot
cp .env.example .env
# 编辑 .env 填写 BOT_TOKEN、SUPER_ADMINS 等

python3 -m pip install -r requirements.txt --break-system-packages
python3 -m bot.main
```

### 方式二：Docker 一键部署

```bash
cd telegram_admin_bot
cp .env.example .env
# 编辑 .env 填写配置

docker-compose up -d
```

### 方式三：Docker 手动构建

```bash
cd telegram_admin_bot
docker build -t telegram-admin-bot .
docker run -d --name bot \
  -v bot-data:/app/data \
  -p 8080:8080 \
  --env-file .env \
  telegram-admin-bot
```

### 方式四：Zeabur 免费部署（推荐，无需信用卡）

Zeabur 是一个国产云平台，**无需信用卡**，用 GitHub 或邮箱就能注册，支持 Python 和 Docker 一键部署 [$TRAE_REF](https://zeabur.com/docs/zh-CN/get-started/quick-start)。

#### 注册 Zeabur

1. 打开 [zeabur.com](https://zeabur.com)
2. 点击右上角 **Sign in** → **Sign up**
3. 可以使用 **GitHub** 一键登录，或者用 **邮箱** 注册
4. 登录后，Zeabur 会自动引导你创建一个项目

#### 创建项目并部署

**方法 A：通过 GitHub 部署（推荐，后续更新方便）**

1. 先把项目代码推送到你的 GitHub 仓库
2. 在 Zeabur 控制台，点击 **创建项目**
3. 点击 **部署新服务** → **GitHub**
4. 首次使用需要授权 GitHub 账号
5. 搜索并选择你的仓库（`telegram_admin_bot`）
6. Zeabur 会自动检测到 `Dockerfile`，无需额外配置
7. 点击 **部署**

**方法 B：通过本地文件上传（不需要 GitHub）**

1. 在 Zeabur 控制台，点击 **创建项目**
2. 点击 **部署新服务** → **本地项目**
3. 把整个 `telegram_admin_bot` 文件夹拖拽上传
4. Zeabur 会自动检测到 `Dockerfile` 并开始构建

#### 设置环境变量

部署开始后，进入服务页面 → **Variables** 标签，添加以下环境变量：

| 变量名 | 值 | 说明 |
|---|---|---|
| `BOT_TOKEN` | `8885923218:AAHTzLnrV6xFfmIWTDEWQWKq0f0Igu1-JKY` | 你的 Bot Token |
| `SUPER_ADMINS` | `8049091400` | 你的 Telegram ID |
| `PRIVATE_MODE` | `true` | 私有模式 |

其他可选变量（全部用默认值即可）：

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `DEFAULT_WARN_LIMIT` | `3` | 警告上限 |
| `DEFAULT_MUTE_SECONDS` | `3600` | 默认禁言秒数 |
| `DEFAULT_SLOW_SECONDS` | `5` | 慢速检测秒数 |
| `DEFAULT_SILENT_MESSAGES` | `3` | 新成员审核条数 |
| `DEFAULT_EXCHANGE_RATE` | `7.2` | 默认汇率 |
| `DEFAULT_FEE_RATE` | `0.05` | 默认费率 |
| `WEB_PORT` | `8080` | Web 后台端口 |

> 注意：**不要**把 `.env` 文件上传到代码仓库（已在 `.gitignore` 中排除），所有敏感信息通过 Variables 设置。

#### 验证机器人

1. 部署完成后，打开 Telegram
2. 私聊你的机器人（`@你之前设置的机器人用户名`）
3. 发送 `/start`，如果能正常回复，说明部署成功
4. 把机器人拉入你的群组，给予**管理员权限**
5. 发送 `/adminlist` 查看管理员列表
6. 发送 `/owner` 查看主人信息

#### 访问 Web 管理后台

在 Zeabur 服务页面 → **Domains** 标签，可以看到系统分配的域名（如 `xxx.zeabur.app`），通过这个地址即可访问 Web 管理后台。

#### 关于休眠

Zeabur 免费版在长时间无活动时会自动休眠。但我们的机器人每隔几秒就会轮询 Telegram 服务器，**相当于持续活动**，所以不会进入休眠状态。

#### 更新代码

如果通过 GitHub 部署，推送代码到仓库后，Zeabur 会自动重新构建和部署。如果通过本地文件上传，需要重新上传文件。

## 配置说明

`.env` 配置项：

| 配置项 | 说明 | 示例 |
|---|---|---|
| `BOT_TOKEN` | BotFather 获取的 Token | `123456:ABC-DEF...` |
| `SUPER_ADMINS` | 超级管理员 ID，逗号分隔 | `123456789,987654321` |
| `SUPPORT_ADMINS` | 客服管理员 ID，为空用 SUPER_ADMINS | `123456789` |
| `LOG_CHAT_ID` | 日志群 ID，为空不发日志 | `-100123456789` |
| `DATABASE_PATH` | SQLite 数据库路径 | `data/bot.sqlite3` |
| `DEFAULT_WARN_LIMIT` | 警告上限 | `3` |
| `DEFAULT_MUTE_SECONDS` | 默认禁言秒数 | `3600` |
| `DEFAULT_SLOW_SECONDS` | 慢速检测秒数 | `5` |
| `DEFAULT_SILENT_MESSAGES` | 新成员审核消息数 | `3` |
| `DEFAULT_EXCHANGE_RATE` | 默认汇率 | `7.2` |
| `DEFAULT_FEE_RATE` | 默认费率 | `0.05` |
| `WEB_PORT` | Web 后台端口 | `8080` |

获取自己的数字 ID：私聊 `@userinfobot`

## 重要限制

- Telegram Bot API 不提供用户账号注册时间
- 机器人无法通过 @用户名 稳定反查用户 ID，建议命令通过回复使用
- Telegram 限制删除较旧消息，/clean 不保证全部删除
- 实时汇率使用免费 API，可能有请求限制和延迟
- Web 后台当前无登录认证，建议用 Nginx 或防火墙保护 8080 端口

## Serv00 部署指南

Serv00 是 FreeBSD 系统的免费虚拟主机，同样可以运行这个机器人。

### 局限性

| 项目 | 说明 |
|---|---|
| 系统 | FreeBSD（非 Linux），代码完全兼容 |
| 内存 | 512MB 上限，机器人约用 100-150MB，足够 |
| 外网端口 | 8080 端口无法外部访问，**Web 后台不可用** |
| 持久化 | 无 systemd，需要 `screen` + `cron` 保活 |
| 存储 | 3GB / 永久免费 |

### 部署步骤

#### 1. 上传代码

通过 SSH 或 Serv00 的文件管理器，把 `telegram_admin_bot` 文件夹上传到你的域名目录下，例如：

```
/home/你的用户名/domains/你的域名/telegram_admin_bot/
```

#### 2. 配置环境变量

```bash
cd ~/domains/你的域名/telegram_admin_bot
cp .env.example .env
nano .env
```

填写 `BOT_TOKEN`、`SUPER_ADMINS`，其他保持默认。

#### 3. 安装依赖

```bash
pip3 install -r requirements.txt --break-system-packages
```

> 如果提示 `aiogram` 安装失败，先升级 pip：`pip3 install --upgrade pip --break-system-packages`

#### 4. 修改启动脚本路径

编辑 `start_bot.sh` 和 `cron_keepalive.sh`，把里面的项目路径改成你的实际路径：

```bash
nano start_bot.sh
# 把 PROJECT_DIR 改成你的实际路径
```

#### 5. 启动机器人

```bash
bash start_bot.sh
```

首次启动会自动安装依赖并创建 `screen` 会话。

#### 6. 设置保活（cron）

```bash
crontab -e
```

添加一行（每 10 分钟检查一次）：

```
*/10 * * * * /home/你的用户名/domains/你的域名/telegram_admin_bot/cron_keepalive.sh
```

#### 7. 查看状态

```bash
# 查看 screen 会话
screen -ls

# 进入机器人终端
screen -r tg_bot

# 分离会话（不中断运行）
# Ctrl + A, 然后按 D

# 查看日志
tail -f ~/domains/你的域名/telegram_admin_bot/logs/bot.log
```

#### 8. 重启机器人

```bash
screen -S tg_bot -X quit
bash start_bot.sh
```

### 已知问题

- **Web 后台不可用**：Serv00 不开放自定义端口外网访问，`DISABLE_WEB=1` 环境变量会自动关闭 Web 服务器
- **进程偶尔被杀死**：Serv00 可能会杀掉长时间空闲的进程，`cron_keepalive.sh` 会每 10 分钟检查并重启
- **数据库文件**：默认在 `data/bot.sqlite3`，重启后数据不会丢失

## 推荐 Web 后台安全加固

```nginx
# Nginx 反向代理 + Basic Auth
location / {
    proxy_pass http://127.0.0.1:8080;
    auth_basic "Admin Panel";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

## Hugging Face Spaces 部署指南（免费，无需信用卡）

Hugging Face Spaces 提供 **2 vCPU + 16GB RAM + 50GB 硬盘** 的免费 Docker 容器，完全不需要信用卡，用邮箱就能注册。这是目前最适合你的部署方案。

### 优势

| 项目 | 说明 |
|---|---|
| 费用 | **完全免费**，无需绑定银行卡 |
| 配置 | 2 vCPU / 16GB RAM / 50GB 硬盘 |
| Web 后台 | 有独立公网 URL，可直接访问 |
| 持久化 | 支持挂载持久化存储目录 |
| 注册 | 只需邮箱，国内可访问 |

### 第一步：注册 Hugging Face 账号

1. 打开 [huggingface.co](https://huggingface.co)
2. 点击右上角 **Sign Up**
3. 输入你的 **邮箱地址**，设置用户名和密码
4. 去邮箱查收验证邮件，点击验证链接
5. 登录后，你就拥有了一个免费账号

### 第二步：创建 Space（容器环境）

1. 登录后，点击右上角头像 → **New Space**
2. 填写以下信息：
   - **Space Name**：填 `tg-admin-bot`（或你喜欢的名字）
   - **License**：选 `MIT`
   - **Space SDK**：选 **Docker**
   - **Docker Template**：选 **Blank**
   - **Space Hardware**：选 **CPU free**（免费）
   - **Space Visibility**：选 **Public**
3. 点击 **Create Space**

### 第三步：上传项目代码

Hugging Face Spaces 使用 Git 管理代码，有两种方式上传：

#### 方式 A：通过网页上传（最简单）

1. 进入你刚创建的 Space 页面
2. 点击 **Files** 标签 → **Add file** → **Upload files**
3. 把整个 `telegram_admin_bot` 文件夹里的 **所有文件** 拖拽上传
4. 在 Commit message 里写 `Initial commit`
5. 点击 **Commit changes**

#### 方式 B：通过 Git 命令行上传（推荐，后续更新方便）

```bash
# 安装 git（如果还没有）
# 配置 git
git config --global user.name "你的用户名"
git config --global user.email "你的邮箱"

# 克隆你的 Space 仓库（用你的用户名替换下面）
git clone https://huggingface.co/spaces/你的用户名/tg-admin-bot
cd tg-admin-bot

# 把项目文件复制过来
cp -r /path/to/telegram_admin_bot/* .

# 提交并推送
git add .
git commit -m "Initial commit"
git push
```

> 推送时会提示输入用户名和密码，密码使用 **Hugging Face Token**（不是登录密码）：
> 1. 打开 [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
> 2. 点击 **New token**，权限选 **Write**
> 3. 复制生成的 token，粘贴到 Git 密码输入框

### 第四步：设置环境变量（关键）

上传代码后，Space 会自动开始构建。在构建的同时，设置环境变量：

1. 进入 Space 页面 → **Settings** 标签
2. 往下翻到 **Repository Secrets** 区域
3. 点击 **New secret**，逐个添加以下变量（注意 **不要** 用引号）：

| 变量名 | 值 | 说明 |
|---|---|---|
| `BOT_TOKEN` | `8885923218:AAHTzLnrV6xFfmIWTDEWQWKq0f0Igu1-JKY` | 你的 Bot Token |
| `SUPER_ADMINS` | `8049091400` | 你的 Telegram ID |
| `PRIVATE_MODE` | `true` | 私有模式 |
| `DEFAULT_WARN_LIMIT` | `3` | 警告上限 |
| `DEFAULT_MUTE_SECONDS` | `3600` | 默认禁言秒数 |
| `DEFAULT_SLOW_SECONDS` | `5` | 慢速检测秒数 |
| `DEFAULT_SILENT_MESSAGES` | `3` | 新成员审核条数 |
| `DEFAULT_EXCHANGE_RATE` | `7.2` | 默认汇率 |
| `DEFAULT_FEE_RATE` | `0.05` | 默认费率 |

> **重要**：`BOT_TOKEN` 和 `SUPER_ADMINS` 已经设置为你的值，直接复制粘贴即可。

### 第五步：设置持久化存储（让数据库不丢失）

Hugging Face Spaces 重启后容器内数据会丢失，但可以用持久化存储：

1. 在 Space 页面 → **Settings** 标签
2. 找到 **Persistent Storage** 区域
3. 点击 **Create Storage**
4. 目录填 `/data`（注意是 `/data` 不是 `/app/data`）
5. 点击 **Create**

> 启动脚本会自动将数据库链接到 `/data` 目录，这样即使 Space 重启，数据也不会丢失。

### 第六步：等待构建完成

1. 切到 **Builder** 标签，可以看到构建日志
2. 首次构建需要 3-5 分钟（下载依赖、安装包）
3. 构建完成后，Space 自动启动
4. 启动日志显示 `Web 管理后台已启动` 即表示成功

### 第七步：验证机器人是否在线

1. 打开 Telegram，私聊你的机器人（`@你的机器人用户名`）
2. 发送 `/start`，如果能正常回复，说明机器人运行成功
3. 把机器人拉入你的群组，给它**管理员权限**
4. 在群内发送 `/adminlist` 查看管理员列表
5. 发送 `/owner` 查看主人信息

### 访问 Web 管理后台

你的 Space 页面会自动显示一个 **Embed** 或者可以直接访问：

```
https://你的用户名-tg-admin-bot.hf.space
```

> 例如，如果你的用户名是 `abc123`，那么地址就是：
> `https://abc123-tg-admin-bot.hf.space`

### 检查机器人状态

在 Space 页面 → **Logs** 标签可以查看实时日志，如果机器人运行正常，你会看到类似：

```
2024-01-01 12:00:00 [bot.main] INFO: 机器人已启动...
2024-01-01 12:00:00 [bot.main] INFO: Web 管理后台已启动：http://0.0.0.0:8080
```

### 更新代码

当你的机器人代码更新后：

```bash
cd tg-admin-bot  # 你的本地仓库
git add .
git commit -m "更新了XXX功能"
git push
```

推送后，Hugging Face 会自动重新构建并部署，无需手动操作。

### 注意事项

- **持久化存储**：务必设置，否则 Space 重启（约每 2 周一次）后数据会丢失
- **日志查看**：在 Space 的 **Logs** 标签查看机器人运行日志
- **重启 Space**：如果机器人卡死，可以在 Settings → **Restart Space** 重启
- **休眠**：Hugging Face 免费 Space 48 小时无活动会休眠，但机器人一直在轮询 Telegram，**不会休眠**
- **Web 后台**：没有登录认证，建议不要存储敏感信息。如需加固，可自行添加 Nginx 反向代理

### 故障排除

| 问题 | 解决方法 |
|---|---|
| 构建失败 | 检查 Logs 中的错误信息，通常是依赖问题 |
| 机器人无响应 | 检查 BOT_TOKEN 是否设置正确 |
| 数据库丢失 | 检查是否设置了 Persistent Storage 到 `/data` |
| 端口冲突 | HF Spaces 自动检测 8080 端口，无需修改 |
| 机器人启动但 Web 打不开 | 等待 1-2 分钟，HF 代理需要时间初始化 |
