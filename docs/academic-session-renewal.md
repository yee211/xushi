# 云服务器学校会话维持方案

2026-10-08 实测发现：
1. 旧学校 Cookie 在独立 HTTP 请求中返回 302，跳转 zts.ccsut.cn。
   网关同时清除 sdp_app_session-443 / legacy Cookie，证明已有应用会话会过期。
2. 同一浏览器打开正常课表入口，经过学校网关的 reportEnv、authCheck、
   verify 和正常应用授权跳转后自动回到学生课表，未再次要求扫码。
3. 新请求中的网关 Cookie 和教务 JSESSIONID 均发生变化。
这验证了当前浏览器 SSO 状态尚有效时能恢复，不证明可无限续期；
未确定学校的闲置超时、绝对到期时间，也未验证云服务器 IP。

建议在云服务器运行专用持久 Chromium，保留整个学校认证状态。
管理员首次在云服务器浏览器扫码登录，后台定期访问正常课表入口。
若应用 Cookie 失效、SSO 仍有效，正常导航可恢复；若 SSO 也失效，
进入 needs_login 状态，由管理员补扫码。不能通过改本地 Cookie 到期时间
延长学校服务端会话，也不复用 CAS 一次性 ticket 或临时授权 code。

## 已准备的可运行脚本

server/scripts/academic_session_worker.py。它使用正常浏览器导航，不调用猜测的续期接口。
独立学校账户通过 CCSUT_EXPECTED_ACCOUNT 指定；若浏览器账户不匹配，不导出会话。
正常到达课表页后，用独立 HTTP 查询验证，再调用现有加密连接保存逻辑。
Cookie 不写日志；完整浏览器 profile 自带凭据，应仅供运行账户访问。

脚本为可选独立进程，未加入 API 主进程，未在云服务器部署。
安装依赖后使用服务器上与 API 相同的 Python 环境、ADMIN_SESSION_SECRET 和 data 挂载：
```bash
python -m pip install playwright
python -m playwright install --with-deps chromium

# 首次登录需要可见浏览器 / 桌面会话：在服务器桌面中执行
export CCSUT_EXPECTED_ACCOUNT='<你的学校账号>'
python scripts/academic_session_worker.py --login

# 登录后常驻检查；600 秒只是初始检查间隔，不是实测有效期
python scripts/academic_session_worker.py --interval 600
```

Linux 无桌面时，可用受保护的远程桌面 / noVNC 或 SSH 转发进入服务器桌面，
先运行 --login，扫码完成后结束，再用同一 profile 启动后台进程。
两个 Chromium 进程不能同时使用同一 profile。
不需要开放浏览器调试端口供公网连接。
若云服务器无图形依赖或学校限制该 IP，需调整部署或使用本机采集端，
不能因为本机验证成功就保证云服务器成功。

状态写入 data/academic/browser-status.json；
profile 位于 data/academic/browser-profile；连接仍为 connection.enc。
当前 --login 会打开可见浏览器，这是给管理员扫码的明确交互模式。
后台默认 headless，实际学校网关是否接受 headless 需云端验证。

## 与现有 API 的同步

API 每次查询读取加密连接文件，因此 worker 轮换会话后能使用新配置。
会话变化会使内存课表失效，学生上下文与 SQLite 完整课表缓存保留。
worker 与 API 必须共享同一 data 挂载和加密密钥。
普通周期内 Cookie 未变化时不会重写连接文件。
后台展示最近检查时间及 connected / needs_login / error 状态。
暂未集成自动通知、网页内扫码画面和自动安装服务。

登录过期时，年级、已缓存学生搜索、已有课表学期和课表均可回退到
持久缓存。没有缓存的数据仍需要恢复学校连接后查询。

Playwright 持久浏览器目录能力：
https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context


## 后台账号密码与验证码登录（第一版）

超级管理员在「学校教务连接」保存学校账号密码，密码使用 AES-GCM 加密，
存储于 data/academic/credentials.enc。管理接口只返回账号、是否已保存和登录状态。
点击「发起登录 / 开始维护」启动专用 headless Chromium，正常导航到学校密码登录页，
点击「获取验证码」后，在后台输入收到的验证码并提交。验证码仅放在内存队列中，
不会持久化，登录任务 ID 防止把旧任务验证码提交到新会话。发送间隔至少 60 秒。

专用 profile 为 data/academic/managed-browser-profile，与旧命令行 worker 的目录不同。
登录成功用独立 HTTP 校验账号及课表权限，自动更新加密 Cookie；每 10 分钟再次
正常导航检查。需要新验证码时回到后台补输入。服务重启后点击开始维护恢复。
第一版依赖单 API 进程；多实例必须把登录控制放到一个独立浏览器服务。
Linux 安装 playwright 与 chromium 所需系统依赖，目录与 API 同 data 挂载。

目前已核实真实学校密码表单控件与跳转；真实账号登录需管理员完成测试。
未实现图形验证码、扫码画面或设备确认的远程交互。学校流程变化时会失败并提示，
可在高级设置手动配置 Cookie。保存账号密码不承诺能跳过学校验证码或永久续期。
停止维护后可更换或删除账号密码；删除密码不会自动删除当前应用 Cookie 和 browser profile。
