const app = getApp()
const days = ['周一','周二','周三','周四','周五','周六','周日']
const DEFAULT_COLOR = '#5B8DEF'
// 高辨识度课程调色板，与源项目 utils/schedule.js 一致
const COURSE_COLORS = [
  '#F59E0B', '#F43F5E', '#F97316', '#A855F7', '#06B6D4', '#84CC16',
  '#3B82F6', '#EC4899', '#10B981', '#6366F1', '#EAB308', '#14B8A6',
  '#8B5CF6', '#D946EF', '#2563EB', '#059669',
]
function formatWeeks(weeks) {
  if (!weeks || !weeks.length) return ''
  const ranges=[]; let start=weeks[0], last=start
  weeks.slice(1).forEach(n => { if(n===last+1) last=n; else { ranges.push(start===last?`${start}`:`${start}-${last}`); start=last=n } })
  ranges.push(start===last?`${start}`:`${start}-${last}`); return ranges.join(',')
}
function parseWeeks(text) {
  const result=[]
  String(text).split(/[,，]/).forEach(part => { const [a,b]=part.trim().split('-').map(Number); if(a&&b) for(let i=a;i<=b;i++) result.push(i); else if(a) result.push(a) })
  return [...new Set(result)].filter(n=>n>=1&&n<=30).sort((a,b)=>a-b)
}
Page({
  data: {
    id: null, scheduleId: null, name: '', teacher: '', room: '', weekday: 1,
    startSection: 1, endSection: 2, weeks: '1-16', color: DEFAULT_COLOR, days,
    colors: [DEFAULT_COLOR, ...COURSE_COLORS],
    sections: Array.from({length:12},(_,i)=>`第${i+1}节`), saving: false,
    adjustedWeek: null,
    confirmModal: { visible: false, title: '', content: '', confirmText: '确定', cancelText: '取消', danger: false },
  },
  onLoad(options) {
    this.setData({ nightMode: wx.getStorageSync('night_mode') === true })
    if (wx.setNavigationBarColor) {
      const nightMode = this.data.nightMode
      wx.setNavigationBarColor({ frontColor: nightMode ? '#ffffff' : '#000000',
        backgroundColor: nightMode ? '#0b1220' : '#f3f6fb', fail: () => {} })
    }
    const course = wx.getStorageSync('editing_course')
    if (course && course.name) {
      wx.setNavigationBarTitle({ title: course.id ? '编辑课程' : '校对课程' })
      this.setData({
        id: course.id || null, scheduleId: course.schedule_id || Number(options.scheduleId), name: course.name,
        teacher: course.teacher || '', room: course.room || '', weekday: course.weekday || 1,
        startSection: course.start_section || 1, endSection: course.end_section || 2,
        weeks: formatWeeks(course.weeks) || '1-16', color: course.color || DEFAULT_COLOR,
        adjustedWeek: course.adjusted_week || null,
      })
    } else {
      wx.setNavigationBarTitle({ title: '添加课程' })
      this.setData({ scheduleId: Number(options.scheduleId) })
    }
  },
  field(event) { this.setData({ [event.currentTarget.dataset.key]: event.detail.value }) },
  weekday(event) { this.setData({ weekday: Number(event.detail.value)+1 }) },
  startSection(event) { this.setData({ startSection: Number(event.detail.value)+1 }) },
  endSection(event) { this.setData({ endSection: Number(event.detail.value)+1 }) },
  pickColor(event) { this.setData({ color: event.currentTarget.dataset.color }) },
  async save() {
    if (!this.data.name.trim()) return this.toast('请填写课程名称')
    if (this.data.endSection < this.data.startSection) return this.toast('结束节次不能早于开始节次')
    const payload = {
      schedule_id: this.data.scheduleId, name: this.data.name.trim(), teacher: this.data.teacher.trim(),
      room: this.data.room.trim(), weekday: this.data.weekday, start_section: this.data.startSection,
      end_section: this.data.endSection, weeks: parseWeeks(this.data.weeks), color: this.data.color,
    }
    this.setData({ saving: true })
    try {
      await app.request(this.data.id ? `/api/courses/${this.data.id}` : '/api/courses', { method: this.data.id ? 'PUT' : 'POST', data: payload })
      // 编辑已调课课程时，新时间覆盖旧安排，同步撤销该周调课（与源项目 saveCourse 一致）
      if (this.data.id && this.data.adjustedWeek) {
        await app.request(`/api/courses/${this.data.id}/adjustments/${this.data.adjustedWeek}`, { method: 'DELETE' })
      }
      wx.removeStorageSync('editing_course'); wx.navigateBack()
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ saving: false }) }
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
  async remove() {
    const result = await this.modal({
      title: '删除课程',
      content: `确认删除“${this.data.name}”？`,
      confirmText: '删除',
      danger: true,
    })
    if (!result.confirm) return
    try {
      await app.request(`/api/courses/${this.data.id}`, { method: 'DELETE' })
      wx.removeStorageSync('editing_course')
      wx.navigateBack()
    } catch (error) { this.toast(error.message) }
  },
  cancel() { wx.removeStorageSync('editing_course'); wx.navigateBack() },
  toast(title) { wx.showToast({title,icon:'none'}) },
})
