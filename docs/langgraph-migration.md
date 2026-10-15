# Agent 查询编排迁移与回退

## 当前阶段

稳定基线是 c5a7256，GitHub 回退标签 pre-langgraph-20261014。第一阶段只增加可选的 LangGraph 查询图，AGENT_ENGINE 默认 legacy。同步提交、状态回复、后台同步任务、通知订阅/投递、Redis 会话历史及 Pydantic 课程渲染均不迁移。不新增数据库迁移或 checkpoint。

图节点：initialize → model → tools → model；无工具调用时 model → validate → 输出；异常/截断/预算或轮次耗尽 → recover → 已校验课程事实或 None，再交现有确定性兜底。

保留 loop._run 作为旧引擎参考实现。graph.py 复用 loop 的模型 HTTP 调用、技能注册/执行、事实校验、上下文提取和 course_reply 渲染器。新旧编排代码暂时并存，后续协议变更必须跑两套测试，避免漂移。

每轮最多 4 次模型调用，图步数单独限制为 3*MAX_ROUNDS+5。图中不设置自动重试；失败不重跑旧模型循环，不会重复发起同步。继承同一个 ContextVar 时间预算，数据库和渠道 I/O 仍不是可硬中断的总请求时限。

每次请求创建独立运行上下文和编译图，状态只含消息、事实、轮次数、模型回复和最终结果。工具实例、数据库连接及密钥只在该次调用的上下文里，不进入图状态；不配置 checkpointer/store，禁用该图的 LangSmith tracing，不上传会话及工具事实。工具并行仍使用原线程池和 copy_context，按调用顺序收集结果。

## 依赖与安装

默认 requirements.txt 保留 langchain-core==0.3.86；requirements-common.txt 只提取未变更的公共依赖。候选图环境使用单独的 requirements-langgraph.txt：langgraph==1.2.15、langchain-core==1.4.7、checkpoint==4.3.0、prebuilt==1.1.0、sdk==0.4.6。不要在同一次 pip 命令中同时安装两套互斥的 core 版本。

此前兼容组合 0.6.11 / core 0.3.86 已验证可运行，但未作为最终依赖。图环境升级 core 消息/提示抽象，模型 HTTP 协议、供应商参数和配置读取仍保持原实现；必须在候选环境重新跑完整回归，而不是把旧环境结果当作候选验证。默认镜像继续安装旧依赖，INSTALL_LANGGRAPH=true 才选择候选依赖。

本地安装：

```powershell
python -m venv tmp/langgraph-venv
tmp/langgraph-venv/Scripts/python.exe -m pip install -r server/requirements-langgraph.txt pytest==8.4.2
$env:AGENT_ENGINE='langgraph'
tmp/langgraph-venv/Scripts/python.exe -m pytest server/tests -q -p no:cacheprovider
```

设置 AGENT_ENGINE=legacy 可立即使用原编排；未知值失败关闭，进入确定性兜底，不擅自切换模型引擎。

## 对比验证与上线条件

现有 Agent 离线 CI 增加 legacy/langgraph 矩阵；test_agent_graph.py 用相同模拟模型序列对比请求内容、工具参数/顺序、答案、上下文与熔断结果，另测并发隔离、无配置、预算、图基础设施异常和不导出追踪。

本地完整回归需对两种引擎分别运行。模拟模型回放不代表真实模型准确率。真实模型联调只允许使用虚构课表，明确启用后才调用，不能把测试导向生产学校接口或真实微信投递。不在线上同时运行两套引擎，避免双倍调用或副作用。

正式切换前还需要：复核选定依赖的安全情况；确认生产 Python 3.12 / Linux 候选镜像回归结果；虚构数据真实模型联调；确认成本、延迟、模板回退和通知成功率没有回归。

## 本次验证记录

2026-10-15：候选独立环境中，legacy 与 langgraph 分别完整回归，各 697 passed、41 skipped；跳过项包含未安装的可选依赖及外部服务测试。Linux / Python 3.12 隔离网络容器中，LangGraph 关键回归 198 passed。没有执行真实模型、学校接口或微信投递联调，也没有变更生产服务。

## 部署与回退操作

Dockerfile 支持可选 INSTALL_LANGGRAPH，默认 false，普通构建及现有服务均保持 legacy。

```bash
# 只构建候选镜像，尚不切换默认引擎。
docker compose build --build-arg INSTALL_LANGGRAPH=true api weixin-worker
```

Compose 已向 API 与微信 worker 传递 AGENT_ENGINE=${AGENT_ENGINE:-legacy}。只有候选镜像和联调通过后，才把生产 .env 里的 AGENT_ENGINE 改为 langgraph 并重建这两个服务；先备份环境配置和原镜像。

出现问题时，设置 AGENT_ENGINE=legacy，再执行 docker compose up -d --no-build api weixin-worker。无需数据库降级；需要整包回退时使用保存的原镜像或 pre-langgraph-20261014 标签。

本阶段不启用同步完成后恢复查询、不引入持久化执行状态、不改变小程序，也不自动部署线上。

官方参考：
- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://pypi.org/pypi/langgraph/1.2.15/json
- https://pypi.org/pypi/langgraph/0.6.11/json
