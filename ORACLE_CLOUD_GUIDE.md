# Oracle Cloud 免费 VPS 注册 + 部署机器人完整指南

## 免费套餐内容

| 资源 | 免费额度 |
|---|---|
| **ARM 实例** | 最高 **4 核 CPU + 24GB 内存**（永久免费） |
| **硬盘** | 总共 200GB |
| **网络** | 每月 10TB 流量 |
| **x86 实例** | 1 核 + 1GB 内存（也可选） |

> 你选 **ARM 架构**，因为免费额度更高。

---

## 第一部分：注册 Oracle Cloud 账号

### 准备工作

你需要准备：
1. **一个邮箱**（QQ邮箱、Gmail、Outlook 都可以）
2. **一部手机**（收验证码）
3. **一张信用卡**（Visa / Mastercard / 银联，**只验证身份，不会扣钱**，验证后立即退还）

### 注册步骤

#### 第 1 步：打开注册页面

在手机浏览器打开：
```
https://signup.cloud.oracle.com
```

#### 第 2 步：填写信息

| 字段 | 填写内容 |
|---|---|
| **国家** | 选择 `China`（中国） |
| **名字** | 填你的真实姓名拼音，如 `San` |
| **姓氏** | 填你的真实姓氏拼音，如 `Zhang` |
| **邮箱** | 填你的邮箱 |
| **密码** | 设置一个密码（至少8位，含大小写字母+数字） |

点 **Next** 继续。

#### 第 3 步：验证邮箱

1. 去邮箱查收 Oracle 发的验证邮件
2. 点击邮件里的 **Verify Email** 链接
3. 验证成功后，返回注册页面继续

#### 第 4 步：验证手机

1. 输入你的手机号（+86 开头的中国手机号）
2. 点击 **Request code**
3. 收到短信验证码后输入
4. 点击 **Verify Code**

#### 第 5 步：添加信用卡信息

| 字段 | 填写说明 |
|---|---|
| **卡号** | 你的信用卡号 |
| **有效期** | 信用卡上的 MM/YY |
| **CVV** | 信用卡背面三位数 |
| **持卡人姓名** | 信用卡上的姓名拼音 |
| **地址** | 随便填一个地址，如 `100 Beijing Road` |
| **城市** | 填你的城市，如 `Beijing` |
| **省份** | 填你的省份，如 `Beijing` |
| **邮编** | 填你所在城市的邮编，如 `100000` |

> 放心，**不会扣钱**。Oracle 只会扣 $1 验证，**立即退还**。

#### 第 6 步：确认并提交

1. 勾选同意条款
2. 点击 **Start subscription**
3. 等待 1-2 分钟，注册成功后会进入控制台

---

## 第二部分：创建实例（VM）

### 第 1 步：登录控制台

注册成功后会自动登录，如果没进去，打开：
```
https://cloud.oracle.com
```

用你的邮箱和密码登录。

### 第 2 步：创建实例

1. 点击左上角 **☰ 菜单** → **计算** → **实例**
2. 点击 **创建实例**
3. 填写以下信息：

| 字段 | 填什么 |
|---|---|
| **名称** | `tg-admin-bot`（随便填） |
| **所在区域** | 选离你最近的，如 `日本东京` 或 `韩国首尔` |
| **映像** | 选 `Ubuntu 24.04`（推荐） |
| **架构** | 选 **ARM**（⚠️ 注意：选这个才能免费 4 核 24GB） |
| **OCPU 数量** | 选 **4** |
| **内存** | 选 **24GB** |
| **SSH 密钥** | 选 **自动生成密钥对**，然后下载私钥文件 |
| **引导卷大小** | 默认 50GB（免费额度内） |

### 第 3 步：关于 SSH 密钥

当你选择 **自动生成密钥对** 后，Oracle 会下载一个 `.key` 文件到手机，**这个文件非常重要，一定要保存好！** 它是你远程连接服务器的钥匙。

### 第 4 步：点击创建

点击 **创建**，等待 1-2 分钟，实例状态变成 **运行中** 就搞定了。

### 第 5 步：查看公网 IP

在实例详情页，找到 **"公共 IP 地址"**，记下来（比如 `xxx.xxx.xxx.xxx`），后面连接服务器要用。

---

## 第三部分：连接服务器并部署机器人

### 用手机连接服务器

iPhone 需要安装一个 SSH 客户端 App，推荐：

| App | 免费 | 说明 |
|---|---|---|
| **Termius** | ✅ 免费版够用 | 最推荐，App Store 搜 "Termius" |
| **Blink Shell** | 收费 | 不用下 |
| **JuiceSSH** | Android 用 | |

#### 安装 Termius 后：

1. 打开 Termius → 点 **New Host**
2. 填写：

| 字段 | 填什么 |
|---|---|
| **Hostname** | 你的实例公网 IP（如 `xxx.xxx.xxx.xxx`） |
| **Port** | `22` |
| **Username** | `ubuntu` |
| **SSH Key** | 选择你从 Oracle 下载的那个 `.key` 文件 |

3. 点 **Save**，然后点连接（Connect）

### 连接成功后，执行以下命令：

#### 安装 Python 和依赖

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 和 pip
sudo apt install python3 python3-pip git -y

# 安装机器人依赖
pip3 install aiogram aiosqlite python-dotenv apscheduler aiohttp
```

#### 下载项目代码

```bash
# 创建项目目录
mkdir -p ~/telegram_admin_bot
cd ~/telegram_admin_bot

# 下载代码（两种方式）
```

**方式 A：从 GitHub 下载（推荐，后续更新方便）**

```bash
# 如果你有 GitHub，先初始化仓库
git init
git remote add origin https://github.com/你的用户名/telegram_admin_bot.git
git pull origin main
```

**方式 B：手动创建文件**

如果你没有 GitHub，我帮你把代码准备好，Termius 有文件传输功能，或者在服务器上直接创建文件。

#### 创建配置文件

```bash
nano .env
```

粘贴以下内容（按手机屏幕操作）：

```
BOT_TOKEN=8885923218:AAHTzLnrV6xFfmIWTDEWQWKq0f0Igu1-JKY
SUPER_ADMINS=8049091400
DATABASE_PATH=data/bot.sqlite3
PRIVATE_MODE=true
DEFAULT_WARN_LIMIT=3
DEFAULT_MUTE_SECONDS=3600
DEFAULT_SLOW_SECONDS=5
DEFAULT_SILENT_MESSAGES=3
DEFAULT_EXCHANGE_RATE=7.2
DEFAULT_FEE_RATE=0.05
WEB_PORT=8080
```

按 `Ctrl + X` → `Y` → `Enter` 保存退出。

#### 创建数据库目录

```bash
mkdir -p data
```

#### 启动机器人

```bash
cd ~/telegram_admin_bot
python3 -m bot.main
```

如果看到 `Web 管理后台已启动` 就说明成功了！

---

## 第四部分：让机器人后台运行

上面的命令关闭终端后机器人就会停止，我们需要让它 24 小时运行。

### 方法：使用 screen（推荐）

```bash
# 安装 screen
sudo apt install screen -y

# 创建后台会话
screen -dmS tg_bot bash -c "cd ~/telegram_admin_bot && python3 -m bot.main"

# 查看是否运行
screen -ls

# 进入机器人终端查看日志
screen -r tg_bot
# 按 Ctrl + A, D 退出（不中断运行）
```

### 设置开机自启

```bash
# 编辑 crontab
crontab -e
```

选择编辑器（选 `nano`），粘贴下面一行：

```
@reboot screen -dmS tg_bot bash -c "cd /home/ubuntu/telegram_admin_bot && python3 -m bot.main"
```

按 `Ctrl + X` → `Y` → `Enter` 保存。

---

## 第五部分：访问 Web 管理后台

在 Oracle Cloud 中，需要开放 8080 端口才能访问 Web 后台：

### 开放端口

1. 登录 Oracle Cloud 控制台
2. 点击左上角 **☰ 菜单** → **网络** → **虚拟云网络**
3. 点击你的 VCN（虚拟云网络）
4. 点击左侧 **安全列表**
5. 点击 **添加入站规则**
6. 填写：

| 字段 | 值 |
|---|---|
| 源类型 | CIDR |
| 源 CIDR | `0.0.0.0/0` |
| IP 协议 | TCP |
| 目标端口范围 | `8080` |

7. 点击 **添加入站规则**

### 访问地址

```
http://你的公网IP:8080
```

---

## 常用命令汇总

```bash
# 查看机器人是否在运行
screen -ls

# 进入机器人日志
screen -r tg_bot

# 退出日志（不中断运行）
# Ctrl + A, 然后按 D

# 停止机器人
screen -S tg_bot -X quit

# 重启机器人
screen -S tg_bot -X quit
screen -dmS tg_bot bash -c "cd ~/telegram_admin_bot && python3 -m bot.main"

# 更新代码（如果从 GitHub 下载）
cd ~/telegram_admin_bot && git pull
screen -S tg_bot -X quit
screen -dmS tg_bot bash -c "cd ~/telegram_admin_bot && python3 -m bot.main"
```

---

## 验证机器人

1. 打开 Telegram，私聊你的机器人 `@你的机器人用户名`
2. 发送 `/start`，如果能正常回复，说明机器人运行成功
3. 把机器人拉入你的群组，给它**管理员权限**
4. 在群内发送 `/adminlist` 查看管理员列表
5. 发送 `/owner` 查看主人信息
```