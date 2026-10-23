# 小程序他人课表（第一版）

首页课表顶部切换“我的课表 / 他人课表”。他人栏可搜索、预览、保存多人、切换人员、选择学期、填写备注、手动更新和移除收藏。默认启动进入我的课表。

收藏跟账号存储于独立的 academic_others 表，以 user_id + student_id 去重；每人保留一个当前选中的学期快照，切换学期后可重新保存。预览不写收藏。他人课表只读，不进入 schedules、身份绑定、学校同步覆盖、恢复备份和助手默认课表选择逻辑。学校查询不完整或过期时拒绝覆盖收藏。

接口均需要登录：

- GET /api/academic/others：当前账号收藏及快照。
- GET /api/academic/students/{student_id}/schedule?term=...&refresh=true：独立查询/预览。
- PUT /api/academic/others：student_id、term、remark，更新此人收藏。
- DELETE /api/academic/others/{student_id}：只移除当前账号对此人的收藏。

数据库通过 Alembic 0023_academic_others 升级；启动建表路径也已补齐。部署需要同步更新后端与小程序。收藏列表本地缓存与当前登录会话匹配后才可离线回显；更换登录会话时重新从服务端获取。

验证：node --test miniapp/tests/*.test.cjs；node miniapp/scripts/check_wxml.js；在 server 下运行 python -m pytest tests/test_academic_others.py tests/test_academic_binding.py。

尚需在微信开发者工具和真实学校连接下进行真机查询联调。第一版不提供多人课表叠加、对比或自动后台同步。
