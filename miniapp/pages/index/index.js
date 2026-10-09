const app = getApp()
const days = ['周一','周二','周三','周四','周五','周六','周日']
const dayShortNames = ['一','二','三','四','五','六','日']
const ROW_HEIGHT = 112
const DEFAULT_COLOR = '#5B8DEF'
const sections = [
  { number: 1, start: '08:20', end: '09:05' },
  { number: 2, start: '09:15', end: '10:00' },
  { number: 3, start: '10:20', end: '11:05' },
  { number: 4, start: '11:15', end: '12:00' },
  { number: 5, start: '14:00', end: '14:45' },
  { number: 6, start: '14:55', end: '15:40' },
  { number: 7, start: '16:00', end: '16:45' },
  { number: 8, start: '16:55', end: '17:40' },
  { number: 9, start: '19:00', end: '19:45' },
  { number: 10, start: '19:55', end: '20:40' },
  { number: 11, start: '20:50', end: '21:35' },
  { number: 12, start: '21:45', end: '22:30' },
]
// 高辨识度课程调色板，与源项目 utils/schedule.js 保持一致
const courseColors = [
  '#F59E0B', '#F43F5E', '#F97316', '#A855F7', '#06B6D4', '#84CC16',
  '#3B82F6', '#EC4899', '#10B981', '#6366F1', '#EAB308', '#14B8A6',
  '#8B5CF6', '#D946EF', '#2563EB', '#059669',
]

// ===== 果冻水晶卡混色（液态玻璃规范,JS 版 color-mix,兼容不支持 color-mix 的内核）=====
const WHITE_RGB = [255, 255, 255]
const INK_RGB = [15, 23, 42]
function hexRgb(color) {
  const value = String(color || '').replace('#', '')
  const full = value.length === 3 ? value.split('').map(ch => ch + ch).join('') : value
  const int = parseInt(full.slice(0, 6), 16) || 0x5b8def
  return [(int >> 16) & 255, (int >> 8) & 255, int & 255]
}
function mixTo(rgb, target, weight) {
  return rgb.map((channel, index) => Math.round(channel + (target[index] - channel) * weight))
}
function rgbaStr(rgb, alpha) { return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})` }
// 白光透染 → 半透彩色 → 透明衰减；微棱高光与彩色弥散投影一并内联
function jellyStyle(color) {
  const rgb = hexRgb(color)
  return 'background:linear-gradient(135deg,' + rgbaStr(mixTo(rgb, WHITE_RGB, .45), .95) + ' 0%,'
    + rgbaStr(rgb, .82) + ' 52%,' + rgbaStr(rgb, .60) + ' 100%)'
    + ';border-color:' + rgbaStr(mixTo(rgb, WHITE_RGB, .35), .85)
    + ';box-shadow:0 8rpx 20rpx -3rpx ' + rgbaStr(rgb, .30)
    + ',0 4rpx 10rpx -2rpx ' + rgbaStr(rgb, .18)
    + ',inset 0 1.5px 0.5px rgba(255,255,255,.88)'
    + ',inset 0 -1px 1px ' + rgbaStr(mixTo(rgb, INK_RGB, .25), .80) + ';'
}

function localDate(value) {
  const parts = String(value || '').slice(0, 10).split('-').map(Number)
  return parts[0] ? new Date(parts[0], parts[1] - 1, parts[2]) : null
}
function isoDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
}
function defaultTermName(value) {
  const date = localDate(value) || new Date()
  const year = date.getFullYear()
  const month = date.getMonth() + 1
  return month >= 7 ? `${year}-${year + 1}-1学期` : `${year - 1}-${year}-2学期`
}
// 从文件名（如 2025-2026-1）推测学期起止日期，与源项目 suggestSemesterDates 对齐
function suggestSemesterDates(termStr) {
  const match = String(termStr || '').trim().match(/(\d{4})\s*[-–—/]\s*(\d{4})[^\d]*(?:第\s*)?([12一二秋春])/)
  if (!match) return null
  const year1 = Number(match[1])
  const isFirstTerm = match[3] === '1' || match[3] === '一' || match[3] === '秋'
  const anchor = isFirstTerm ? new Date(year1, 8, 1) : new Date(Number(match[2]) || year1 + 1, 2, 1)
  const day = anchor.getDay()
  const mondayOffset = day === 0 ? 1 : (day === 1 ? 0 : 8 - day)
  const start = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + mondayOffset)
  const end = new Date(start.getTime() + (20 * 7 - 1) * 86400000)
  return { start: isoDate(start), end: isoDate(end) }
}
function weekCount(schedule) {
  const start = localDate(schedule && schedule.start_date), end = localDate(schedule && schedule.end_date)
  if (start && end) return Math.max(1, Math.min(30, Math.ceil(((end-start)/86400000+1)/7)))
  const weeks = (schedule && schedule.courses || []).reduce((all, item) => all.concat(item.weeks || []), [])
  return Math.min(30, Math.max(20, ...weeks, 20))
}
function isScheduleActiveToday(schedule) {
  const start = localDate(schedule && schedule.start_date)
  if (!start) return false
  const total = weekCount(schedule)
  const end = localDate(schedule && schedule.end_date) || new Date(start.getTime() + (total * 7 - 1) * 86400000)
  const today = new Date(isoDate(new Date()))
  return today >= new Date(isoDate(start)) && today <= new Date(isoDate(end))
}
function termWeek(schedule) {
  const start = localDate(schedule && schedule.start_date)
  if (!start) return 1
  // 历史/未来学期默认从第 1 周看起，与源项目 termWeek 行为一致
  if (!isScheduleActiveToday(schedule)) return 1
  start.setDate(start.getDate() - ((start.getDay() || 7) - 1))
  const elapsed = Math.floor((new Date(isoDate(new Date())) - new Date(isoDate(start))) / 86400000)
  return Math.max(1, Math.min(weekCount(schedule), Math.floor(elapsed / 7) + 1))
}
function formatWeeks(weeks) {
  if (!weeks || !weeks.length) return '未设置周次'
  const sorted = [...weeks].sort((a, b) => a - b)
  const ranges = []
  let start = sorted[0]
  let last = start
  sorted.slice(1).forEach(week => {
    if (week === last + 1) last = week
    else {
      ranges.push(start === last ? `${start}` : `${start}-${last}`)
      start = last = week
    }
  })
  ranges.push(start === last ? `${start}` : `${start}-${last}`)
  return `${ranges.join('、')}周`
}
function formatWeeksInput(weeks) {
  if (!weeks || !weeks.length) return ''
  const sorted = [...weeks].filter(n => typeof n === 'number' && !isNaN(n)).sort((a, b) => a - b)
  if (!sorted.length) return ''
  const ranges = []
  let start = sorted[0]
  let last = start
  sorted.slice(1).forEach(n => {
    if (n === last + 1) last = n
    else {
      ranges.push(start === last ? `${start}` : `${start}-${last}`)
      start = last = n
    }
  })
  ranges.push(start === last ? `${start}` : `${start}-${last}`)
  return ranges.join(',')
}
function courseKey(name) {
  return String(name || '未命名课程').trim().replace(/\s+/g, ' ').toLowerCase()
}
function buildColorMap(courses) {
  const names = [...new Set((courses || []).map(item => courseKey(item.name)))].sort()
  const map = {}
  names.forEach((name, index) => { map[name] = courseColors[index % courseColors.length] })
  return map
}
function datesForWeek(schedule, week) {
  let monday = localDate(schedule && schedule.start_date) || new Date()
  const weekday = monday.getDay() || 7
  monday.setDate(monday.getDate() - weekday + 1 + (week - 1) * 7)
  const today = isoDate(new Date())
  const active = isScheduleActiveToday(schedule)
  const weekDays = dayShortNames.map((name, index) => {
    const date = new Date(monday)
    date.setDate(date.getDate() + index)
    return {
      name,
      date: String(date.getDate()).padStart(2, '0'),
      month: String(date.getMonth() + 1).padStart(2, '0'),
      isToday: active && isoDate(date) === today,
    }
  })
  const first = weekDays[0]
  const last = weekDays[6]
  return {
    weekDays,
    monthLabel: `${first.month}月`,
    range: `${first.month}.${first.date}-${last.month}.${last.date}`,
  }
}
function buildWeekOptions(schedule, count, selectedWeek) {
  return Array.from({ length: count }, (_, index) => {
    const week = index + 1
    const dates = datesForWeek(schedule, week)
    return { week, range: dates.range, selected: week === selectedWeek }
  })
}
function scheduleMeta(schedule) {
  const courses = schedule && schedule.courses || []
  const lessons = courses.reduce((total, course) => {
    const weeks = (course.weeks && course.weeks.length) || 20
    const span = Math.max(1, (course.end_section || 1) - (course.start_section || 1) + 1)
    return total + weeks * Math.ceil(span / 2)
  }, 0)
  return { unique: new Set(courses.map(item => courseKey(item.name))).size, lessons }
}
function scheduleStatus(schedule) {
  if (!isScheduleActiveToday(schedule)) {
    const start = localDate(schedule && schedule.start_date)
    return start && new Date(isoDate(start)) > new Date(isoDate(new Date())) ? '未开学' : '往期'
  }
  return `进行中 · 第${termWeek(schedule)}周`
}
function sectionCountFor(schedule) {
  const ends = (schedule && schedule.courses || []).map(item => Number(item.end_section) || 0)
  return Math.min(12, Math.max(10, ...ends, 10))
}
// 同名相邻节次合并为连堂大块，与源项目 ScheduleGrid.displayCourses 对齐
function displayCourses(schedule, week, count, colorMap, rowHeight = ROW_HEIGHT) {
  const width = 100 / 7
  const shown = (schedule && schedule.courses || [])
    .filter(item => item.weekday >= 1 && item.weekday <= 7 && (item.weeks && item.weeks.includes(week)))
    .map(item => {
      const adjustment = (item.adjustments || []).find(value => Number(value.week) === week)
      const displayed = adjustment ? { ...item, weekday: adjustment.weekday, start_section: adjustment.start_section,
        end_section: adjustment.end_section, room: adjustment.room || item.room, adjusted: true,
        adjusted_week: adjustment.week } : { ...item, adjusted: false, adjusted_week: null }
      displayed.start_section = Math.max(1, Math.min(count, Number(displayed.start_section) || 1))
      displayed.end_section = Math.max(displayed.start_section, Math.min(count, Number(displayed.end_section) || displayed.start_section))
      return displayed
    })
    .sort((a, b) => a.weekday - b.weekday || a.start_section - b.start_section)
  const merged = []
  shown.forEach(course => {
    const previous = merged[merged.length - 1]
    if (previous && courseKey(previous.name) === courseKey(course.name) && previous.teacher === course.teacher
      && previous.room === course.room && previous.weekday === course.weekday
      && previous.end_section + 1 === course.start_section) {
      previous.end_section = course.end_section
      return
    }
    merged.push(course)
  })
  return merged.map(course => {
    const rows = course.end_section - course.start_section + 1
    // 字号自适应：名字越长字号越小；再按卡片净高钳制行数，放不下就进一步降字号
    const nameLen = (course.name || '').length
    const inner = rows * rowHeight - 18
    const metaFont = inner < 90 ? 14 : 15
    const metaH = 2 * metaFont * 1.25 + 5
    let font = nameLen <= 5 ? 22 : nameLen <= 9 ? 21 : nameLen <= 14 ? 20 : 18
    let maxLines = Math.max(1, Math.floor((inner - metaH) / (font * 1.25)))
    if (maxLines < 2 && font > 15) {
      font = 15
      maxLines = Math.max(1, Math.floor((inner - metaH) / (font * 1.25)))
    }
    return {
      ...course,
      // 与母版一致：网格颜色恒按课名查调色板，保证同名课程同色
      displayColor: colorMap[courseKey(course.name)] || DEFAULT_COLOR,
      slotStyle: `left:${(course.weekday - 1) * width}%;width:${width}%;top:${(course.start_section - 1) * rowHeight}rpx;height:${(course.end_section - course.start_section + 1) * rowHeight}rpx;`,
      jellyStyle: jellyStyle(colorMap[courseKey(course.name)] || DEFAULT_COLOR),
      nameStyle: `font-size:${font}rpx;-webkit-line-clamp:${Math.min(maxLines, 8)};`,
      metaStyle: `font-size:${metaFont}rpx;`,
    }
  })
}

Page({
  openAcademicQuery() { this.setData({ scheduleCenterOpen: false, termSheetOpen: false }); wx.navigateTo({ url: '/pages/academic/academic' }) },
  openImportModal() { this.setData({ scheduleCenterOpen: true }) },
  closeScheduleCenter() { this.setData({ scheduleCenterOpen: false }) },
  chooseCenterImport() { this.setData({ scheduleCenterOpen: false }); this.openFileImportModal() },

  switchTab(e) {
    const tab = (e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.tab) || 'home'
    if (this.data.currentTab === tab) return
    this.setData({ currentTab: tab })
    wx.setNavigationBarTitle({
      title: tab === 'mine' ? '个人中心' : '序时课表'
    })
  },
  clearBackground() {
    if (!this.data.backgroundPath) {
      this.toast('当前已是默认背景')
      return
    }
    wx.removeStorageSync('schedule_background')
    this.setData({ backgroundPath: '' })
    this.toast('已恢复默认背景')
  },
  data: {
    currentTab: 'home', // 'home' | 'mine'
    refreshing: false,
    syncing: false,
    loading: true, schedules: [], schedule: null, scheduleNames: [], scheduleIndex: 0,
    week: 1, weekCount: 20, currentWeekRange: '', weekOpen: false, weekOptions: [],
    weekDays: [], monthLabel: '', gridCourses: [], sections, days, shownSections: sections.slice(0, 10),
    sectionCount: 10, sectionOptions: Array.from({ length: 10 }, (_, index) => `第 ${index + 1} 节`),
    gridHeight: 10 * ROW_HEIGHT, backgroundPath: '', scheduleActive: false, statusText: '',
    detailOpen: false, selectedCourse: null,
    scheduleCenterOpen: false, importOpen: false, importTab: 'excel', importStage: 'setup', importFile: null, semesterName: '', startDate: '', endDate: '', uploading: false,
    importElapsed: 0, importProgressText: '',
    semesterOpen: false, semesterForm: {}, semesterWeeks: 20, semesterSaving: false,
    semesterStatusText: '', semesterStatusClass: 'unset', semesterOriginal: '', semesterChanged: false, calculatedNotice: '',
    termSheetOpen: false, scheduleList: [],
    nightMode: false, privacyOpen: false,
    confirmModal: { visible: false, title: '', content: '', confirmText: '确定', cancelText: '取消', danger: false },
    boundStudent: null,
    actionSheet: { visible: false, itemList: [] },
  },
  onLoad() {
    // 启动秒开优化：首屏直接同步取本地缓存瞬时渲染，0ms 白屏与转圈
    const cached = wx.getStorageSync('schedules_cache')
    if (Array.isArray(cached) && cached.length) {
      this.applySchedules(cached)
      this._initialLoaded = true
    }
  },
  onShow() {
    // 账号关联/解除会清除缓存；回到课表页时同步清除旧账号画面。
    if (!Array.isArray(wx.getStorageSync('schedules_cache'))) {
      this.setData({ schedule: null, schedules: [], scheduleList: [] })
    }
    this.setData({
      backgroundPath: wx.getStorageSync('schedule_background') || '',
      nightMode: wx.getStorageSync('night_mode') === true,
      boundStudent: wx.getStorageSync('bound_student') || null,
    })
    this.applyNavigationBarColor(this.data.nightMode)
    this.hookPrivacyAuthorization()
    this.load()
    this.fetchBoundStudent()
  },
  async fetchBoundStudent() {
    try {
      const binding = await app.request('/api/academic/binding')
      const student = binding && binding.student ? binding.student : null
      this.setData({ boundStudent: student })
      if (student) wx.setStorageSync('bound_student', student)
      else wx.removeStorageSync('bound_student')
    } catch (e) {}
  },
  openAgent() {
    const scheduleId = this.data.schedule && this.data.schedule.id
    wx.navigateTo({ url: `/pages/agent/agent${scheduleId ? `?scheduleId=${scheduleId}` : ''}` })
  },
  openFeedback() {
    const scheduleId = this.data.schedule && this.data.schedule.id
    wx.navigateTo({ url: `/pages/feedback/feedback${scheduleId ? `?scheduleId=${scheduleId}` : ''}` })
  },
  // 主题入口：更换背景 / 切换日夜间（原先顶部的两个图标按钮收敛于此）
  async openThemeSheet() {
    const { tapIndex } = await this.actionSheet([
      { text: '🖼 更换课表背景' },
      { text: this.data.nightMode ? '☀️ 切换日间模式' : '🌙 切换夜间模式' },
    ])
    if (tapIndex === 0) this.chooseBackground()
    if (tapIndex === 1) this.toggleNightMode()
  },
  openSemesterFromSheet() {
    this.setData({ termSheetOpen: false })
    this.openSemester()
  },
  // 隐私接口被拦截时弹出自定义指引弹窗（open-type=agreePrivacyAuthorization），不依赖微信默认弹窗
  hookPrivacyAuthorization() {
    if (this._privacyHooked || !wx.onNeedPrivacyAuthorization) return
    this._privacyHooked = true
    this._privacyHandler = resolve => {
      this._privacyResolve = resolve
      this.setData({ privacyOpen: true })
    }
    wx.onNeedPrivacyAuthorization(this._privacyHandler)
  },
  onUnload() {
    if (this._privacyResolve) this._privacyResolve({ event: 'disagree' })
    if (this._privacyHandler && wx.offNeedPrivacyAuthorization) wx.offNeedPrivacyAuthorization(this._privacyHandler)
    this._privacyResolve = null
    this._privacyHandler = null
    this._privacyHooked = false
  },
  openPrivacyContract() {
    if (wx.openPrivacyContract) wx.openPrivacyContract({ fail: () => this.toast('暂时打不开指引，请稍后再试') })
  },
  onPrivacyAgree() {
    if (this._privacyResolve) { this._privacyResolve({ event: 'agree', buttonId: 'privacy-agree-btn' }); this._privacyResolve = null }
    this.setData({ privacyOpen: false })
  },
  onPrivacyDisagree() {
    if (this._privacyResolve) { this._privacyResolve({ event: 'disagree' }); this._privacyResolve = null }
    this.setData({ privacyOpen: false })
    this.toast('未同意隐私指引，暂不能选择文件')
  },
  applyNavigationBarColor(nightMode) {
    if (!wx.setNavigationBarColor) return
    wx.setNavigationBarColor({
      frontColor: nightMode ? '#ffffff' : '#000000',
      backgroundColor: nightMode ? '#0b1220' : '#f3f6fb',
      fail: () => {},
    })
  },
  async load(preferredId, silent = false) {
    if (this._initialLoaded && silent === false) silent = true
    if (!silent) this.setData({ loading: true })
    try {
      const schedules = await app.request('/api/schedules')
      // 缓存最近一次完整课表：刷新更快，断网时也能兜底展示
      wx.setStorageSync('schedules_cache', schedules)
      this.applySchedules(schedules, preferredId)
      return true
    } catch (error) {
      const cached = wx.getStorageSync('schedules_cache')
      if (Array.isArray(cached) && cached.length) {
        this.applySchedules(cached, preferredId)
        this.toast('网络异常，已展示最近缓存的课表')
      } else {
        if (!silent) this.setData({ loading: false })
        this.toast(error.message)
      }
      return false
    }
  },
  // 导入成功指定的课表优先，并在重新打开或离线时保持。旧切换记录不再生效。
  applySchedules(schedules, preferredId) {
    schedules = schedules.filter(item => item.variant_type !== 'adjusted')
    let index = schedules.findIndex(item => item.id === Number(preferredId))
    if (index >= 0) wx.setStorageSync('latest_import_schedule_id', schedules[index].id)
    if (index < 0) index = schedules.findIndex(item => item.id === Number(wx.getStorageSync('latest_import_schedule_id')))
    if (index < 0 && schedules.length) {
      const latest = schedules.reduce((result, item) => item.id > result.id ? item : result, schedules[0])
      index = schedules.indexOf(latest)
    }
    if (index < 0) index = 0
    const schedule = schedules[index] || null
    if (schedule) wx.setStorageSync('active_schedule_id', schedule.id)
    else wx.removeStorageSync('active_schedule_id')
    const activeId = schedule ? schedule.id : 0
    const scheduleList = schedules.map(item => this.decorateScheduleItem(item, activeId))
    this.setData({
      schedules, schedule, scheduleIndex: index,
      scheduleNames: schedules.map(item => this.scheduleOptionText(item)),
      scheduleList,
      scheduleActive: schedule ? isScheduleActiveToday(schedule) : false,
      statusText: schedule ? scheduleStatus(schedule) : '',
      loading: false,
    })
    this.applyWeek(termWeek(schedule))
  },
  // 页面主体是 scroll-view，页面级下拉刷新不会触发，这里用 scroll-view 自带 refresher
  async onRefresh() {
    this.setData({ refreshing: true })
    try { await this.load(this.data.schedule && this.data.schedule.id, true) }
    finally { this.setData({ refreshing: false }) }
  },
  scheduleOptionText(schedule) {
    const meta = scheduleMeta(schedule)
    let range = ''
    if (schedule.start_date) {
      const start = String(schedule.start_date).slice(5, 10).replace('-', '.')
      const end = schedule.end_date ? String(schedule.end_date).slice(5, 10).replace('-', '.') : '?'
      range = ` · ${start}-${end}`
    }
    return `${schedule.term || schedule.name}${range} · ${scheduleStatus(schedule)} · ${meta.unique}门 ${meta.lessons}课时`
  },
  // 与母版一致：行高按可视区高度均分，整张课表一屏放下（10~12 节自适应）
  computeRowHeight(sectionCount) {
    try {
      if (!this._viewportPx) {
        const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
        this._viewportPx = info.windowHeight
      }
      // 预留：学期条+页面留白约 58px、表头 54px、底部悬浮条与安全区约 110px。
      // 行高上限 100rpx：宁紧勿撑——表格底部留白，视觉与母版一致
      const availablePx = this._viewportPx - 222
      const rowRpx = Math.round((availablePx * 2) / sectionCount)
      return Math.max(72, Math.min(100, rowRpx))
    } catch (error) {
      return ROW_HEIGHT
    }
  },
  applyWeek(week) {
    const count = weekCount(this.data.schedule)
    const safeWeek = Math.max(1, Math.min(count, week))
    const dates = datesForWeek(this.data.schedule, safeWeek)
    const sectionCount = sectionCountFor(this.data.schedule)
    const rowHeight = this.computeRowHeight(sectionCount)
    this.setData({
      week: safeWeek,
      weekCount: count,
      weekIsCurrent: !!this.data.schedule && !!this.data.scheduleActive && safeWeek === termWeek(this.data.schedule),
      currentWeekRange: dates.range,
      weekOptions: buildWeekOptions(this.data.schedule, count, safeWeek),
      weekDays: dates.weekDays,
      monthLabel: dates.monthLabel,
      sectionCount,
      shownSections: sections.slice(0, sectionCount),
      sectionOptions: Array.from({ length: sectionCount }, (_, index) => `第 ${index + 1} 节`),
      rowHeightRpx: rowHeight,
      gridHeight: sectionCount * rowHeight,
      gridCourses: displayCourses(this.data.schedule, safeWeek, sectionCount, buildColorMap(this.data.schedule && this.data.schedule.courses), rowHeight),
    })
  },
  previousWeek() { this.applyWeek(this.data.week - 1) },
  nextWeek() { this.applyWeek(this.data.week + 1) },
  goCurrentWeek() { this.applyWeek(termWeek(this.data.schedule)) },
  // 课表区左右滑动切换周次；纵向滚动与长按拖拽不受影响
  onSwipeStart(event) {
    const touch = event.touches && event.touches[0]
    if (!touch) return
    this._swipe = { x: touch.clientX, y: touch.clientY, t: Date.now() }
  },
  onSwipeEnd(event) {
    const start = this._swipe
    this._swipe = null
    if (!start || this.data.weekOpen) return
    const touch = event.changedTouches && event.changedTouches[0]
    if (!touch) return
    const dx = touch.clientX - start.x
    const dy = touch.clientY - start.y
    // 横向位移需大于 60px、明显大于纵向位移、且时长在 600ms 内，避免误触纵向滚动
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5 || Date.now() - start.t > 600) return
    const target = dx < 0 ? this.data.week + 1 : this.data.week - 1
    if (target < 1 || target > this.data.weekCount) return
    this.applyWeek(target)
  },
  toggleWeekPicker() {
    this.setData({ weekOpen: !this.data.weekOpen })
  },
  selectWeek(event) {
    const week = Number(event.currentTarget.dataset.week)
    this.setData({ weekOpen: false })
    this.applyWeek(week)
  },
  changeSchedule(event) {
    const index = Number(event.detail.value), schedule = this.data.schedules[index]
    if (!schedule) return
    wx.setStorageSync('active_schedule_id', schedule.id)
    const activeId = schedule.id
    const scheduleList = this.data.schedules.map(item => this.decorateScheduleItem(item, activeId))
    this.setData({ schedule, scheduleIndex: index, weekOpen: false,
      scheduleActive: isScheduleActiveToday(schedule), statusText: scheduleStatus(schedule), scheduleList })
    this.applyWeek(termWeek(schedule))
  },
  openTermSheet() {
    if (!this.data.schedules || !this.data.schedules.length) return
    const activeId = this.data.schedule && this.data.schedule.id
    const scheduleList = this.data.schedules.map(item => this.decorateScheduleItem(item, activeId))
    this.setData({ termSheetOpen: true, scheduleList })
  },
  closeTermSheet() {
    this.setData({ termSheetOpen: false })
  },
  selectScheduleItem(event) {
    const id = Number(event.currentTarget.dataset.id)
    const index = this.data.schedules.findIndex(item => item.id === id)
    if (index < 0) return
    const schedule = this.data.schedules[index]
    wx.setStorageSync('active_schedule_id', schedule.id)
    const activeId = schedule.id
    const scheduleList = this.data.schedules.map(item => this.decorateScheduleItem(item, activeId))
    this.setData({
      schedule,
      scheduleIndex: index,
      weekOpen: false,
      termSheetOpen: false,
      scheduleActive: isScheduleActiveToday(schedule),
      statusText: scheduleStatus(schedule),
      scheduleList,
    })
    this.applyWeek(termWeek(schedule))
    this.toast(`已切换至：${schedule.term || schedule.name}`)
  },
  openImportFromSheet() {
    this.closeTermSheet()
    this.onImportTap()
  },
  async syncSchedules() {
    if (this.data.syncing) return
    this.closeTermSheet()
    this.setData({ syncing: true })
    const prevWeek = this.data.week
    try {
      const ok = await this.load(this.data.schedule && this.data.schedule.id, true)
      if (ok) {
        if (prevWeek > 0 && prevWeek <= this.data.weekCount) {
          this.applyWeek(prevWeek)
        }
        wx.showToast({ title: '课表已刷新', icon: 'success', duration: 1800 })
      }
    } catch (error) {
      wx.showToast({ title: error.message || '同步失败，请稍后重试', icon: 'none', duration: 2000 })
    } finally {
      this.setData({ syncing: false })
    }
  },

  decorateScheduleItem(item, activeId) {
    const meta = scheduleMeta(item)
    const active = isScheduleActiveToday(item)
    const status = scheduleStatus(item)
    let dateRange = ''
    if (item.start_date) {
      const start = String(item.start_date).slice(5, 10).replace('-', '.')
      const end = item.end_date ? String(item.end_date).slice(5, 10).replace('-', '.') : '?'
      dateRange = `${start} - ${end}`
    }
    let statusType = 'past'
    if (active) statusType = 'active'
    else if (status === '未开学') statusType = 'future'

    return {
      ...item,
      displayName: item.term || item.name,
      dateRange,
      statusText: status,
      statusType,
      uniqueCount: meta.unique,
      lessonCount: meta.lessons,
      isSelected: item.id === activeId,
      isAdjusted: item.variant_type === 'adjusted',
    }
  },

  buildDetailCourse(course) {
    const start = sections[(course.start_section || 1) - 1]
    const end = sections[(course.end_section || 1) - 1]
    return {
      ...course,
      weekdayText: days[(course.weekday || 1) - 1],
      sectionText: `第 ${course.start_section}-${course.end_section} 节`,
      timeText: start && end ? `${start.start}-${end.end}` : '时间待定',
      weeksText: formatWeeks(course.weeks),
    }
  },
  openCourseDetail(event) {
    const course = event.currentTarget.dataset.course
    if (!course) return
    this.setData({
      detailOpen: true,
      selectedCourse: this.buildDetailCourse(course),
    })
  },
  closeCourseDetail() { this.setData({ detailOpen: false, selectedCourse: null }) },

  // ===== 课程移动（长按进入移动模式，点按目标格确认） =====

  // ===== 学期设置 =====
  openSemester() {
    const schedule = this.data.schedule
    if (!schedule) return
    const form = {
      name: schedule.name || '', term: schedule.term || '',
      start_date: (schedule.start_date || '').slice(0, 10), end_date: (schedule.end_date || '').slice(0, 10),
    }
    this.setData({ semesterOpen: true, semesterWeeks: weekCount(schedule), semesterForm: form,
      semesterOriginal: JSON.stringify(form), semesterChanged: false, calculatedNotice: '' })
    this.updateSemesterStatus()
  },
  // 状态卡四态：未设置 / 未开学 / 进行中 / 历史学期，对齐源项目 SemesterModal
  updateSemesterStatus() {
    const form = this.data.semesterForm
    const weeks = this.data.semesterWeeks
    const start = localDate(form.start_date)
    let statusClass = 'unset', statusText = '尚未设置开学日期'
    if (start) {
      const end = new Date(start)
      end.setDate(end.getDate() + weeks * 7 - 1)
      const today = new Date(isoDate(new Date()))
      if (today < new Date(isoDate(start))) { statusClass = 'future'; statusText = '未开学 · 将在开学后自动生效' }
      else if (today > end) { statusClass = 'past'; statusText = '历史学期 · 已结束' }
      else {
        const monday = new Date(start)
        monday.setDate(monday.getDate() - ((monday.getDay() || 7) - 1))
        const current = Math.min(weeks, Math.floor((today - monday) / 86400000 / 7) + 1)
        statusClass = 'active'; statusText = `进行中 · 当前为第 ${current} 周`
      }
    }
    this.setData({ semesterStatusText: statusText, semesterStatusClass: statusClass,
      semesterChanged: JSON.stringify(form) !== this.data.semesterOriginal })
  },
  closeSemester() { if (!this.data.semesterSaving) this.setData({ semesterOpen: false }) },
  semesterField(event) {
    this.setData({ [`semesterForm.${event.currentTarget.dataset.key}`]: event.detail.value })
    this.updateSemesterStatus()
  },
  setSemesterWeeks(event) {
    this.setData({ semesterWeeks: Math.max(1, Math.min(30, Number(event.detail.value) || 20)) })
    this.updateSemesterStatus()
  },
  calculateSemesterEnd() {
    const start = localDate(this.data.semesterForm.start_date)
    if (!start) return this.toast('请先选择开学日期')
    start.setDate(start.getDate() + this.data.semesterWeeks * 7 - 1)
    this.setData({ 'semesterForm.end_date': isoDate(start),
      calculatedNotice: `已按 ${this.data.semesterWeeks} 周推算，结束日期为 ${isoDate(start)}` })
    this.updateSemesterStatus()
  },
  async saveSemester() {
    const form = this.data.semesterForm
    if (!String(form.name || '').trim()) return this.toast('课表名称不能为空')
    if (form.start_date && form.end_date && form.end_date < form.start_date) return this.toast('结束日期不能早于开学日期')
    this.setData({ semesterSaving: true })
    try {
      await app.request(`/api/schedules/${this.data.schedule.id}`, { method: 'PUT', data: form })
      this.setData({ semesterOpen: false }); await this.load(this.data.schedule.id); this.toast('学期设置已保存')
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ semesterSaving: false }) }
  },
  // ===== 单周调课弹窗 =====

  // ===== 调课中心 =====

  // 调课记录挂在可编辑副本上；原始课表的调课中心为空时指向它的（调）版本

  // ===== 调课通知图片识别 =====

  toggleNightMode() {
    const nightMode = !this.data.nightMode
    wx.setStorageSync('night_mode', nightMode)
    this.setData({ nightMode })
    this.applyNavigationBarColor(nightMode)
  },
  async chooseBackground() {
    const items = [
      { text: '调整当前背景显示区域', danger: false },
      { text: '更换背景', danger: false },
      { text: '恢复默认背景', danger: true },
    ]
    const { tapIndex } = await this.actionSheet(items)
    if (tapIndex < 0) return
    if (tapIndex === 0) {
      if (this.data.backgroundPath) {
        this.cropBackground(this.data.backgroundPath)
      } else {
        this.toast('当前为默认背景，请先更换背景')
      }
      return
    }
    if (tapIndex === 1) {
      this.pickAndCropBackground(true)
      return
    }
    if (tapIndex === 2) {
      if (!this.data.backgroundPath) {
        this.toast('当前已是默认背景')
        return
      }
      wx.removeStorageSync('schedule_background')
      this.setData({ backgroundPath: '' })
      this.toast('已恢复默认背景')
      return
    }
  },
  pickAndCropBackground(needCrop = true) {
    const onSelected = tempFilePath => {
      if (needCrop) {
        this.cropBackground(tempFilePath)
      } else {
        this.saveBackgroundFile(tempFilePath)
      }
    }
    if (wx.chooseMedia) {
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album'],
        success: ({ tempFiles }) => {
          if (tempFiles && tempFiles[0]) onSelected(tempFiles[0].tempFilePath)
        },
        fail: error => this.pickerFail(error),
      })
    } else {
      wx.chooseImage({
        count: 1,
        sourceType: ['album'],
        success: ({ tempFilePaths }) => {
          if (tempFilePaths && tempFilePaths[0]) onSelected(tempFilePaths[0])
        },
        fail: error => this.pickerFail(error),
      })
    }
  },
  cropBackground(filePath) {
    if (!filePath) return
    if (wx.cropImage) {
      wx.cropImage({
        src: filePath,
        cropScale: '9:16',
        success: ({ tempFilePath }) => {
          this.saveBackgroundFile(tempFilePath)
        },
        fail: error => {
          const msg = (error && error.errMsg) || ''
          if (/cancel/i.test(msg)) return
          this.saveBackgroundFile(filePath)
        },
      })
    } else {
      this.saveBackgroundFile(filePath)
    }
  },
  saveBackgroundFile(tempFilePath) {
    const fs = wx.getFileSystemManager && wx.getFileSystemManager()
    const applyPath = path => {
      wx.setStorageSync('schedule_background', path)
      this.setData({ backgroundPath: path })
      this.toast('背景已更新')
    }
    if (!fs || !fs.saveFile) {
      return applyPath(tempFilePath)
    }
    fs.saveFile({
      tempFilePath,
      success: ({ savedFilePath }) => applyPath(savedFilePath),
      fail: () => applyPath(tempFilePath),
    })
  },
  async deleteSchedule() {
    const schedule = this.data.schedule
    if (!schedule) return
    if (schedule.academic_student_id) { this.openAcademicQuery(); return }
    const result = await this.modal({
      title: '删除课表',
      content: `确认删除“${schedule.term || schedule.name}”？其中全部课程也会删除。`,
      confirmText: '删除',
      danger: true,
    })
    if (!result.confirm) return
    try {
      await app.request(`/api/schedules/${schedule.id}`, { method: 'DELETE' })
      this.setData({ semesterOpen: false })
      await this.load()
      this.toast('课表已删除')
    } catch (error) { this.toast(error.message) }
  },
  // ===== 导入（Excel 课表导入）=====
  openFileImportModal() {
    this.setData({ importOpen: true, importTab: 'excel' })
  },
  onImportTap() {
    this.openImportModal()
  },
  chooseFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['xlsx', 'xlsm', 'xls'],
      success: ({ tempFiles }) => this.prepareImport(tempFiles[0]),
      fail: error => this.pickerFail(error),
    })
  },
  prepareImport(file) {
    if (!file) return
    const path = file.path || file.tempFilePath
    if (!path) return this.toast('无法读取所选文件')
    const name = file.name || path.split(/[\\/]/).pop() || '课表文件'
    // 优先从文件名推测学期日期（如 2025-2026-1.xlsx），与源项目 suggestSemesterDates 对齐
    const guessed = suggestSemesterDates(name)
    const start = guessed ? guessed.start : (this.data.schedule && this.data.schedule.start_date || isoDate(new Date()))
    const end = guessed ? guessed.end : isoDate(new Date(new Date(start).getTime() + (20 * 7 - 1) * 86400000))
    this.setData({
      importOpen: true,
      importTab: 'excel',
      importStage: 'setup',
      importFile: { name, path },
      semesterName: defaultTermName(start),
      startDate: String(start).slice(0,10),
      endDate: String(end).slice(0,10),
    })
  },
  setSemesterName(event) { this.setData({ semesterName: event.detail.value }) },
  setStartDate(event) { this.setData({ startDate: event.detail.value }) },
  setEndDate(event) { this.setData({ endDate: event.detail.value }) },
  // 导入进度：分段计时文案，对齐源项目 ImporterModal 的等待体验
  startImportTimer() {
    this.setData({ importElapsed: 0, importProgressText: '正在安全读取工作簿…' })
    this.stopImportTimer()
    this.importTimer = setInterval(() => {
      const elapsed = (this.data.importElapsed || 0) + 1
      const text = elapsed < 5 ? '正在安全读取工作簿…'
        : elapsed < 45 ? `正在识别课程信息… ${elapsed} 秒`
        : '在线解析较慢，正在准备本地解析兜底…'
      this.setData({ importElapsed: elapsed, importProgressText: text })
    }, 1000)
  },
  stopImportTimer() {
    if (this.importTimer) { clearInterval(this.importTimer); this.importTimer = null }
  },
  closeImport() {
    if (this.data.uploading) return
    this.stopImportTimer()
    this.setData({ importOpen: false, importStage: 'setup', importFile: null })
  },
  async confirmImportOverwrite(name) {
    const result = await this.modal({
      title: '课表名称重复',
      content: `已存在课表“${name}”。覆盖后，原课表中的课程将替换为本次上传内容，是否继续？`,
      confirmText: '覆盖',
      cancelText: '取消',
      danger: true,
    })
    return Boolean(result.confirm)
  },
  async upload() {
    if (!this.data.importFile || !this.data.importFile.path) return this.toast('请重新选择课表文件')
    const semesterName = this.data.semesterName.trim()
    if (!semesterName) return this.toast('请填写学期名称')
    if (this.data.endDate < this.data.startDate) return this.toast('结束日期不能早于开始日期')
    let overwrite = false
    const existing = (this.data.schedules || []).find(item =>
      ['original', 'draft'].includes(item.variant_type) &&
      [item.name, item.term].some(value => String(value || '').trim() === semesterName))
    if (existing) {
      overwrite = await this.confirmImportOverwrite(existing.name || existing.term || semesterName)
      if (!overwrite) return
    }
    this.setData({ uploading: true })
    this.startImportTimer()
    try {
      const submit = confirmed => app.upload('/api/import', this.data.importFile.path, {
        term_name: semesterName, start_date: this.data.startDate,
        end_date: this.data.endDate, overwrite: confirmed ? 'true' : 'false',
      })
      let result
      try {
        result = await submit(overwrite)
      } catch (error) {
        if (error.code !== 'schedule_exists' || overwrite) throw error
        this.stopImportTimer()
        const confirmed = await this.confirmImportOverwrite(
          error.data && error.data.schedule_name || semesterName)
        if (!confirmed) return
        overwrite = true
        this.startImportTimer()
        result = await submit(true)
      }
      if (result.imported) {
        this.setData({ importOpen: false, importStage: 'setup', importFile: null }); await this.load(result.schedule_id)
        // 与“切换课表”口径一致：同名的多时段/单双周记录只计 1 门课。
        const importedCount = scheduleMeta(this.data.schedule).unique
        this.toast(result.replaced ? `已覆盖当前学期，共 ${importedCount} 门课程`
          : `已导入 ${importedCount} 门课程`)
      } else {
        throw new Error('未识别出完整课表，请检查 Excel 内容或换一份整学期课表')
      }
    } catch (error) { this.toast(error.message) }
    finally { this.stopImportTimer(); this.setData({ uploading: false }) }
  },
  onShareAppMessage() {
    return { title: '序时 · 简洁好用的课程表', path: '/pages/index/index' }
  },
  onShareTimeline() {
    return { title: '序时 · 简洁好用的课程表' }
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
  actionSheet(itemList = []) {
    return new Promise(resolve => {
      this._actionSheetResolve = resolve
      this.setData({
        actionSheet: {
          visible: true,
          itemList: itemList.map(item => (typeof item === 'string' ? { text: item, danger: false } : item)),
        }
      })
    })
  },
  onActionSheetSelect(e) {
    const tapIndex = Number(e.currentTarget.dataset.index)
    this.setData({ 'actionSheet.visible': false })
    if (this._actionSheetResolve) {
      const resolve = this._actionSheetResolve
      this._actionSheetResolve = null
      resolve({ tapIndex })
    }
  },
  onActionSheetCancel() {
    this.setData({ 'actionSheet.visible': false })
    if (this._actionSheetResolve) {
      const resolve = this._actionSheetResolve
      this._actionSheetResolve = null
      resolve({ tapIndex: -1 })
    }
  },
  noop() {},
  // 相册/相机/文件选择的失败统一提示：区分隐私协议未同意与权限未授权
  pickerFail(error) {
    const msg = (error && error.errMsg) || ''
    if (error && error.errno === 112) {
      return this.toast('该文件权限尚未在小程序隐私保护指引中声明，请联系开发者更新指引')
    }
    if (/privacy/i.test(msg)) return this.toast('需先同意《用户隐私保护指引》后再选择')
    if (/auth|deny|permission/i.test(msg)) return this.toast('请在设置中开启相册/相机权限')
  },
  toast(title) { wx.showToast({ title, icon: 'none' }) },
})
