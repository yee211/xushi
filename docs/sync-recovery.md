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
