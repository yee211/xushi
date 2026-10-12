# 学校同步与恢复

学校同步仍采用一份权威学校课表的规则。覆盖课程、删除其他课表之前，服务端在同一数据库事务中保存完整快照，包括课表、课程、单周调课、修改记录和关联 ID。备份失败会使同步回滚，不会继续覆盖。

每个账号保留最近 5 次快照。学校数据和本地数据均未变化、且没有其他待删除课表时，不新增快照。恢复时也先备份当前课表，支持撤回恢复。正在排队或执行学校同步时不能恢复。

网页端、Android 的学校身份弹窗和小程序的学校身份页面提供恢复入口。恢复后未来的自动同步仍会更新学校课表；希望保留恢复内容时，可解除学校绑定。

接口均要求用户登录，只能访问当前账号的记录：

- `GET /api/academic/backups`：最近 5 次快照的 ID、时间和课表数量。
- `POST /api/academic/backups/{backup_id}/restore`：事务恢复，返回 `schedule_id` 和 `restored`。

数据库表通过启动时 `init_db()` 创建，也提供 Alembic 迁移 `0014_schedule_backups`。

前端请求默认 30 秒超时，学校查询和课表导入为 75 秒；超时包含读取响应内容。写操作超时后应刷新确认结果，避免重复提交。

恢复集成测试使用独立临时 PostgreSQL schema，模拟学校数据，不请求学校服务。连接可用后在 PowerShell 执行：

```powershell
cd server
$env:TEST_ACADEMIC_QUEUE_DB = '1'
venv/Scripts/python -m pytest tests/test_schedule_backups.py tests/test_academic_jobs.py -q
```


## 同步执行预算与恢复

每次执行预算 90 秒，学校查询总预算最多 60 秒，单个 HTTP 操作最多 20 秒；
学校响应即使持续小量传输也受剩余总时限约束。数据库连接等待按剩余预算限制，
写入事务的锁等待最多 15 秒；预算耗尽会取消活动 SQL，并在提交前检查及回滚。
预算不包含队列等待，解析等同步计算仍在阶段边界检查，不能将 90 秒视为进程强杀时间。

任务公开 querying、writing、retrying、completed 等阶段和 started_at，方便查看进度。
临时超时仍最多执行三次，重试间隔 20、40 秒；重启恢复也遵守三次尝试上限。
恢复 running 任务前必须先取得 PostgreSQL 执行器锁，避免与仍在执行的任务同时写入。
新增字段由迁移 0017_sync_progress 和幂等初始化创建。
