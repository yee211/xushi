# 序时微信小程序

本项目以 `ClassSchedule` 为唯一母版，将其业务、交互和视觉设计移植为原生微信小程序；微信登录替代网页邮箱登录，Android APK 更新等平台专属能力不进入小程序。

原生微信小程序 + FastAPI + PostgreSQL。后端通过 `wx.login` 的 code 调用微信 `jscode2session`，生成随机 Bearer 会话；所有课表、课程、导入和删除操作均按微信用户 `openid` 隔离。

## 目录

- 小程序源码：项目根目录，用微信开发者工具直接打开
- `server/`：FastAPI API 与课表解析服务

## 本地后端

```bash
cd server
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8010
```

本地调试需在 `server/.env` 显式设置 `APP_ENV=development`，并可设置 `WECHAT_DEV_OPENID=local-dev-user`，再直接向 `/api/auth/wechat` 提交 `{ "code": "dev" }`。服务端未配置 `APP_ENV` 时按生产环境处理；生产环境必须删除 `WECHAT_DEV_OPENID`，并配置真实的 `WECHAT_APP_ID`、`WECHAT_APP_SECRET`。

## 小程序配置

1. `config.js` 按 `envVersion` 自动切换环境：开发者工具（develop）连接 `DEV_API_BASE_URL`（默认 `http://127.0.0.1:8010`）联调真实解析接口；体验版/正式版连接 `PROD_API_BASE_URL`。
2. 仅当运行环境是开发者工具且 API 为本机回环地址时，才会使用 `.env` 中的 `WECHAT_DEV_OPENID`；真机不会启用开发登录。
3. 生产 API 域名已设为 `https://wx-api.tanzeng.xyz`（主域名备案的子域名，无需单独备案）。微信公众平台需把该域名加入 request 与 uploadFile 合法域名（HTTPS、443、精确匹配、不带路径）。
4. `WECHAT_APP_SECRET` 只能放在服务端 `.env`，绝不能写入小程序。
5. 小程序使用相册/摄像头与微信文件选择，需在微信公众平台《用户隐私保护指引》中声明对应收集行为后，相关接口才可用；`app.json` 已开启 `__usePrivacyCheck__`，便于在开发者工具中验证隐私弹窗。
6. 课表导入仅接受 Excel（xlsx/xlsm/xls）：教务系统导出的学期课表数据最完整，可避免 PDF 分页/周视图导出导致的课程缺失。调课通知图片识别不受影响（走视觉模型 API）。
7. Excel 导入支持 OpenAI 兼容 AI 解析：在 `server/.env` 同时配置 `AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL` 后启用。发送内容为工作簿单元格坐标与文本；未配置、超时或输出无效时自动回退本地解析。
8. 调课通知图片识别：调课中心提供「课程图片识别调课」入口，上传通知截图后由视觉模型（`VISION_BASE_URL`/`VISION_API_KEY`/`VISION_MODEL`，缺省回退 AI_* 三项）提取“调整前/调整后”并自动匹配课程，勾选确认后批量应用，应用前会做时段冲突校验。
9. 文件名含 `2025-2026-1` 之类的学期串时，导入弹窗会自动推测开学日期与结束日期。
10. 课表页支持下拉刷新（scroll-view refresher）；最近一次完整课表会缓存到本地，断网时自动兜底展示；JS 异常与未处理的 Promise 拒绝会写入微信实时日志，便于上线后排障。

## 与母版项目的移植对照

`ClassSchedule`（FastAPI + Vue + Android）为唯一母版。本仓库完成的移植：

- 登录：邮箱账号体系替换为 `wx.login` 静默登录（`/api/auth/wechat`），按 openid 隔离数据。
- 课表：学期切换（含进行中/未开学/往期状态与课程统计）、周导航（‹ › 步进、周面板、回到本周）、连堂课合并显示、10–12 节动态网格、按课名 16 色自动配色、今日高亮。
- 课程：添加/编辑/删除，编辑器支持 12 节次与 17 色课程颜色，编辑已调课课程时自动撤销该周调课。
- 调课：长按课程进入移动模式，点按目标格确认（2 节制对齐 + 冲突检测），移动仅调整单周（整学期固定时间用「编辑课程」修改）；单周调课弹窗支持撤销；详情弹窗展示本课程修改记录并可恢复/撤销/删除。
- 调课中心：变更记录列表（图片调课/位置移动/主动编辑）、批量记录展开逐条撤销、记录删除，以及调课通知图片 AI 识别与应用。
- 导入：微信文件选择，仅接受 XLSX / XLSM / XLS（教务系统导出的整学期课表），AI 解析优先、失败回退本地解析（表头探测/列映射/连堂合并），文件名推测学期日期，候选课程校对流程，导入进度分段计时提示。PDF/图片导入能力在服务端保留但产品入口已收敛，避免分页/周视图导出导致的课程缺失。
- 安全与工程：上传大小上限与 zip 炸弹/格式伪装校验、登录限流、数据库连接池、请求结构化日志、生产配置校验；alembic 迁移基线、pytest 单元测试（tests/）、ruff、Dockerfile/compose、GitHub Actions CI（`node scripts/check_wxml.js` 为小程序侧静态检查）。
- 服务端端点与母版对齐：schedules/courses/adjustments（含 `/api/adjustments/parse`、apply 冲突校验、`source=drag` 整学期移动）/import/health//api/live。
- AI 解析默认模型 `qwen3.8-flash`（端点实测优于 qwen3.7-flash，可用 `server/scripts/ab_parse.py` 复测）。
- 微信 Agent：独立 Python iLink Worker 直连腾讯 ClawBot，扫码取得的凭证加密入库；不依赖 OpenClaw。普通微信与兼容保留的企业微信渠道共用同一套绑定、会话和课表 Agent。

未移植项（平台专属或已被平台能力替代）：Android APK 更新（UpdateModal/downloads）、邮箱注册登录、视频壁纸与流光气泡（以自定义相册背景替代）、开屏 Splash、退出登录（微信静默登录）。

## 服务端自测

```bash
cd server
venv/Scripts/python -m pytest     # 离线单元测试
venv/Scripts/python scripts/api_e2e.py    # 调课/导入 API，需要本地 PostgreSQL 与运行中的 uvicorn
venv/Scripts/python scripts/local_e2e.py  # 企业微信回调链路，需要本地 PostgreSQL 与运行中的 uvicorn
```

两个 E2E 脚本都是会写入并清理专用测试数据的手工验收工具，不由 pytest 自动收集。

## 生产启动

推荐使用 Docker Compose：

```bash
cd server/deploy
cp .env.example .env
# 编辑 .env，填写 DB_PASSWORD、WECHAT_APP_ID、WECHAT_APP_SECRET 和 WEIXIN_ILINK_CREDENTIAL_KEY
docker compose build
docker compose up -d
docker compose ps
```

`server/deploy/.env` 已被 Git 忽略。`WEIXIN_ILINK_CREDENTIAL_KEY` 可用 `openssl rand -base64 32` 生成，投入使用后必须固定并备份；更换它会导致已保存的 ClawBot 凭证无法解密。Compose 会把可选的 `AI_*`/`VISION_*` 配置传入 API 和 Worker；未配置 AI 时课表 Agent 仍可使用确定性意图规则。

ClawBot 登录凭证、长轮询 cursor 和消息幂等状态保存在 PostgreSQL。用户在小程序「AI 助手」中点击“生成连接二维码”，长按识别并确认后会自动保存凭证、绑定当前课表账号；不需要登录服务器执行扫码命令。`weixin-worker` 会自动发现新账号，并为每个账号启动独立轮询。当前 MVP 接收文字与已有语音转写文本，回复文字；图片、视频和文件协议留待后续版本。

不使用容器时：

```bash
cd server
APP_ENV=production venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

使用 Nginx 将 HTTPS 域名反向代理到 `127.0.0.1:8010`。数据库建议使用独立的 `wx_class_schedule` 库和非超级用户账号。
启动后必须先确认 `curl https://wx-api.tanzeng.xyz/api/live` 返回 `{"ok":true}`；Nginx 的 HTML 404 表示站点配置尚未命中，不能上传体验版或正式版。

## 生产运维

- `server/deploy/docker-compose.yml` 中 db / db-backup / api / weixin-worker 均配置 `restart: unless-stopped`，宿主机重启后自动拉起。
- 数据库定时备份由 `db-backup` 服务完成：容器启动时立即全量备份一次，之后每 24 小时一次；备份写入 `server/deploy/backups/wx_日期.dump`（自定义格式，先写 `.tmp` 再改名），自动清理 14 天前的旧备份。
- 手动立即备份：进入 `server/deploy` 目录执行 `docker compose exec db pg_dump -U wx_schedule -Fc wx_class_schedule > backups/manual.dump`（bash）。
- 恢复：`cd server && python scripts/backup_database.py restore ../deploy/backups/wx_2026-09-12.dump`（依赖 `.env` 的 `DATABASE_URL` 与宿主机 5432 端口）。
- 备份目录已在 `.gitignore` 中排除，建议另行将 `server/deploy/backups/` 同步到异地存储。

### 域名与 HTTPS（wx-api.tanzeng.xyz）

1. DNS：在域名服务商为 `wx-api.tanzeng.xyz` 添加 A 记录指向云服务器公网 IP（子域名复用主域名 `tanzeng.xyz` 的备案）。
2. 证书与反代：按 `server/deploy/nginx-api.conf.example` 头部注释操作——certbot 签发证书后拷贝为 `/etc/nginx/conf.d/wx-api.tanzeng.xyz.conf`，`nginx -t && nginx -s reload`。反代到 `127.0.0.1:8010`，`client_max_body_size 12m`（大于服务端 10MB 上传上限），超时 180s（大于小程序 uploadFile 的 120s）。
3. 验证：`curl https://wx-api.tanzeng.xyz/api/live` 返回 `{"ok":true}` 即通。
