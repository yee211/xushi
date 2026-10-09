# 长沙工业学院学生课表接口调查与序时接入方案

调查日期：2026-10-08。通过用户已登录的浏览器会话、页面脚本与实际网络请求验证。
本次仅调查和设计，未修改业务代码，未保存 Cookie、登录令牌或全班名单。

## 1. 已验证的请求链路

域名：https://tls.ccsut.cn。以下请求必须在有效学校登录会话中执行。
当前账号经过统一身份认证与 zts 网关进入系统；服务器独立 HTTP 客户端可用性尚未验证。
观察到的页面行为不能证明接口对所有账号、角色开放。

| 方法 | 路径 | 参数 | 返回 / 用途 |
| --- | --- | --- | --- |
| GET | /admin/jwxtgld/kbcx/xskblist | 无 | 学生课表选择页；年级选项来自 HTML |
| POST | /admin/jwxtgld/xscx/getXssjYxxx | sznj, xm，表单编码 | 数组：院系 → 专业 → 班级 |
| POST | /admin/jwxtgld/xscx/getXsxx | sznj, xm，表单编码 | 页面脚本预期学生数组；本次按本人学号查询返回空数组 |
| GET | /admin/jwxtgld/kbcx/xsxxlist | sznj, yxid, zyid, bjid | 班级学生列表 HTML，非 JSON |
| GET | /admin/api/getKbxx | xqid, userId, xnxq, role=xs, showBtn=0 | 个人课表 HTML 入口，非课程 JSON |
| POST | /admin/api/getZclistByXnxq | xnxq, role=xs, userId, xqid | ret/msg/data，含周次、日期、节次时间、校区 |
| GET | /admin/api/getRqListByWeek | xnxq, week | 每周日期数组，可选辅助接口 |
| GET | /admin/api/getXskb | xnxq, userId, xqid, week, role=xs | ret/msg/data.kckbData，当前周课程安排 |

筛选字段含义：sznj 为入学年级；xm 为班级名称、学生学号或姓名搜索文本。
院系树字段：id/yxmc/zyxxList；专业字段：id/zymc/bjxxList；班级字段：id/bjmc/xqdm。
yxid、zyid、bjid 使用相应节点 id。
个人 userId 使用学生链接 data-id / URL 中的编码标识，不能用学号或自行拼接、猜测。
班级节点 encodeId 和个人编码标识不是同一个对象。

## 2. 学生姓名、学号和班级的来源

班级列表标题提供班级名称，每个 .xskb-link 提供：
- data-name：学生姓名；
- data-id：个人教务编码标识；
- data-xnxq：学年学期，如 2026-2027-1；
- 内部 .text-class：显示学号、性别和姓名。本次学号为 2024****0731 形式，已脱敏。

本次查看本人班级列表，包含 41 个学生链接，仅打开本人课表进行课程验证。
不能把显示学号当作完整学号，也不能从姓名、班级或编码标识反推出缺失位数。
getXsxx 的前端脚本引用 xm/xh/encodeId，但实际本人查询响应为空，尚未验证可取得完整 xh。
建议 student_number_display 与经本人确认的 student_number 分开存储。

课程里的 jxbzc 是教学班组成，可包含多个行政班，不能据此覆盖学生的行政班。
姓名、年级、院系、专业、行政班均来自选择上下文，个人编码标识来自学生链接。

## 3. 真实课程结构和完整学期

真实结构为：
```json
{
  "ret": 0,
  "msg": "",
  "data": {
    "kckbData": [
      {
        "xnxq": "2026-2027-1",
        "kcmc": "示例课程",
        "tmc": "示例教师",
        "croommc": "示例教室",
        "xingqi": 1,
        "djc": 1,
        "zcstr": "1,7,8,9,11,12",
        "zc": "1-1,7-9,11-12"
      }
    ]
  }
}
```

字段映射：kcmc → name；tmc → teacher；croommc → room；
xingqi → weekday；djc → 单节节次；zcstr → weeks；xnxq → term。
先按课程安排去重，再合并同星期、同教师、同教室、同周次的连续节次。
不要仅按课程名称或 id 去重：本人同一课程 id 在不同周出现不同教室和 pkid。

重要实测：
- 页面默认只取当前第 5 周，返回 20 条单节安排。
- 第 1、9 周分别返回 24 条安排，包含第 5 周未出现的安排。
- week 为空时 ret=0，但没有有效 data.kckbData，不能视为全学期。
- 按校历返回的 20 周逐周读取本人课表，共 348 条重复记录；
  以 pkid/jxbid/kcmc/tmc/croommc/xingqi/djc/zcstr 组合作为调查去重键得到 76 条、8 个课程名称。
- 76 是去重后的单节安排数量，尚未执行序时解析与连堂合并，不能作为最终落库课程数。
- 第 18 周有 20 条，第 17、19、20 周无记录；不能遇到空周就停止遍历。

实现应先请求 getZclistByXnxq，再遍历其 data.zclist，不硬编码 20 周。
成功但为空的周与请求失败必须区分；部分失败时不能把不完整数据标记为完整导入。
保留上游课程周次；需要核对补课/变更安排时，同时保留请求周次上下文。

本次校历：2026-2027-1，第 1 周起始 2026-09-07，第 20 周结束 2027-01-24。
data.jcsjszList 提供第 1–10 节上下课时间，data.xqList 提供校区选项。
日历返回周数和排课配置上限可能不同，应按实际校历遍历，并记录配置差异。

## 4. xushi 中可以复用的部分

- frontend/android/app/src/main/java/io/github/yee211/classschedule/AcademicWebviewPlugin.java：
  已有学校登录 WebView、XHR/fetch 嗅探和 AcademicBridge 导入桥接。
- frontend/src/App.vue：handleAcademicImport / importAcademicData 现有导入入口。
- frontend/src/api/index.js：现有 importerApi 客户端。
- server/app/routers/importer.py：POST /api/import-html、确定性解析和 AI 兜底。
- server/app/html_parser.py：parse_qiangzhi_json 已支持单节课表字段。
- server/app/parser.py：normalize_courses 已有周次规范化、去重、连续节次合并。
- server/app/services/schedule_import.py：write_schedule 提供事务落库和覆盖保护。
- server/app/db/schema.py：users 尚无学校学籍资料表。

## 5. 现有导入需要优先修正的地方

1. parse_qiangzhi_json 目前只识别 data 数组、courses/rows 数组和根数组；
   不识别真实的 data.kckbData，现有测试样本与本次接口结构存在差异。
2. WebView 目前优先返回最近捕获的响应，仅当前周，容易漏课。
3. 捕获缓存仅按 30 分钟时效复用，没有关联学生、学期、校区；
   切换学生或学期后可能导入旧响应。应按这些维度隔离并失效。
4. import-html 根据学期文字估算起止日期；新接口可提供真实校历，
   应显式传 start_date/end_date，并校验，不复用上一份课表日期。
5. import-html 当前固定 overwrite=True；新增直连应支持预览和确认覆盖，
   防止学校同步清除已有调课版本。
6. normalize_courses 的去重键没有 teacher/room；
   若合并来自不同来源的原始安排，应先检查同名同节同周不同地点是否冲突，
   避免静默吞掉冲突数据。

## 6. 用户确认的产品方向：共享教务会话查询模块

用户希望增加独立“查同学课表”模块：由后台维护管理员自己的学校登录会话，
其他序时用户按姓名/班级选择学生并查看课表，无需各自登录教务。
该模块应与“导入我的课表”区分；查看他人课表不自动绑定学校身份或覆盖个人课表。

追加验证：
- 当前学校账号查询 2024 年级，返回 5 个学院、62 个班级，报告总学生数 2454。
  这证明当前会话有较广目录访问范围，不证明所有年级/学生均可查。
- 本人班级目录含 41 个学生，均显示脱敏学号。
- 从正常班级列表选择另一名学生，查询其第 5 周课表 ret=0、返回 20 条。
  未尝试猜测或构造个人标识，未验证其他学生的全学期课表。
- 尚未验证全校、其他年级、历史学期和转专业/休学学生的覆盖情况。

建议架构：
1. 受管理后台鉴权保护的教务连接管理：管理员登录、连接状态、到期重登。
2. 独立学校目录：年级、院系、专业、班级、学生编码标识、姓名和显示学号。
   学生编码跨会话稳定性需验证；目录缓存有更新时间，不凭姓名唯一匹配。
3. 序时鉴权保护的查询接口：输入姓名和可选班级，同名学生返回候选列表，
   用户选择具体学生及学期后查询。使用源编码标识定位课表。
4. 后台逐周抓取、校验、去重、标准化，返回只读课程与校历。
5. 以学校/学生标识/学期/校区为缓存键，给出同步时间、覆盖周数与失败周。
   共享只读课表缓存独立于 schedules，不能写入管理员个人课表。
6. 用户明确选择“导入我的课表”时才调用既有 write_schedule 路径。

候选 API 契约（尚未实现）：
- GET /api/academic/students?name=...&class_name=...&grade=...
- GET /api/academic/students/{source_student_id}/schedule?term=...
- GET /api/admin/academic/connection
- POST /api/admin/academic/refresh-directory

不能直接假定复制 Cookie 后 httpx 能访问。
当前学校登录含 zts 网关，需先验证后端独立会话能力：
- 若普通 HTTP 客户端可用：后台专用客户端 + 会话管理；
- 若请求绑定浏览器或网关脚本：服务端独立浏览器会话 / 受控采集进程；
- 本次 MCP 的本机浏览器仅供调查，不是生产系统运行依赖。
连接状态失效时返回明确状态，保留旧缓存及其同步时间，不返回伪装为空课表的数据。

## 7. 数据完整性指标

需要把“接口成功”“学生目录完整”“学期课表完整”分别记录：
- 目录：每个班级报告人数、解析人数、学生标识去重人数及差异；
- 目录范围：年级/学院/专业/班级覆盖，异常或无权限节点；
- 学期：可用学期来自页面实际列表，未发布学期不能视为空课表；
- 课程：期望周次来自校历，成功周、有效空周、失败周分别保存；
- 完整性：仅所有期望周正常返回且结构有效时 complete=true；
- 刷新：部分请求失败时保留上一份完整快照，显示本次失败和最后成功同步时间；
- 校验：任意抽选学生，比较第 1、中间和末尾有课周与学校页面。
目录人数不能代替课表完整性，也不能凭一个学生的成功结果保证全校可用。
展示“已覆盖 20/20 周”比承诺“全校所有数据完整”更准确。

建议同步完整性返回字段：
```json
{
  "complete": false,
  "expected_weeks": [1, 2, 3],
  "completed_weeks": [1, 2],
  "failed_weeks": [3],
  "fetched_at": "<同步时间>",
  "last_complete_at": "<上次完整同步时间>"
}
```
样例仅展示格式，实际使用真实校历全部周次。
请求失败、返回登录 HTML、业务 ret 非零、未知结构均不可算成功空周。
查询接口限制返回必要的姓名、班级、显示学号、课程资料；
不把管理员学校会话材料发送到普通用户客户端。

## 8. 实施与验证顺序

先验证生产后端可维持的学校会话方式，再实现目录与单个学生完整学期查询，
最后接前端选择器与同步刷新。暂不一次抓取全校所有人的全部历史学期。
查询时按需缓存，目录可定期刷新；目录全量快照必须核对各班人数差异。

后续验证：
- 真实 data.kckbData、空周、失败周、业务错误、登录页重定向和错误响应结构的离线测试；
- 同名学生、同名班级、跨年级查询、名单人数差异与缓存失效；
- 单人完整学期、不同教室与重复单节、连堂合并及第 18 周记录；
- 学校登录续期、断线重登、后端重启后状态、共享查询并发去重；
- 网页/小程序查询结果只读与序时鉴权，管理员连接管理单独鉴权；
- 数据只包含源页面已授权返回的记录，完整学号仍为未验证能力。

本次仅完成调查与方案文档，尚未实现或部署共享查询模块。


## 9. 追加发现：整学期报表入口（优先方案）

2026-10-08 继续调查“下载”按钮，验证存在整学期报表：
- GET /admin/pkgl/xskb/report：参数 id=<学生编码标识>、xnxq=<学期>、ydd=1、mbzc=空、from=1。
- GET /admin/pkgl/xskb/getReportUrl：相同参数，返回 ret/msg/data.url；地址含临时签名，不保存、不硬编码。
- report 入口进入 /report/reportJsp/showReport.jsp，显示整学期 HTML 矩阵，并提供 Excel/PDF/Word 导出。

本人报表同时显示第 1–16 周安排与第 18 周课程设计，证明无需逐周请求即可取得跨周的学期报表。
尚未逐项与 76 条单节 JSON 安排做完全一致性核对；报表还有实践环节备注，应单独处理。
getXskb 的 week=1-20 和逗号列表测试均请求失败，不应使用这些未经支持的范围参数。

修订推荐：优先请求整学期报表并确定性解析，使用逐周 JSON 查询核对或兜底。
“一个学生一次获取整学期”在业务上可行，但报表导航本身可能包含重定向和多次 HTTP 请求，
不能等同于一个返回全部原生课程 JSON 的接口。现有 parse_html_schedule 可作为起点，
需要专门验证报表 rowspan、自动折行课程名、单双周、地点变化与实践备注。
导出格式和字段完整性尚未验证。服务器学校会话可用性仍需验证。
