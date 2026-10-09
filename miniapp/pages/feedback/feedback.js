const app = getApp()

function clientInfo() {
  let device = {}
  let base = {}
  let account = {}
  try {
    device = wx.getDeviceInfo ? wx.getDeviceInfo() : wx.getSystemInfoSync()
    base = wx.getAppBaseInfo ? wx.getAppBaseInfo() : wx.getSystemInfoSync()
    account = wx.getAccountInfoSync ? wx.getAccountInfoSync() : {}
  } catch (_) {}
  return {
    platform: String(device.platform || ''),
    system: String(device.system || ''),
    wechat_version: String(base.version || ''),
    app_version: String((account.miniProgram && account.miniProgram.version) || 'dev'),
  }
}

Page({
  data: {
    description: '',
    contact: '',
    submitting: false,
    submitted: false,
    feedbackNo: '',
    nightMode: false,
    backgroundPath: '',
  },
  onShow() {
    const nightMode = wx.getStorageSync('night_mode') === true
    const backgroundPath = wx.getStorageSync('schedule_background') || ''
    this.setData({ nightMode, backgroundPath })
    if (wx.setNavigationBarColor) {
      wx.setNavigationBarColor({
        frontColor: (nightMode || backgroundPath) ? '#ffffff' : '#000000',
        backgroundColor: nightMode ? '#070d19' : (backgroundPath ? '#000000' : '#f3f6fb')
      }).catch(() => {})
    }
  },
  onLoad(options) {
    this.scheduleId = Number(options && options.scheduleId) || 0
  },
  setDescription(event) {
    this.setData({ description: event.detail.value })
  },
  setContact(event) {
    this.setData({ contact: event.detail.value })
  },
  async submit() {
    const description = this.data.description.trim()
    if (description.length < 5) return this.toast('请至少填写 5 个字的问题描述')
    const contact = this.data.contact.trim()
    if (this.data.submitting) return
    this.setData({ submitting: true })
    try {
      const result = await app.request('/api/feedback', {
        method: 'POST',
        data: {
          description,
          contact,
          schedule_id: this.scheduleId || null,
          client_info: clientInfo(),
        },
      })
      this.setData({ submitted: true, feedbackNo: result.feedback_no || '' })
    } catch (error) {
      this.toast(error.message || '反馈提交失败，请稍后重试')
    } finally {
      this.setData({ submitting: false })
    }
  },
  back() {
    wx.navigateBack()
  },
  copyFeedbackNo() {
    if (!this.data.feedbackNo) return
    wx.setClipboardData({
      data: this.data.feedbackNo,
      success: () => wx.showToast({ title: '单号已复制', icon: 'success' }),
    })
  },
  toast(title) {
    wx.showToast({ title, icon: 'none' })
  },
})
