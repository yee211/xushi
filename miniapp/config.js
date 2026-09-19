// 环境切换：开发者工具（develop）连本机 FastAPI 联调；体验版/正式版使用已备案的 HTTPS 域名。
// 上线前把 PROD_API_BASE_URL 改为真实域名，并在微信公众平台加入 request 与 uploadFile 合法域名。
// 统一后端与网页版共用同一个服务（默认本地端口 8000）；生产环境把
// PROD_API_BASE_URL 与网页端 VITE_API_BASE_URL 指向同一个域名即可。
const DEV_API_BASE_URL = 'http://127.0.0.1:8001'
const PROD_API_BASE_URL = 'https://wx-api.tanzeng.xyz'
const platform = typeof wx !== 'undefined' && wx.getDeviceInfo
  ? wx.getDeviceInfo().platform
  : ''
const envVersion = (() => {
  try { return (wx.getAccountInfoSync().miniProgram || {}).envVersion || 'release' } catch (_) { return 'release' }
})()
const apiBaseUrl = envVersion === 'develop' ? DEV_API_BASE_URL : PROD_API_BASE_URL

// 助手开关：过审后正式开启
const SHOW_AGENT_DEFAULT = true

module.exports = {
  apiBaseUrl,
  devLogin: platform === 'devtools' && /^http:\/\/(127\.0\.0\.1|localhost)(:|\/|$)/.test(apiBaseUrl),
  showAgent: SHOW_AGENT_DEFAULT,
}

