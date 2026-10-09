# 2.4.8 发布准备（2026-10-09）

版本：2.4.8，versionCode：30。包名保持 io.github.yee211.classschedule。
上传包为 tmp/release-2.4.8/xushi-server-2.4.8.tar.gz，根目录是项目目录布局。
包含服务端源码、管理后台、迁移、前端源码与构建结果、正式 APK、部署配置。
不包含生产 .env、数据库、学校登录凭证、签名密钥、node_modules 或本机虚拟环境。
新版本通知文件在上传包的 release/app_version.json 中，最后才启用。

## 云服务器更新顺序

以下按现有目录 /www/wwwroot/ClassSchedule 和 Docker Compose 部署编写。
如实际目录不同，只调整项目路径；保留服务器现有 server/deploy/.env。
不要执行 docker compose down -v，不要用本机数据目录覆盖线上 data。

1. 在上传包覆盖源码之前备份原有项目源码、frontend/dist、static/downloads、data 和生产 .env，备份放项目目录外。
   备份不要包含巨大的 node_modules 或容器数据库卷。保存当前 Git 提交和 API/worker 镜像 ID以备回退。
2. 上传 tar.gz 到服务器，在项目根解压；解压不会写入 .env、data 或在线版本通知文件。
3. 检查 server/deploy/.env 保留原来的密钥和数据库密码。
   学校目录和同步默认启用；如果线上使用管理后台浏览器维护学校登录，设置 INSTALL_ACADEMIC_BROWSER=true。
   保持原有学校凭证加密用的 ADMIN_SESSION_SECRET，不能重新生成，否则旧学校连接无法解密。
4. 构建完成之后停止写入、备份数据库、迁移并启动：

```bash
set -e
cd /www/wwwroot/ClassSchedule/server/deploy
docker compose config --quiet
docker compose build api weixin-worker
docker compose stop api weixin-worker
mkdir -p backups
backup_file="backups/pre_2.4.8_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T db pg_dump -U xushi -Fc xushi_schedule > "$backup_file"
test -s "$backup_file"
docker compose run --rm --no-deps api alembic upgrade head
docker compose up -d api weixin-worker db-backup
```

本次迁移最终应到 0015_academic_directory。
API 启动也会执行迁移；迁移失败会阻止启动。失败时不要继续启用新版通知。
Compose 将宿主机 frontend/dist 挂载进容器，本上传包已经带最新 dist；
若改用 git pull 更新源码，需要同时更新 dist，单纯 docker build 不会替换挂载目录。
构建下载慢时再选择可用国内镜像；不要永久修改密钥或应用配置解决下载问题。

## 发布验收与启用 APK 通知

```bash
cd /www/wwwroot/ClassSchedule/server/deploy
docker compose ps
docker compose logs --tail=100 api weixin-worker
docker compose exec -T api alembic current
curl -fsS http://127.0.0.1:8010/api/live
curl -fsS https://api.tanzeng.xyz/api/live
curl -fsS https://wx-api.tanzeng.xyz/api/live
```

登录后检查学校身份、同步真实学校课表、开学/结束日期、当前周次、反馈提交。
在旧正式签名 App 上覆盖安装新版，确认登录状态和课表保留，并测试微信 ClawBot 查询课表。
检查 https://api.tanzeng.xyz/downloads/序时_v2.4.8.apk 可下载且 SHA-256 与 release/manifest.json 一致。
所有检查通过后，在项目根执行：

```bash
cd /www/wwwroot/ClassSchedule
cp release/app_version.json data/app_version.json
curl -fsS https://api.tanzeng.xyz/api/app/version
```

通知应为 versionName=2.4.8、versionCode=30，下载地址使用官方服务器。
本次只准备本地产物，没有推送 Git、创建 GitHub Release 或修改云服务器。

## 回退

通知启用后如有问题，先恢复旧 data/app_version.json，再恢复旧源码、网页产物、APK 和旧容器镜像。
不要直接执行 alembic downgrade；新增迁移通常可以由旧应用忽略，必要时验证后再回退。
数据库恢复会丢失备份之后的新数据，仅在必要时停写并确认恢复范围后操作。

## 已做验证

后端完整回归 501 项、前端 10 项、小程序 20 项通过；含隔离 PostgreSQL 的目录、队列与备份测试。
小程序 WXML 和 JS 语法检查通过；正式包另行校验签名、包名、版本与线上 API 地址。
真实学校接口及云服务器健康检查留到部署验收时执行。
