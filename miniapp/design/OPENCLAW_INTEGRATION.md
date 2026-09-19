# OpenClaw 官方微信渠道接入

本项目采用 OpenClaw 官方文档描述的组合：

```text
微信私聊
  → @tencent-weixin/openclaw-weixin
  → OpenClaw Gateway / Agent
  → schedule-tools 插件
  → FastAPI /api/integrations/openclaw/tools
  → PostgreSQL
```

不让 FastAPI 接收微信原始事件。微信登录、iLink API、媒体和消息回复由腾讯外部插件负责；OpenClaw Agent 负责理解自然语言并选择课表工具；FastAPI 负责身份、权限和确定性课表业务。

## 版本要求

- OpenClaw `>=2026.5.17`；
- Node.js 24.16+ 或 26.1+；
- `@tencent-weixin/openclaw-weixin` 2.4.8 对应 OpenClaw `>=2026.5.12`；
- 建议固定已验证版本，升级 OpenClaw 时重新运行插件测试。

## 安装微信插件

```bash
npx -y @tencent-weixin/openclaw-weixin-cli install
openclaw channels login --channel openclaw-weixin
openclaw config set session.dmScope per-account-channel-peer
```

扫码登录后检查：

```bash
openclaw plugins list
openclaw channels status --probe
openclaw plugins inspect openclaw-weixin --runtime --json
```

腾讯插件 2.4.8 的标准 pairing adapter 尚不完整，因此不能以 OpenClaw pairing 作为课表权限边界。本项目仍要求用户通过小程序一次性绑定码，将 OpenClaw 提供的 `requesterSenderId` 映射到业务 `user_id`。

## 安装课表 Tool 插件

插件源码位于 `integrations/openclaw-schedule-tools`。构建后用本地 npm 包安装：

```bash
cd integrations/openclaw-schedule-tools
npm install
npm run build
npm pack
openclaw plugins install npm-pack:./wx-classschedule-openclaw-tools-0.1.0.tgz
openclaw plugins enable schedule-tools
```

在 OpenClaw 配置中填写插件配置：

```json5
{
  plugins: {
    entries: {
      "schedule-tools": {
        enabled: true,
        config: {
          baseUrl: "https://wx-api.tanzeng.xyz",
          apiSecret: "与服务端 OPENCLAW_TOOL_SECRET 完全相同"
        }
      }
    }
  },
  tools: {
    allow: ["schedule-tools"]
  }
}
```

配置后运行：

```bash
openclaw plugins inspect schedule-tools --runtime --json
openclaw gateway restart
```

## 工具

- `schedule_bind`：消费小程序生成的六位绑定码；
- `schedule_get_by_date`：查询某日及某时段课程；
- `schedule_get_next`：查询当前或未来 7 天的下一节课；
- `schedule_get_week`：查询某自然周，可指定星期；
- `schedule_find_course`：查询某门课程未来的安排。

所有工具从 OpenClaw 可信运行上下文读取 `requesterSenderId`，参数 Schema 中没有 `user_id` 或 `sender_id`。FastAPI 还会通过共享密钥验证插件请求，然后再次以身份映射约束查询。

## 服务端配置

```env
OPENCLAW_TOOL_SECRET=高强度随机密钥
APP_TIMEZONE=Asia/Shanghai
BINDING_CODE_TTL_SECONDS=300
```

## V1 限制

- 腾讯微信插件能力元数据只声明私聊，不承诺群聊；
- 第一版课表工具只读，除身份绑定外不修改课表；
- OpenClaw Agent 负责最终措辞，FastAPI 返回结构化事实；
- 主动提醒和图片调课留到后续阶段；
- OpenClaw 或微信插件升级后需要重新验证 `requesterSenderId` 的稳定性。
