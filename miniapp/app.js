const { apiBaseUrl, devLogin } = require('./config')
// 实时日志用于上线后排障：只记录 JS 异常与未处理的 Promise 拒绝，可在小程序后台「开发管理-运行时日志」查看
const logger = wx.getRealtimeLogManager ? wx.getRealtimeLogManager() : null

App({
  onError(message) { if (logger) logger.error(String(message)) },
  onUnhandledRejection({ reason }) {
    if (logger) logger.error('unhandledrejection: ' + ((reason && (reason.stack || reason.message)) || String(reason)))
  },
  globalData: { apiBaseUrl, devLogin, loginPromise: null },

  login(force = false) {
    if (!force) {
      const token = wx.getStorageSync('session_token')
      if (token) return Promise.resolve(token)
      if (this.globalData.loginPromise) return this.globalData.loginPromise
    }
    this.globalData.loginPromise = new Promise((resolve, reject) => {
      const exchangeCode = code => wx.request({
        url: `${apiBaseUrl}/api/auth/wechat`, method: 'POST',
        header: { 'content-type': 'application/json' }, data: { code },
        success: ({ statusCode, data }) => {
          if (statusCode >= 200 && statusCode < 300 && data.token) {
            wx.setStorageSync('session_token', data.token)
            resolve(data.token)
          } else reject(new Error(data.detail || '微信登录失败'))
        },
        fail: error => reject(new Error(`无法连接服务器：${error.errMsg || '网络异常'}`)),
      })
      if (devLogin) exchangeCode('dev')
      else wx.login({
        success: ({ code }) => exchangeCode(code),
        fail: () => reject(new Error('无法获取微信登录凭证')),
      })
    }).finally(() => { this.globalData.loginPromise = null })
    return this.globalData.loginPromise
  },

  // 超时与网络失败分开提示；超时时引导稍后刷新确认（服务端可能已处理成功）
  requestFailMessage(error) {
    const msg = (error && error.errMsg) || ''
    if (/timeout/i.test(msg)) return '请求超时，服务端可能仍在处理，请稍后刷新课表确认'
    return '网络连接失败，请检查网络后重试'
  },

  async request(path, options = {}, retried = false) {
    const token = await this.login()
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${apiBaseUrl}${path}`, method: options.method || 'GET', data: options.data,
        header: { 'content-type': 'application/json', Authorization: `Bearer ${token}`, ...(options.header || {}) },
        success: async ({ statusCode, data }) => {
          if (statusCode === 401 && !retried) {
            wx.removeStorageSync('session_token')
            try { resolve(await this.request(path, options, true)) } catch (error) { reject(error) }
          } else if (statusCode >= 200 && statusCode < 300) resolve(data)
          else {
            const detail = data && data.detail
            const error = new Error((typeof detail === 'object' && detail.message) || detail || '请求失败')
            error.statusCode = statusCode
            if (detail && typeof detail === 'object') { error.code = detail.code; error.data = detail }
            reject(error)
          }
        },
        fail: error => reject(new Error(this.requestFailMessage(error))),
      })
    })
  },

  async upload(path, filePath, formData, retried = false) {
    const token = await this.login()
    return new Promise((resolve, reject) => {
      wx.uploadFile({
        url: `${apiBaseUrl}${path}`, filePath, name: 'file', formData,
        header: { Authorization: `Bearer ${token}` },
        success: async ({ statusCode, data }) => {
          let body = {}; try { body = JSON.parse(data) } catch (_) {}
          if (statusCode === 401 && !retried) {
            wx.removeStorageSync('session_token')
            try { resolve(await this.upload(path, filePath, formData, true)) } catch (error) { reject(error) }
          } else if (statusCode >= 200 && statusCode < 300) resolve(body)
          else {
            const detail = body && body.detail
            const error = new Error((typeof detail === 'object' && detail.message) || detail || '上传失败')
            error.statusCode = statusCode
            if (detail && typeof detail === 'object') {
              error.code = detail.code
              error.data = detail
            }
            reject(error)
          }
        },
        fail: error => reject(new Error(/timeout/i.test((error && error.errMsg) || '')
          ? '上传超时，服务端可能仍在解析，请稍后在课表页下拉确认'
          : '文件上传失败，请检查网络后重试')),
      })
    })
  },
})
