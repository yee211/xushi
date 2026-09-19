const app = getApp()
const config = require('../../config')

Page({
  data: { loading: true, code: '', codeProvider: '', expiresAt: '', generating: false,
    connecting: false, loginSession: '', qrDataUrl: '', loginStatus: '', needVerifyCode: false,
    verifyCode: '', claw: { bound: false }, wecom: { bound: false },
    account: { linked: false, email: '' }, linkCode: '', linking: false,
    confirmModal: { visible: false, title: '', content: '', confirmText: '确定', cancelText: '取消', danger: false } },
  onLoad(options) {
    this.scheduleId = Number(options && options.scheduleId) || 0
  },
  onShow() {
    this.pollCancelled = false
    this.loadStatus()
    // 离开页面（如长按识别二维码跳去微信）会中断轮询链，返回时若有进行中的扫码会话则恢复
    if (this.data.loginSession && this.data.connecting) this.pollLogin('')
  },
  onHide() { this.pollCancelled = true },
  onUnload() { this.pollCancelled = true },
  openFeedback() {
    wx.navigateTo({ url: `/pages/feedback/feedback${this.scheduleId ? `?scheduleId=${this.scheduleId}` : ''}` })
  },
  async loadStatus() {
    this.setData({ loading: true })
    try {
      // 账号互通接口可能先于小程序发版上线（旧后端 404），失败时按未绑定处理
      const [result, link] = await Promise.all([
        app.request('/api/agent-bindings'),
        app.request('/api/account/link').catch(() => null),
      ])
      const byProvider = {}
      for (const item of result.channels || []) byProvider[item.provider] = item
      this.setData({ loading: false,
        claw: byProvider.weixin_ilink || { bound: false },
        wecom: byProvider.wecom || { bound: false },
        account: { linked: !!(link && link.email), email: (link && link.email) || '' } })
    } catch (error) { this.setData({ loading: false }); this.toast(error.message) }
  },
  onLinkCodeInput(event) { this.setData({ linkCode: event.detail.value }) },
  async submitLinkCode() {
    const code = String(this.data.linkCode || '').trim().toUpperCase()
    if (code.length !== 6) return this.toast('请输入六位绑定码')
    this.setData({ linking: true })
    try {
      const result = await app.request('/api/account/link', { method: 'POST', data: { code } })
      const notes = []
      if (result.schedules_moved > 0) notes.push(`${result.schedules_moved} 张课表已同步`)
      if (result.schedules_discarded > 0) notes.push(`${result.schedules_discarded} 张重复课表已移除`)
      this.setData({ linkCode: '', account: { linked: true, email: result.email || '' } })
      this.toast(notes.length ? `绑定成功，${notes.join('，')}` : '绑定成功')
      this.loadStatus()
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ linking: false }) }
  },
  async unlinkAccount() {
    if (this.data.linking) return
    const result = await this.modal({
      title: '解除绑定',
      content: '解除后，小程序将恢复为独立账号，课表不再与 App 同步。',
      confirmText: '解除绑定',
      danger: true,
    })
    if (!result.confirm) return
    this.setData({ linking: true })
    try {
      await app.request('/api/account/link', { method: 'DELETE' })
      // 服务端已吊销全部会话：清除本地令牌，下次请求静默重新登录为全新账号
      wx.removeStorageSync('session_token')
      this.setData({ account: { linked: false, email: '' } })
      this.toast('已解除绑定')
      this.loadStatus()
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ linking: false }) }
  },
  async generateCode(event) {
    const provider = event.currentTarget.dataset.provider || 'wecom'
    this.setData({ generating: true, code: '', codeProvider: '', expiresAt: '' })
    try {
      const result = await app.request('/api/agent-bindings/code',
        { method: 'POST', data: { provider } })
      this.setData({ code: result.code, codeProvider: result.provider || provider,
        expiresAt: this.formatTime(result.expires_at) })
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ generating: false }) }
  },
  async connectClawBot() {
    this.pollCancelled = false
    this.setData({ connecting: true, loginStatus: '正在生成二维码…', needVerifyCode: false })
    try {
      const result = await app.request('/api/integrations/weixin/login', { method: 'POST' })
      this.setData({ loginSession: result.session_id,
        qrDataUrl: `${app.globalData.apiBaseUrl}${result.qrcode_path}`,
        loginStatus: '请长按保存图片，再回到微信扫码确认连接' })
      this.pollLogin('')
    } catch (error) {
      this.setData({ connecting: false, loginStatus: '' }); this.toast(error.message)
    }
  },
  previewQrcode() {
    // 原生预览器的长按菜单由微信客户端决定，仅保证可保存图片。
    if (!this.data.qrDataUrl) return
    wx.previewImage({ urls: [this.data.qrDataUrl] })
  },
  async pollLogin(verifyCode = '') {
    if (this.pollCancelled || !this.data.loginSession) return
    // 每次启动/恢复轮询都递增令牌，使旧轮询链的定时器自动失效，避免 onShow 恢复后出现双链路
    const token = (this.pollToken = (this.pollToken || 0) + 1)
    try {
      const result = await app.request(`/api/integrations/weixin/login/${this.data.loginSession}/poll`,
        { method: 'POST', data: { verify_code: verifyCode } })
      if (result.connected) {
        this.setData({ connecting: false, qrDataUrl: '', loginSession: '',
          loginStatus: '', needVerifyCode: false, verifyCode: '' })
        this.toast('微信 ClawBot 连接成功')
        this.loadStatus()
        return
      }
      const status = result.status || 'wait'
      if (status === 'need_verifycode') {
        this.setData({ needVerifyCode: true, loginStatus: '请输入微信中显示的数字验证码' })
        return
      }
      if (['expired', 'verify_code_blocked', 'binded_redirect'].includes(status)) {
        const message = status === 'expired' ? '二维码已过期，请重新生成' :
          (status === 'binded_redirect' ? '该 ClawBot 已连接过其他实例' : '验证码错误次数过多，请重试')
        this.setData({ connecting: false, qrDataUrl: '', loginSession: '', loginStatus: message })
        return
      }
      this.setData({ loginStatus: status === 'scaned' ? '已扫码，请在微信中确认连接…' : this.data.loginStatus })
      if (!this.pollCancelled && token === this.pollToken) setTimeout(() => this.pollLogin(''), 1200)
    } catch (error) {
      this.setData({ connecting: false, loginStatus: '' }); this.toast(error.message)
    }
  },
  onVerifyInput(event) { this.setData({ verifyCode: event.detail.value }) },
  submitVerifyCode() {
    const code = String(this.data.verifyCode || '').trim()
    if (!code) return this.toast('请输入验证码')
    this.setData({ needVerifyCode: false, loginStatus: '正在验证…' })
    this.pollLogin(code)
  },
  copyCommand() {
    if (!this.data.code) return
    wx.setClipboardData({ data: `绑定 ${this.data.code}`,
      success: () => wx.showToast({ title: '已复制，去微信发送给助手', icon: 'none' }) })
  },
  modal({ title = '', content = '', confirmText = '确定', cancelText = '取消', danger = false }) {
    return new Promise(resolve => {
      this._modalResolve = resolve
      this.setData({
        confirmModal: { visible: true, title, content, confirmText, cancelText, danger }
      })
    })
  },
  onModalConfirm() {
    this.setData({ 'confirmModal.visible': false })
    if (this._modalResolve) {
      const resolve = this._modalResolve
      this._modalResolve = null
      resolve({ confirm: true, cancel: false })
    }
  },
  onModalCancel() {
    this.setData({ 'confirmModal.visible': false })
    if (this._modalResolve) {
      const resolve = this._modalResolve
      this._modalResolve = null
      resolve({ confirm: false, cancel: true })
    }
  },
  noop() {},
  async unbind(event) {
    const provider = event.currentTarget.dataset.provider
    const result = await this.modal({
      title: '解除绑定',
      content: '解除后，该渠道的助手将无法查询你的课表。',
      confirmText: '解除绑定',
      danger: true,
    })
    if (!result.confirm) return
    try {
      this.pollCancelled = true
      await app.request(`/api/agent-bindings/${provider}`, { method: 'DELETE' })
      this.setData({ code: '', codeProvider: '', expiresAt: '', qrDataUrl: '', loginSession: '' })
      this.toast('已解除绑定')
      this.loadStatus()
    } catch (error) { this.toast(error.message) }
  },
  formatTime(value) {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? '' : `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  },
  toast(title) { wx.showToast({ title: title || '操作失败', icon: 'none' }) },
})
