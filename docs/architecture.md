# 序时架构与运行链路

## 应用边界

- frontend：Vue 界面、统一 API 客户端；Capacitor Android 复用 Vue，原生插件负责教务 WebView、账号保存。
- miniapp：微信小程序独立界面；app.js 统一登录、请求、上传与 401 重试。
- server/admin：独立静态管理后台。
- server/app/routers：HTTP 参数、鉴权与响应；services：共享业务与事务；agent：理解、工具调用与回答；channels：微信消息传输。
- 普通浏览器默认宣传页，/?mode=app 或 /?preview=app 进入课表界面。

## 身份边界

网页和 Android 使用 JWT；小程序使用 sessions 中可撤销的随机令牌。统一鉴权最终得到 user_id。
账号关联将小程序会话和数据并入邮箱账号。聊天渠道绑定将发送者关联到 user_id。
学校绑定将 user_id 关联到学生目录，供课表同步使用，不是学校身份认证。
学校身份冲突需用户选择保留哪端；合并操作包含对应课表和队列处理。

## 课表链路

客户端 → /api/schedules → Redis 用户缓存 → PostgreSQL 批量读取课表、课程和单周调课。
基础关系为 users → schedules → courses → course_adjustments / course_change_logs。
现有课表类型包含 original、adjusted、draft；当前允许原表直接编辑，同时保留历史调课版机制。
课程碰撞规则集中在 services/course_rules.py；导入落库集中在 services/schedule_import.py。
Excel 优先 AI、失败回退本地解析；教务 HTML 优先确定性解析、失败回退 AI。
图片调课先识别与匹配，再经用户确认落库。未接入客户端的课表分享码功能已移除。

## 学校链路

管理员维护学校登录 → 加密本地会话 → CcsutClient → 学校 HTTP 接口。
目录刷新：PostgreSQL 保存请求 → API 内采集线程 → 按年级逐班读取 → 事务替换完整目录。
完整目录成功同步后，搜索走本地 PostgreSQL；首次同步前回退学校实时搜索。
学生上下文优先完整目录，其次内存中的绑定或搜索上下文，最后 SQLite 历史快照。
绑定保存学生 JSON 快照；目录刷新不会自动改写已绑定账号的 JSON。
课表同步：绑定 → 数据库队列 → 单执行器 → 学校查询 → 完整性与绑定版本校验 → 备份 → 事务覆盖 → 缓存失效。
每天北京时间零点生成已绑定账号同步任务；目录当前由管理员手动刷新。
学校同步成功后只保留一个学校主课表，其他课表和调课会被清理；失败保留原数据。
最近保留 5 次恢复快照。学校请求限流使用共享 Redis；多进程部署应配置统一 Redis。

## 助手链路

微信 iLink 独立 Worker 或企业微信回调 → 渠道身份 → user_id → ScheduleTools → 数据库课程事实 → 回答。
模型工具调用循环优先；不可用时回退意图和模板路径。教学周与节次由 schedule_query.py 计算。
Redis 保存用户和渠道隔离的对话历史。微信 Worker 同时执行早间课表、天气推送。

## 运行与存储

API 启动：配置校验 → 连接池 → 幂等建表 → 学校同步与目录线程 → HTTP 服务。
Compose 运行 api、weixin-worker、db、redis、db-backup。学校工作线程通过 PostgreSQL 锁协调。
PostgreSQL 保存业务和任务；Redis 保存缓存、对话和限流；SQLite 保存学校历史查询；文件保存加密会话和浏览器资料。
服务端运行数据仍在 server/data；发版资源使用统一 paths.py：本地仓库根 data、static、frontend/dist，容器 /app 对应目录。
特殊部署可通过 XUSHI_ASSET_ROOT 指定发版资源根目录。
/api/live 为进程探针；/api/health 同时验证数据库。
Docker 启动先执行 Alembic，失败会阻止启动；init_db 继续承担幂等建表和旧库兼容。

## 浏览器登录维护部署

默认镜像不含 Playwright。需要学校浏览器维护时，在 server/deploy/.env 设置 INSTALL_ACADEMIC_BROWSER=true，
再执行 docker compose build api 和 docker compose up -d api。构建安装 Playwright、Chromium 与系统依赖。
已有 Cookie 的 HTTP 查询与浏览器维护分别使用不同依赖；镜像构建不会发起学校登录。
ACADEMIC_DIRECTORY_WORKER_ENABLED 和 ACADEMIC_SYNC_WORKER_ENABLED 控制 API 内对应采集器。
至少一个 API 实例需要启用相应工作线程才能处理任务。

## 后续拆分边界

App.vue 的确认弹窗状态已移至 composables/useConfirmation.js；后续可按登录、导入、课程编辑拆分，避免一次移动全部流程。
课程与图片调课路由仍保留部分事务业务，可继续迁到 services，保持权限检查、锁顺序和响应兼容。
学校绑定快照和完整目录的字段更新策略仍需按业务明确；目前优先目录读取，不自动重绑或改写绑定快照。

## 已移除的旧功能

已删除调课版派生 HTTP 入口、分享码路由与服务、演示课表入口、小程序旧编辑页、
学校年级独立查询与同学课表直接查询入口、学校直接同步入口，以及未接入的 /api/config。
现有课表编辑、Excel/HTML 导入、图片调课、账号关联、学校绑定、同步队列和恢复备份保留。
旧数据库迁移不改写；旧分享码表不再被运行时代码使用，也不主动删除已有数据库数据。
调课类型字段和历史课表读取兼容保留，不再提供派生接口。

旧 editor 页面仅保留不注册的重定向占位文件，供开发者工具旧文件索引读取；两套项目配置都从上传包排除此目录，不恢复编辑功能。
