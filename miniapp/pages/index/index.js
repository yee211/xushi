const app = getApp()
const days = ['周一','周二','周三','周四','周五','周六','周日']
const dayShortNames = ['一','二','三','四','五','六','日']
const ROW_HEIGHT = 112
const DEFAULT_COLOR = '#5B8DEF'
function operationKey(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}
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
  const elapsed = Math.floor((new Date(isoDate(new Date())) - new Date(isoDate(start))) / 86400000)
  return Math.max(1, Math.min(weekCount(schedule), Math.floor(elapsed / 7) + 1))
}
function formatWeeks(weeks) {
  if (!weeks || !weeks.length) return '每周'
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
function parseWeeks(text) {
  const result = []
  String(text || '').split(/[,，]/).forEach(part => {
    const [a, b] = part.trim().split('-').map(Number)
    if (a && b) for (let i = a; i <= b; i++) result.push(i)
    else if (a) result.push(a)
  })
  return [...new Set(result)].filter(n => n >= 1 && n <= 30).sort((a, b) => a - b)
}
const sectionPickerOptions = Array.from({ length: 12 }, (_, index) => `第 ${index + 1} 节`)
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
function importEngineText(engine) {
  if (engine === 'ai') return '在线解析'
  const fallback = /^excel-fallback\((.+)\)$/.exec(String(engine || ''))
  if (fallback) {
    const reasons = {
      'ai-not-configured': '在线解析未配置',
      'ai-timeout': '在线解析超时',
      'ai-invalid-schema': '在线解析结果无效',
      'ai-unavailable': '在线解析服务异常',
    }
    const reason = reasons[fallback[1]] || (fallback[1].startsWith('ai-http-') ? `在线解析 ${fallback[1].slice(8)}` : '在线解析不可用')
    return `本地解析 · ${reason}`
  }
  return '本地解析'
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
    .filter(item => item.weekday >= 1 && item.weekday <= 7 && (!item.weeks || !item.weeks.length || item.weeks.includes(week)))
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
  data: {
    refreshing: false,
    syncing: false,
    // 功能开关：仅隐藏入口，相关逻辑全部保留；恢复入口改回 true 即可
    showAddCourse: false,
    showAdjustCenter: false,
    loading: true, schedules: [], schedule: null, scheduleNames: [], scheduleIndex: 0,
    week: 1, weekCount: 20, currentWeekRange: '', weekOpen: false, weekOptions: [],
    weekDays: [], monthLabel: '', gridCourses: [], sections, days, shownSections: sections.slice(0, 10),
    sectionCount: 10, sectionOptions: Array.from({ length: 10 }, (_, index) => `第 ${index + 1} 节`),
    gridHeight: 10 * ROW_HEIGHT, backgroundPath: '', scheduleActive: false, statusText: '',
    detailOpen: false, selectedCourse: null, courseRecords: [], courseRecordsLoading: false,
    importOpen: false, importTab: 'excel', importStage: 'setup', importFile: null, semesterName: '', startDate: '', endDate: '', uploading: false,
    importElapsed: 0, importProgressText: '',
    semesterOpen: false, semesterForm: {}, semesterWeeks: 20, semesterSaving: false,
    adjustmentOpen: false, adjustmentForm: {}, adjustmentSaving: false,
    recordsOpen: false, records: [], recordsLoading: false, recordsError: '', expandedRecordId: null, recordsHint: '',
    semesterStatusText: '', semesterStatusClass: 'unset', semesterOriginal: '', semesterChanged: false, calculatedNotice: '',
    moveMode: false, movingCourse: null, moveOpen: false, moveForm: null, moveSaving: false,
    parseStage: 'idle', parseItems: [], parseFile: '', parsePath: '', parseApplying: false,
    termSheetOpen: false, scheduleList: [],
    shareModalOpen: false, shareCode: '', shareGenerating: false,
    shareImportModalOpen: false, inputShareCode: '', sharePreview: null,
    checkingShareCode: false, importingShare: false,
    courseEditorOpen: false, courseSaving: false, courseForm: null,
    editorColors: [DEFAULT_COLOR, ...courseColors],
    sectionPickerOptions,
    nightMode: false, privacyOpen: false,
    confirmModal: { visible: false, title: '', content: '', confirmText: '确定', cancelText: '取消', danger: false },
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
    this.setData({ backgroundPath: wx.getStorageSync('schedule_background') || '', nightMode: wx.getStorageSync('night_mode') === true })
    this.applyNavigationBarColor(this.data.nightMode)
    this.hookPrivacyAuthorization()
    this.load()
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
  // 选中优先级：指定 id > 本地记忆 > 包含今天的进行中学期 > 第一个
  applySchedules(schedules, preferredId) {
    const saved = wx.getStorageSync('active_schedule_id')
    let index = schedules.findIndex(item => item.id === (preferredId || saved))
    if (index < 0) {
      // 优先定位包含今天的进行中学期，与源项目 findCurrentSchedule 对齐
      index = schedules.findIndex(item => isScheduleActiveToday(item))
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
    if (!start || this.data.moveMode || this.data.weekOpen) return
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
        wx.showToast({ title: '课表已同步到最新', icon: 'success', duration: 1800 })
      }
    } catch (error) {
      wx.showToast({ title: error.message || '同步失败，请稍后重试', icon: 'none', duration: 2000 })
    } finally {
      this.setData({ syncing: false })
    }
  },
  async openShareModal() {
    const schedule = this.data.schedule
    if (!schedule || !schedule.id) {
      this.toast('当前没有可分享的课表')
      return
    }
    this.closeTermSheet()
    this.setData({ shareModalOpen: true, shareCode: '', shareGenerating: true })
    try {
      const res = await app.request(`/api/schedules/${schedule.id}/share`, { method: 'POST' })
      this.setData({
        shareCode: res.code,
        shareGenerating: false,
      })
    } catch (err) {
      this.setData({ shareModalOpen: false, shareGenerating: false })
      this.toast(err.message || '生成分享码失败')
    }
  },
  closeShareModal() {
    this.setData({ shareModalOpen: false })
  },
  copyShareCode() {
    const code = this.data.shareCode
    if (!code) return
    const schedule = this.data.schedule
    const name = schedule ? (schedule.name || schedule.term) : '课表'
    const text = `【序时课表】你的好友向你分享了课表“${name}”，在小程序内点击「口令导入」输入口令【${code}】即可一键导入！`
    wx.setClipboardData({
      data: text,
      success: () => {
        this.toast('口令已复制到剪贴板')
      }
    })
  },
  openShareImportModal() {
    this.closeTermSheet()
    this.setData({
      shareImportModalOpen: true,
      inputShareCode: '',
      sharePreview: null,
      checkingShareCode: false,
      importingShare: false,
    })
  },
  closeShareImportModal() {
    this.setData({ shareImportModalOpen: false })
  },
  async pasteShareCode() {
    try {
      const clip = await wx.getClipboardData()
      if (clip && clip.data) {
        const match = String(clip.data).match(/\b([A-HJ-NP-Z2-9]{6})\b/i) || String(clip.data).match(/【([A-HJ-NP-Z2-9]{6})】/i)
        const code = (match ? match[1] : clip.data.trim().slice(0, 6)).toUpperCase()
        this.setData({ inputShareCode: code })
        if (code.length === 6) {
          this.previewShareCode(code)
        }
      }
    } catch (e) {
      // ignore
    }
  },
  onShareCodeInput(e) {
    const val = (e.detail.value || '').trim().toUpperCase()
    this.setData({ inputShareCode: val })
    if (val.length === 6) {
      this.previewShareCode(val)
    } else {
      this.setData({ sharePreview: null, checkingShareCode: false })
    }
  },
  async previewShareCode(code) {
    if (!code || code.length !== 6) return
    this.setData({ checkingShareCode: true, sharePreview: null })
    try {
      const info = await app.request(`/api/schedules/share/${code}`, { method: 'GET' })
      this.setData({ sharePreview: info, checkingShareCode: false })
    } catch (err) {
      this.setData({ checkingShareCode: false, sharePreview: null })
      this.toast(err.message || '查询分享码失败')
    }
  },
  async confirmImportShare() {
    const code = this.data.inputShareCode
    if (!code || code.length !== 6) {
      this.toast('请输入完整的 6 位分享码')
      return
    }
    this.setData({ importingShare: true })
    try {
      const res = await app.request(`/api/schedules/share/${code}/import`, { method: 'POST' })
      this.toast(`导入成功！共导入 ${res.courses_imported} 门课程`)
      this.setData({ shareImportModalOpen: false, importingShare: false })
      if (res.schedule_id) {
        wx.setStorageSync('active_schedule_id', res.schedule_id)
        await this.load(res.schedule_id)
      } else {
        await this.load()
      }
    } catch (err) {
      this.setData({ importingShare: false })
      this.toast(err.message || '导入课表失败')
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
  async ensureEditable(courseId) {
    const schedule = this.data.schedule
    return {
      scheduleId: schedule ? schedule.id : null,
      courseId: courseId || null,
      course_map: {},
      fromOriginal: false,
    }
  },
  closeCourseEditor() {
    if (this.data.courseSaving) return
    this.setData({ courseEditorOpen: false })
  },
  async addCourse() {
    if (!this.data.schedule) return this.toast('请先上传一张课表')
    // 新增课程是对当前课表的补充，不属于调课，不应为原表自动创建调课版。
    const totalWeeks = this.data.weekCount || 16
    this.setData({
      courseEditorOpen: true,
      courseSaving: false,
      courseForm: {
        id: null,
        scheduleId: this.data.schedule.id,
        name: '',
        teacher: '',
        room: '',
        weekday: 1,
        startSection: 1,
        endSection: 2,
        weeks: `1-${totalWeeks}`,
        color: DEFAULT_COLOR,
        adjustedWeek: null,
      },
    })
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
  async openCourseDetail(event) {
    const course = event.currentTarget.dataset.course
    if (!course) return
    if (this.data.moveMode) {
      // 移动模式下点按已选课程即取消
      if (this.data.movingCourse && this.data.movingCourse.id === course.id) this.cancelMoveMode()
      return
    }
    this.setData({
      detailOpen: true,
      selectedCourse: this.buildDetailCourse(course),
      courseRecords: [], courseRecordsLoading: true,
    })
    try {
      const records = await app.request(`/api/adjustments/records?schedule_id=${this.data.schedule.id}`)
      const courseRecords = this.filterCourseRecords(records, course.id)
      this.setData({ courseRecords, courseRecordsLoading: false })
    } catch (error) { this.setData({ courseRecordsLoading: false }) }
  },
  // 回滚/撤销后用网格中的最新状态替换详情弹窗内容，避免按钮停留在旧状态
  refreshSelectedCourse(courseId) {
    const latest = this.data.gridCourses.find(item => item.id === courseId)
    if (latest && this.data.detailOpen) this.setData({ selectedCourse: this.buildDetailCourse(latest) })
  },
  filterCourseRecords(records, courseId) {
    return (records || [])
      .filter(record => record.course_id === courseId
        || (record.details || []).some(detail => detail && detail.course_id === courseId))
      .map(record => ({
        ...record,
        timeText: String(record.created_at || '').replace('T', ' ').slice(0, 16),
        diffs: this.recordDiffs(record, courseId).map((text, index) => ({ text, _idx: index })),
        canRevoke: (record.details || []).some(detail => detail && detail.course_id === courseId && detail.can_revoke),
        revokeDetail: (record.details || []).find(detail => detail && detail.course_id === courseId && detail.can_revoke)
          || (record.details || [])[0] || null,
      }))
  },
  recordDiffs(record, courseId) {
    return (record.details || [])
      .filter(detail => !detail || !detail.course_id || detail.course_id === courseId)
      .map(detail => {
        if (detail.label && (detail.old !== undefined || detail.new !== undefined) && !detail.old_weekday) {
          return `${detail.label}：${detail.old} → ${detail.new}`
        }
        const oldPlace = detail.old_weekday ? `${days[detail.old_weekday - 1]} 第${detail.old_start_section}-${detail.old_end_section}节` : ''
        const newPlace = detail.new_weekday ? `${days[detail.new_weekday - 1]} 第${detail.new_start_section}-${detail.new_end_section}节` : ''
        const lines = [`${oldPlace} → ${newPlace}`]
        if ((detail.old_room || '') !== (detail.new_room || '')) lines.push(`教室：${detail.old_room || '未设置'} → ${detail.new_room || '未设置'}`)
        return lines.join('，')
      })
  },
  closeCourseDetail() { this.setData({ detailOpen: false, selectedCourse: null, courseRecords: [] }) },
  async editSelectedCourse() {
    const course = this.data.selectedCourse
    if (!course) return
    try {
      const editable = await this.ensureEditable(course.id)
      const totalWeeks = this.data.weekCount || 16
      this.setData({
        detailOpen: false,
        courseEditorOpen: true,
        courseSaving: false,
        courseForm: {
          id: editable.courseId,
          scheduleId: editable.scheduleId,
          name: course.name || '',
          teacher: course.teacher || '',
          room: course.room || '',
          weekday: course.weekday || 1,
          startSection: course.start_section || 1,
          endSection: course.end_section || 2,
          weeks: formatWeeksInput(course.weeks) || `1-${totalWeeks}`,
          color: course.color || DEFAULT_COLOR,
          adjustedWeek: course.adjusted ? this.data.week : null,
          linkAdjustments: editable.fromOriginal,
        },
      })
    } catch (error) { this.toast(error.message) }
  },
  courseField(event) {
    const key = event.currentTarget.dataset.key
    this.setData({ [`courseForm.${key}`]: event.detail.value })
  },
  courseWeekday(event) {
    this.setData({ 'courseForm.weekday': Number(event.detail.value) + 1 })
  },
  courseStartSection(event) {
    this.setData({ 'courseForm.startSection': Number(event.detail.value) + 1 })
  },
  courseEndSection(event) {
    this.setData({ 'courseForm.endSection': Number(event.detail.value) + 1 })
  },
  pickCourseColor(event) {
    this.setData({ 'courseForm.color': event.currentTarget.dataset.color })
  },
  async saveCourse() {
    const form = this.data.courseForm
    if (!form) return
    if (!form.name || !form.name.trim()) return this.toast('请填写课程名称')
    if (form.endSection < form.startSection) return this.toast('结束节次不能早于开始节次')
    const weeks = parseWeeks(form.weeks)
    if (!weeks.length) return this.toast('请填写有效上课周次，如 1-16')
    const payload = {
      schedule_id: form.scheduleId,
      name: form.name.trim(),
      teacher: (form.teacher || '').trim(),
      room: (form.room || '').trim(),
      weekday: form.weekday,
      start_section: form.startSection,
      end_section: form.endSection,
      weeks,
      color: form.color || DEFAULT_COLOR,
    }
    this.setData({ courseSaving: true })
    try {
      const courseUrl = form.id
        ? `/api/courses/${form.id}${form.linkAdjustments ? '?link_adjustments=true' : ''}`
        : '/api/courses'
      await app.request(courseUrl, {
        method: form.id ? 'PUT' : 'POST',
        data: payload,
      })
      if (form.id && form.adjustedWeek) {
        try {
          await app.request(`/api/courses/${form.id}/adjustments/${form.adjustedWeek}`, { method: 'DELETE' })
        } catch (_) {}
      }
      const keepWeek = this.data.week
      this.setData({ courseEditorOpen: false })
      await this.load(form.scheduleId, true)
      if (keepWeek) this.applyWeek(keepWeek)
      this.toast(form.id ? '课程已保存' : '课程已添加')
    } catch (error) {
      this.toast(error.message)
    } finally {
      this.setData({ courseSaving: false })
    }
  },
  async removeCourse() {
    const form = this.data.courseForm
    if (!form || !form.id) return
    const result = await this.modal({
      title: '删除课程',
      content: `确认删除“${form.name}”？`,
      confirmText: '删除',
      danger: true,
    })
    if (!result.confirm) return
    this.setData({ courseSaving: true })
    try {
      await app.request(`/api/courses/${form.id}`, { method: 'DELETE' })
      const keepWeek = this.data.week
      this.setData({ courseEditorOpen: false })
      await this.load(form.scheduleId, true)
      if (keepWeek) this.applyWeek(keepWeek)
      this.toast('课程已删除')
    } catch (error) {
      this.toast(error.message)
    } finally {
      this.setData({ courseSaving: false })
    }
  },
  // ===== 课程移动（长按进入移动模式，点按目标格确认） =====
  startMoveMode(event) {
    const course = event.currentTarget.dataset.course
    if (!course || this.data.moveMode) return
    this.setData({ moveMode: true, movingCourse: course, weekOpen: false })
    this.toast('已进入移动模式：点按目标位置')
  },
  cancelMoveMode() { this.setData({ moveMode: false, movingCourse: null }) },
  cellTap(event) {
    if (!this.data.moveMode) return
    const course = this.data.movingCourse
    if (!course) return
    const targetDay = Number(event.currentTarget.dataset.day)
    const targetSection = Number(event.currentTarget.dataset.section)
    if (!targetDay || !targetSection) return
    const rawDuration = course.end_section - course.start_section + 1
    const duration = rawDuration <= 2 ? 2 : rawDuration
    const blockIndex = Math.floor((targetSection - 1) / 2)
    const maxStart = 2 * Math.floor((this.data.sectionCount - duration) / 2) + 1
    const start = Math.max(1, Math.min(maxStart, blockIndex * 2 + 1))
    const end = start + duration - 1
    const conflict = this.data.gridCourses.some(item => item.id !== course.id
      && item.weekday === targetDay && start <= item.end_section && end >= item.start_section)
    if (conflict) return this.toast('目标时段与现有课程冲突')
    const changed = targetDay !== course.weekday || start !== course.start_section || end !== course.end_section
    if (!changed) return this.toast('请选择与原位置不同的位置')
    this.setData({
      moveMode: false, movingCourse: null, moveOpen: true,
      moveForm: { course, weekday: targetDay, start_section: start, end_section: end },
    })
  },
  closeMove() { if (!this.data.moveSaving) this.setData({ moveOpen: false }) },
  async saveMove() {
    const move = this.data.moveForm
    const week = this.data.week
    if (!move) return
    this.setData({ moveSaving: true })
    try {
      const editable = await this.ensureEditable(move.course.id)
      const adjusted = this.data.schedules.find(item => item.id === editable.scheduleId)
      const base = (adjusted && adjusted.courses || []).find(item => item.id === editable.courseId)
        || (adjusted && adjusted.courses || []).find(item => item.id === move.course.id) || move.course
      // 移回原时间但本周调课改过教室时，保留教室变更（与母版判定一致）
      const backToOrigin = base.weekday === move.weekday && base.start_section === move.start_section
        && base.end_section === move.end_section && (base.room || '') === (move.course.room || '')
      if (backToOrigin && move.course.adjusted_week) {
        await app.request(`/api/courses/${editable.courseId}/adjustments/${week}`, { method: 'DELETE' })
        this.toast('已移回原位置，调课已取消')
      } else {
        await app.request(`/api/courses/${editable.courseId}/adjustments/${week}?source=drag`, { method: 'PUT',
          header: { 'Idempotency-Key': operationKey('move') }, data: {
          week, weekday: move.weekday, start_section: move.start_section,
          end_section: move.end_section, room: move.course.room || '',
        } })
        this.toast(`第 ${week} 周课程已调整`)
      }
      this.setData({ moveOpen: false, moveForm: null })
      await this.load(editable.scheduleId); this.applyWeek(week)
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ moveSaving: false }) }
  },
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
        const current = Math.min(weeks, Math.floor((today - start) / 86400000 / 7) + 1)
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
  openAdjustment() {
    const course = this.data.selectedCourse
    if (!course) return
    this.setData({ detailOpen: false, adjustmentOpen: true, adjustmentForm: {
      course, weekday: course.weekday, start_section: course.start_section,
      end_section: course.end_section, room: course.room || '',
    } })
  },
  closeAdjustment() { if (!this.data.adjustmentSaving) this.setData({ adjustmentOpen: false }) },
  adjustmentField(event) { this.setData({ [`adjustmentForm.${event.currentTarget.dataset.key}`]: event.detail.value }) },
  adjustmentPicker(event) { this.setData({ [`adjustmentForm.${event.currentTarget.dataset.key}`]: Number(event.detail.value) + 1 }) },
  async saveAdjustment() {
    const form = this.data.adjustmentForm
    const week = this.data.week
    if (Number(form.end_section) < Number(form.start_section)) return this.toast('结束节次不能早于开始节次')
    this.setData({ adjustmentSaving: true })
    try {
      const editable = await this.ensureEditable(form.course.id)
      const result = await app.request(`/api/courses/${editable.courseId}/adjustments/${week}?source=manual`, { method: 'PUT',
        header: { 'Idempotency-Key': operationKey('adjust') }, data: {
        week, weekday: Number(form.weekday), start_section: Number(form.start_section),
        end_section: Number(form.end_section), room: String(form.room || '').trim(),
      } })
      this.setData({ adjustmentOpen: false }); await this.load(editable.scheduleId); this.applyWeek(week)
      this.toast(result.unchanged ? '调课内容没有变化' : '本周调课已保存')
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ adjustmentSaving: false }) }
  },
  async cancelAdjustmentFromModal() {
    const course = this.data.adjustmentForm.course
    const week = this.data.week
    if (!course || !course.adjusted) return
    try {
      await app.request(`/api/courses/${course.id}/adjustments/${week}`, { method: 'DELETE' })
      this.setData({ adjustmentOpen: false }); await this.load(this.data.schedule.id); this.applyWeek(week); this.toast('已恢复原上课时间')
    } catch (error) { this.toast(error.message) }
  },
  // ===== 调课中心 =====
  async openRecords() {
    if (!this.data.schedule) return
    this.setData({ recordsOpen: true, records: [], recordsLoading: true, recordsError: '', parseStage: 'idle', parseItems: [], recordsHint: '' })
    try {
      const records = await app.request(`/api/adjustments/records?schedule_id=${this.data.schedule.id}`)
      const decorated = this.decorateRecords(records)
      const counterpart = this.counterpartSchedule()
      this.setData({
        records: decorated,
        recordsLoading: false,
        expandedRecordId: null,
        recordsHint: !decorated.length && counterpart ? (counterpart.term || counterpart.name) : '',
      })
    }
    catch (error) { this.setData({ recordsLoading: false, records: [], recordsHint: '', recordsError: error.message || '读取失败' }) }
  },
  retryRecords() { this.openRecords() },
  // 调课记录挂在可编辑副本上；原始课表的调课中心为空时指向它的（调）版本
  counterpartSchedule() {
    const current = this.data.schedule
    if (!current) return null
    return (this.data.schedules || []).find(item => item.variant_type === 'adjusted'
      ? item.source_schedule_id === current.id : item.id === current.source_schedule_id) || null
  },
  async jumpCounterpartRecords() {
    const counterpart = this.counterpartSchedule()
    if (!counterpart) return
    const index = this.data.schedules.findIndex(item => item.id === counterpart.id)
    wx.setStorageSync('active_schedule_id', counterpart.id)
    this.setData({ schedule: counterpart, scheduleIndex: index,
      scheduleActive: isScheduleActiveToday(counterpart), statusText: scheduleStatus(counterpart) })
    this.applyWeek(termWeek(counterpart))
    await this.openRecords()
  },
  decorateRecords(records) {
    return (records || []).map(record => ({
      ...record,
      timeText: String(record.created_at || '').replace('T', ' ').slice(0, 16),
      details: (record.details || []).map((detail, index) => ({
        ...detail,
        _idx: index,
        diffText: this.recordDiffs({ details: [detail] }, detail.course_id)[0] || record.description,
      })),
    }))
  },
  closeRecords() { this.setData({ recordsOpen: false, parseStage: 'idle', parseItems: [] }) },
  toggleRecord(event) {
    const id = Number(event.currentTarget.dataset.id)
    this.setData({ expandedRecordId: this.data.expandedRecordId === id ? null : id })
  },
  async revokeBatchRecord(event) {
    const record = event.currentTarget.dataset.record
    const week = this.data.week
    if (!record || !record.id) return
    const activeDetails = (record.details || []).filter(detail => detail && detail.can_revoke)
    const count = activeDetails.length || (record.details || []).length
    const result = await this.modal({
      title: '一键撤销',
      content: `确认一键撤销本次调课的全部改动（共 ${count} 条）？课表将恢复至调课前的原始状态。`,
      confirmText: '撤销',
      danger: true,
    })
    if (!result.confirm) return
    try {
      let revokedCount = 0
      try {
        const res = await app.request(`/api/adjustments/records/${record.id}/revoke`, { method: 'POST' })
        revokedCount = res.revoked
      } catch (_) {
        for (const detail of activeDetails) {
          if (detail.course_id && detail.week) {
            try {
              await app.request(`/api/courses/${detail.course_id}/adjustments/${detail.week}`, { method: 'DELETE' })
              revokedCount++
            } catch (_) {}
          }
        }
      }
      await this.load(this.data.schedule.id)
      this.applyWeek(week)
      await this.openRecords()
      this.toast(revokedCount ? `已一键撤销 ${revokedCount} 条调课` : '该记录调课已撤销')
    } catch (error) {
      this.toast(error.message)
    }
  },
  async revokeAdjustment(event) {
    const detail = event.currentTarget.dataset.detail
    const week = this.data.week
    if (!detail || !detail.course_id || !detail.week) return
    try {
      await app.request(`/api/courses/${detail.course_id}/adjustments/${detail.week}`, { method: 'DELETE' })
      await this.load(this.data.schedule.id); this.applyWeek(week); await this.openRecords(); this.toast('已撤销调课')
    } catch (error) { this.toast(error.message) }
  },
  async removeCurrentAdjustment() {
    const course = this.data.selectedCourse
    const week = this.data.week
    if (!course || !course.adjusted) return
    try {
      await app.request(`/api/courses/${course.id}/adjustments/${week}`, { method: 'DELETE' })
      await this.load(this.data.schedule.id); this.applyWeek(week)
      this.refreshSelectedCourse(course.id)
      this.toast('已恢复原上课时间')
    } catch (error) { this.toast(error.message) }
  },
  async restoreCourseRecord(event) {
    const record = event.currentTarget.dataset.record
    const courseId = record.course_id || ((record.details || []).find(detail => detail && detail.course_id) || {}).course_id
    const course = (this.data.schedule.courses || []).find(item => item.id === courseId)
    if (!course) return this.toast('原课程已不存在')
    const details = record.details || []
    const timeDiff = details.find(diff => diff.field === 'time')
    const roomDiff = details.find(diff => diff.field === 'room')
    if (!timeDiff && !roomDiff) return this.toast('未找到可恢复的变更项')
    const targetWeekday = timeDiff && timeDiff.old_weekday ? timeDiff.old_weekday : course.weekday
    const targetStart = timeDiff && timeDiff.old_start_section ? timeDiff.old_start_section : course.start_section
    const targetEnd = timeDiff && timeDiff.old_end_section ? timeDiff.old_end_section : course.end_section
    const targetRoom = roomDiff && roomDiff.old !== '未设置' ? roomDiff.old : (course.room || '')
    // drag_move 日志同时承载单周调课与整学期移动；仅当记录带周次时按单周恢复
    const recordWeek = record.week || (details[0] && details[0].week) || null
    // 链式回滚需要本课程完整记录池（详情弹窗已过滤，调课中心未过滤则现查）
    const pool = this.data.courseRecords.length ? this.data.courseRecords
      : this.data.records.filter(item => (item.course_id || ((item.details || [])[0] || {}).course_id) === course.id)
    const result = await this.modal({
      title: '回滚改动',
      content: `确认将“${course.name}”回滚至该次修改前的状态？`,
      confirmText: '回滚',
      danger: true,
    })
    if (!result.confirm) return
    try {
      if (recordWeek) {
        const backToOrigin = targetWeekday === course.weekday && targetStart === course.start_section
          && targetEnd === course.end_section && targetRoom === (course.room || '')
        if (backToOrigin) {
          await app.request(`/api/courses/${course.id}/adjustments/${recordWeek}`, { method: 'DELETE' })
        } else {
          await app.request(`/api/courses/${course.id}/adjustments/${recordWeek}?source=manual`, { method: 'PUT', data: {
            week: recordWeek, weekday: targetWeekday, start_section: targetStart,
            end_section: targetEnd, room: targetRoom } })
        }
      } else {
        await app.request(`/api/courses/${course.id}`, { method: 'PUT', data: {
          schedule_id: this.data.schedule.id, name: course.name, teacher: course.teacher || '',
          room: targetRoom, weekday: targetWeekday, start_section: targetStart, end_section: targetEnd,
          weeks: course.weeks || [], color: course.color || DEFAULT_COLOR } })
      }
      // 删除本条及其后该课程的全部记录，避免残留与现状相反的旧 diff
      const subsequent = pool.filter(item => item.id >= record.id)
      for (const sub of subsequent) {
        try { await app.request(`/api/adjustments/records/${sub.id}`, { method: 'DELETE' }) } catch (_) {}
      }
      await this.load(this.data.schedule.id)
      if (this.data.recordsOpen) await this.openRecords()
      if (this.data.detailOpen) {
        const records = await app.request(`/api/adjustments/records?schedule_id=${this.data.schedule.id}`)
        this.setData({ courseRecords: this.filterCourseRecords(records, course.id) })
        this.refreshSelectedCourse(course.id)
      }
      this.toast('已回滚至该次修改前的状态')
    } catch (error) { this.toast(error.message) }
  },
  async deleteRecord(event) {
    const record = event.currentTarget.dataset.record
    const result = await this.modal({
      title: '删除记录',
      content: '仅删除历史记录，不改变当前课表。',
      confirmText: '删除',
      danger: true,
    })
    if (!result.confirm) return
    try {
      await app.request(`/api/adjustments/records/${record.id}`, { method: 'DELETE' })
      await this.openRecords()
      this.toast('记录已删除')
    } catch (error) { this.toast(error.message) }
  },
  // ===== 调课通知图片识别 =====
  chooseNoticeImage() {
    const choose = picker => picker({
      count: 1, mediaType: ['image'], sourceType: ['album', 'camera'],
      success: ({ tempFiles }) => this.parseNotice(tempFiles[0]),
      fail: error => this.pickerFail(error),
    })
    if (wx.chooseMedia) choose(wx.chooseMedia.bind(wx))
    else choose(options => wx.chooseImage({ ...options,
      success: ({ tempFilePaths }) => this.parseNotice({ tempFilePath: tempFilePaths[0] }),
      fail: error => this.pickerFail(error) }))
  },
  async parseNotice(file) {
    const path = file && (file.tempFilePath || file.path)
    if (!path) return this.toast('无法读取所选图片')
    this.setData({ parseStage: 'parsing', parseItems: [], parseFile: String(path).split(/[\\/]/).pop() || '调课通知图片', parsePath: path })
    try {
      const result = await app.upload('/api/adjustments/parse', path, { schedule_id: this.data.schedule.id })
      if (!result.items || !result.items.length) throw new Error('没有从通知中识别到有效调课记录')
      const items = result.items.map((item, index) => ({ ...item, _idx: index,
        statusText: item.status === 'matched' ? '已匹配' : item.status === 'ambiguous' ? '多个候选' : '未匹配',
        oldText: `${days[item.old_weekday - 1]} 第${item.old_start_section}-${item.old_end_section}节${item.old_room ? ` · ${item.old_room}` : ''}`,
        newText: `${days[item.new_weekday - 1]} 第${item.new_start_section}-${item.new_end_section}节${item.new_room ? ` · ${item.new_room}` : ''}`,
        weekText: `第 ${item.week} 周` }))
      this.setData({ parseStage: 'result', parseItems: items })
      this.toast(`识别到 ${result.matched}/${result.total} 条可应用调课`)
    } catch (error) { this.setData({ parseStage: 'idle' }); this.toast(error.message) }
  },
  toggleParseItem(event) {
    const index = Number(event.currentTarget.dataset.index)
    const item = this.data.parseItems[index]
    if (!item || item.status !== 'matched') return
    this.setData({ [`parseItems[${index}].selected`]: !item.selected })
  },
  async applyParse() {
    const selected = this.data.parseItems.filter(item => item.status === 'matched' && item.selected)
    if (!selected.length) return this.toast('请先勾选要应用的调课')
    this.setData({ parseApplying: true })
    try {
      const editable = await this.ensureEditable()
      // 图片识别匹配的是当前课表课程；生成（调）副本后需把课程 id 映射到副本
      const items = selected.map(item => ({
        course_id: editable.course_map[String(item.course_id)] || item.course_id,
        week: item.week, weekday: item.new_weekday,
        start_section: item.new_start_section, end_section: item.new_end_section, room: item.new_room || '',
      }))
      const result = await app.request('/api/adjustments/apply', { method: 'POST',
        header: { 'Idempotency-Key': operationKey('batch') }, data: { schedule_id: editable.scheduleId, items } })
      this.setData({ parseStage: 'idle', parseItems: [] })
      await this.load(editable.scheduleId)
      await this.openRecords()
      this.toast(result.applied ? `已应用 ${result.applied} 条调课` : '所选调课均已存在')
    } catch (error) { this.toast(error.message) }
    finally { this.setData({ parseApplying: false }) }
  },
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
  openImportModal() {
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
        const engineText = importEngineText(result.engine)
        // 与“切换课表”口径一致：同名的多时段/单双周记录只计 1 门课。
        const importedCount = scheduleMeta(this.data.schedule).unique
        this.toast(result.replaced ? `已覆盖当前学期，共 ${importedCount} 门课程（${engineText}）`
          : `已导入 ${importedCount} 门课程（${engineText}）`)
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
