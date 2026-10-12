# 序时 Agent 评测工作台

## 已完成
30 条固定问法覆盖日期、周查询、简称、下一节课、组合天气查询、历史追问、空课表、缺课表、日期越界及身份注入。
使用真实 ScheduleTools / schedule_query，在内存模拟数据库内保存虚构课程；天气固定为降雨概率 80%。无需生产数据库、Redis、微信连接。
固定时间：2026-09-08 13:00 +08:00。
- 周二上午：大学英语，李明，B202。
- 周三下午：高等数学，张华，A101；计算机组成原理，王林，C303。
- 周五上午：大学体育，赵青，操场。

## 命令
在 server 下：
```powershell
venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_agent_optimizations.py tests/test_agent_conversation.py tests/test_bot_concurrency_hardening.py tests/test_intent_corpus.py tests/test_evaluation_contracts.py -q -p no:cacheprovider
venv\Scripts\python.exe -m scripts.evaluate_agent
```
默认只校验语料，不调用模型。
真实评测显式加 --live，使用 AGENT_BASE_URL / AGENT_API_KEY / AGENT_MODEL；只读取环境配置，不读取管理后台的模型密钥。
```powershell
venv\Scripts\python.exe -m scripts.evaluate_agent --live --limit 3
venv\Scripts\python.exe -m scripts.evaluate_agent --live
```
会把评测问法、虚构课表和 seeded 对话历史发送给模型供应商，产生调用费用。不会发送微信消息或使用用户真实课表。

## 报告
evals/reports/agent.json：实际工具名、参数和返回事实、整轮耗时、各模型请求耗时及 usage、工具契约匹配、关键词覆盖。每完成一例保存。
没有流式输出，因此 first_token_ms 为 null；不能把整轮响应耗时当首字时间。cost 为 null：未提供供应商价格。
工具契约允许部分合法工具组合，但仍可能对合理路径判得偏严，失败后应先检查 trace。词语命中并不是事实准确率，需人工核对课程、教师、教室、日期及未授权身份声明。
历史案例使用固定历史，不是完整多轮产品会话；Redis 保存与渠道身份隔离由已有离线测试独立覆盖。

## 边界
此脚本测 Agent 主循环，不测实际微信投递、扫码登录或跨批次消息顺序。现有测试覆盖工具错误、轮次耗尽、虚构时间拒绝、熔断探测、连接池以及批次内同用户串行和不同用户并行。
不要将批次内串行表述成跨所有账号/进程的同用户全局顺序保证。
当前时间校验只检查时间字符及内部标记，并不能保证课程名、教师、教室完全来自工具。真实评测发现此类错误时，应扩大事实验证或回退到确定性表达。
新增 .github/workflows/agent-evaluation.yml 会跑上述离线测试及默认语料检查；没有推送或触发远程 CI。
真实模型评测尚未执行，不生成虚构准确率或延迟。

## 下一轮优化
按失败数量排序：简称定位 → 日期/历史继承 → 不必要的工具调用 → 工具返回后事实误写。一次只修一个主要问题，同一模型、温度和案例集复测。
模型调用使用全局并发信号量，但线程等待信号量的时间尚不受请求总预算限制；最多4轮也不等于端到端最大时长。先观察，再决定是否增加整轮时间预算。
