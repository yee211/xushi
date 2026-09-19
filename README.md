# 📅 序时 (XuShi) —— 统一全栈仓库

> 本仓库由 `ClassSchedule`（网页 + Android）与 `wx_ClassSchedule`（微信小程序）整合而成：
> **一套 FastAPI 后端同时服务网页端、Android 客户端与微信小程序**；三端前端代码各自保留原样。

```
xushi/
├── server/                 # 统一 FastAPI 后端（唯一后端，双协议鉴权）
│   ├── app/
│   │   ├── main.py         # 应用装配：中间件、路由注册、静态托管
│   │   ├── settings.py     # 合并配置与启动强校验
│   │   ├── rate_limit.py   # 滑动窗口限流（登录/反馈/管理后台）
│   │   ├── observability.py# 结构化日志
│   │   ├── db/             # 连接池 + 幂等建表/旧库就地升级
│   │   ├── auth/           # JWT(网页) + sessions(小程序) 双通道统一依赖
│   │   ├── routers/        # 按领域拆分的 12 个路由模块
│   │   ├── services/       # 导入落库/课表查询/LLM配置/推送/天气/绑定/反馈
│   │   ├── agent/          # 课表 Agent（意图识别 → 技能调度 → 润色）
│   │   ├── channels/       # 微信 ClawBot iLink Worker + 企业微信回调
│   │   ├── excel/parser/html_parser  # Excel/HTML 多格式读取与确定性解析
│   │   └── ai.py adjustment_ai.py    # OpenAI 兼容 AI 解析（支持管理后台动态配置）
│   ├── admin/              # 管理后台静态页（/admin）
│   ├── tests/              # 300+ 离线单元测试（两侧套件合并）
│   ├── migrations/         # alembic 迁移（0001~0011）
│   ├── deploy/             # Dockerfile + docker-compose（api+worker+db+redis+备份）
│   └── scripts/            # e2e / 备份 / 发版 / A/B 对比脚本
├── frontend/               # Vue3 网页端 + Capacitor Android 工程（原样保留）
├── miniapp/                # 微信小程序（原样保留）
├── data/app_version.json   # Android 版本元数据
└── static/downloads/       # APK 分发目录
```

## 🔑 两端如何共用一个后端

| 能力 | 网页端 / Android | 微信小程序 |
| :--- | :--- | :--- |
| 登录 | `/api/register` `/api/login`（邮箱+密码，JWT） | `/api/auth/wechat`（wx.login code → openid，可撤销会话） |
| 鉴权 | `Authorization: Bearer <JWT>` | `Authorization: Bearer <session token>` |
| 课表/课程/调课/导入/反馈 | 同一套端点、同一套业务规则 | 同一套端点、同一套业务规则 |
| 账号互通（微信同步课表） | 个人中心生成六位绑定码：`POST /api/account/link/code` | 课表助手页输码绑定：`POST /api/account/link`（openid 并入邮箱账号行，两端共用同一份课表，无需同步） |
| 平台专属 | `/api/import-html`、`/api/app/version`、`/downloads` | `/api/config`、`/api/schedules/demo`、Agent 绑定与扫码连接 |

统一鉴权依赖 `app/auth/deps.py`：JWT 形态令牌（含两个点）直接无状态校验；
小程序随机令牌查 `sessions` 表（可撤销、有过期）。两类令牌空间不重叠。

## 🚀 本地开发

```bash
# 1. 数据库（任选其一：Docker 或本地 PostgreSQL）
docker run -d --name xushi-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=xushi_schedule -p 5432:5432 postgres:17-alpine

# 2. 后端
cd server
python -m venv venv && venv/Scripts/activate   # Windows
pip install -r requirements-dev.txt
copy .env.example .env                          # 开发环境默认可用
uvicorn app.main:app --reload --port 8000

# 3. 网页端（Vite 已把 /api 代理到 8000）
cd frontend && npm install && npm run dev

# 4. 小程序：微信开发者工具打开 miniapp/，config.js 的 DEV_API_BASE_URL
#    已指向 http://127.0.0.1:8000，开发工具内用 code=dev 静默登录
```

## 🧪 测试

```bash
cd server
venv/Scripts/python -m pytest tests/ -q        # 300+ 离线单元测试
venv/Scripts/python -m ruff check app tests scripts migrations
```

## 📦 生产部署

```bash
cd server/deploy
cp .env.example .env   # 填写数据库密码、微信凭证、JWT 密钥等
docker compose build && docker compose up -d
```

- 单一 `api` 服务同时承载网页端与小程序（`127.0.0.1:8010`）；
- `weixin-worker` 独立进程运行微信 ClawBot 长轮询；
- `db-backup` 每日全量备份并清理 14 天前的旧文件；
- Nginx 反代示例见 `server/deploy/nginx-api.conf.example`：
  `api.tanzeng.xyz` 与 `wx-api.tanzeng.xyz` 可同时反代到同一服务，
  两个前端的线上配置无需改动。

## 🗄️ 数据库合并策略

`server/app/db/schema.py` 的 `init_db()` 在启动时幂等建表并就地升级旧库：

- **旧网页母版库**（users 表为 email 体系）：自动补 `openid` 等列，`feedback`
  表数据自动迁入 `feedbacks`；
- **旧小程序版库**（users 表为 openid 体系）：自动补 `email/username/password_hash`；
- **全新库**：直接得到完整统一 schema + 演示数据种子。

把 `DATABASE_URL` 指向任意一侧的旧库即可平滑切换，无需手动迁移。
