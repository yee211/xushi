# 普通微信 ClawBot（iLink）直连方案

## 运行链路

```text
微信 ClawBot
  → 腾讯 ilinkai.weixin.qq.com
  → app.channels.weixin.worker（独立单副本进程）
  → app.agent.service.build_agent_reply
  → ScheduleTools / PostgreSQL / Redis
  → iLink sendMessage
```

本实现只使用腾讯仓库公开的 HTTPS/JSON 协议，不加载 OpenClaw 包，也不运行 OpenClaw Gateway。
企业微信回调仍可使用，但主绑定 provider 已改为 `weixin_ilink`。

## 用户连接

1. 生成并永久保存凭证加密密钥：`openssl rand -base64 32`。
2. 将结果写入 `WEIXIN_ILINK_CREDENTIAL_KEY`。
3. 部署 API 与 `weixin-worker`。
4. 用户在小程序「AI 助手」页面点击“生成连接二维码”，长按识别并确认。
5. 后端自动保存 ClawBot 凭证，并将扫码微信身份绑定到当前小程序用户。

Docker 部署对应命令：

```bash
docker compose build
docker compose up -d
```

扫码返回的 `bot_token` 使用 AES-256-GCM 加密后写入 `channel_accounts`。加密密钥只通过环境变量提供，
不能提交到仓库，也不能在已有账号仍需使用时随意轮换。

## 消息语义与并发控制

- `get_updates_buf` 每次成功处理整批消息后持久化；处理失败时不推进 cursor。
- **批次并发与保序**：同批次消息中，**不同用户（`sender_id` 不同）**提交全局线程池（`WEIXIN_WORKER_CONCURRENCY`）并行消费，消除大模型调用排队延迟；**相同用户**严格按入站顺序串行处理，确保多轮会话上下文与回复先后顺序正确。
- **数据库连接池**：支持通过 `DB_POOL_MIN_SIZE` 与 `DB_POOL_MAX_SIZE` 动态伸缩（默认 30），匹配并发 Worker 处理吞吐。
- 入站消息以 `account_id + message_id` 幂等。
- 回复 `client_id` 由账号和消息 ID 稳定生成，降低进程在发送后、落库前崩溃造成重复回复的概率。
- 回复必须携带入站 `context_token`；缺失时记录失败，不进行不可靠发送。
- `ret/errcode = -14` 按腾讯客户端行为暂停账号一小时，普通错误退避 30 秒。
- Worker 为每个 active ClawBot 账号启动独立轮询线程，并定期发现小程序中新连接的账号。
- Worker 停机时执行 `shutdown_executor(wait=True)`，平滑等待已分发消息的回复发送完毕。

## 能力边界

第一版处理文本消息与语音消息中已经存在的转写文本，只发送文本。媒体 CDN 的 AES-128-ECB
上传下载尚未启用。ClawBot 不是普通微信好友，不能读取历史聊天、搜索联系人或操作微信客户端。
