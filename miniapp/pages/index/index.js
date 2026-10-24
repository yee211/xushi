const app = getApp()
const days = ['周一','周二','周三','周四','周五','周六','周日']
const dayShortNames = ['一','二','三','四','五','六','日']
const ROW_HEIGHT = 112
const DEFAULT_COLOR = '#5B8DEF'
// 同学课表批量同步：轮询 2s 一次，最多 150 次（约 5 分钟）；完成横幅仅在完成后 10 分钟内展示
const OTHER_SYNC_MAX_POLLS = 150
const OTHER_SYNC_SLOW_POLLS = 40
const OTHER_SYNC_SLOW_DELAY = 15000
const OTHER_SYNC_RESULT_WINDOW_MS = 10 * 60 * 1000
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
  const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 20 * 7 - 1)
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
  const end = localDate(schedule && schedule.end_date) || new Date(start.getFullYear(), start.getMonth(), start.getDate() + total * 7 - 1)
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
  cacheOtherPeople(people) {
    try { wx.setStorageSync('other_schedules_cache', { session: wx.getStorageSync('session_token'), people }) } catch (_) {}
  },
  async switchScheduleScope(e) {
    if (this.otherBusy) return
    const scope = (e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.scope) || (typeof e === 'string' ? e : 'mine')
    if (scope === this.data.scheduleScope) return
    if (scope === 'others') {
      const session = wx.getStorageSync('session_token')
      const cache = wx.getStorageSync('other_schedules_cache')
      const cachedPeople = (!this.otherSession || this.otherSession === session)
        ? (this.data.otherPeople && this.data.otherPeople.length ? this.data.otherPeople : (cache && cache.session === session && Array.isArray(cache.people) ? cache.people : []))
        : []
      const initialPerson = this.previewOther || this.data.otherPerson || cachedPeople[0] || null
      this.setData({ scheduleScope: 'others', cacheNotice: '', detailOpen: false, weekOpen: false, loading: !initialPerson, schedule: initialPerson ? this.data.schedule : null })
      if (initialPerson) this.showOtherPerson(initialPerson)
      await this.loadOtherPeople()
      this.resumeOtherSyncStatus()
    } else {
      this.stopOtherSyncPoll()
      const cachedMine = wx.getStorageSync('schedules_cache')
      const hasMine = Array.isArray(cachedMine) && cachedMine.length > 0
      this.setData({ scheduleScope: 'mine', cacheNotice: '', detailOpen: false, weekOpen: false, loading: !hasMine, schedule: hasMine ? this.data.schedule : null })
      if (hasMine) this.applySchedules(cachedMine)
      await this.load(undefined, hasMine)
    }
  },
  openOtherSearch() {
    if (this.otherBusy) return
    this.setData({ scheduleCenterOpen: false })
    wx.navigateTo({ url: '/pages/others/others' })
  },
  openOtherFromMine() { this.openOtherSearch() },
  async onTermPickerTap() {
    if (this.otherBusy) return
    if (this.data.scheduleScope === 'mine') {
      const schedules = (this.data.schedules || []).filter(item => item.variant_type !== 'adjusted')
      if (schedules.length <= 1) return
      const currentId = this.data.schedule && this.data.schedule.id
      const items = schedules.map(s => ({
        text: `${s.id === currentId ? '✓ ' : '📅 '}${s.term || s.name}`
      }))
      const { tapIndex } = await this.actionSheet(items)
      if (tapIndex >= 0 && tapIndex < schedules.length) {
        const chosen = schedules[tapIndex]
        if (chosen.id !== currentId) {
          this.applySchedules(schedules, chosen.id)
        }
      }
      return
    }
    if (this._openingTermPicker) return
    this._openingTermPicker = true
    try {
      let people = this.data.otherPeople || []
      if (!people.length) {
        try {
          const res = await app.request('/api/academic/others')
          if (this.closed) return
          if (res && Array.isArray(res.people)) {
            this.otherSession = wx.getStorageSync('session_token')
            this.cacheOtherPeople(res.people)
            people = res.people.map(p => ({ ...p, displayName: (p.remark ? p.remark + ' · ' : '') + p.snapshot.student.name + ' · ' + (p.snapshot.student.class_name || '') }))
            this.setData({ otherPeople: people })
          }
        } catch (e) {}
      }
      const items = [{ text: '📅 返回我的课表' }]
      people.forEach(p => {
        const isCurrent = this.data.otherPerson && this.data.otherPerson.student_id === p.student_id
        const label = (p.remark ? `${p.remark}（${p.snapshot.student.name}）` : p.snapshot.student.name) + (p.snapshot.student.class_name ? ` · ${p.snapshot.student.class_name}` : '')
        items.push({ text: `${isCurrent ? '✓ ' : '👤 '}${label}` })
      })
      items.push({ text: '＋ 添加同学' })
      const { tapIndex } = await this.actionSheet(items)
      if (tapIndex < 0) return
      if (tapIndex === 0) {
        await this.switchScheduleScope('mine')
        return
      }
      const idx = tapIndex - 1
      if (idx < people.length) {
        this.showOtherPerson(people[idx])
      } else {
        this.openOtherSearch()
      }
    } finally {
      this._openingTermPicker = false
    }
  },
  async loadOtherPeople() {
    const revision = this.otherLoadRevision = (this.otherLoadRevision || 0) + 1
    const session = wx.getStorageSync('session_token')
    if (this.otherSession && this.otherSession !== session) {
      this.previewOther = null
      this.setData({ otherPeople: [], otherPerson: null, schedule: null })
    }
    try {
      const result = await app.request('/api/academic/others')
      if (this.closed || revision !== this.otherLoadRevision || this.data.scheduleScope !== 'others') return
      this.otherSession = wx.getStorageSync('session_token')
      this.cacheOtherPeople(result.people || [])
      this.setData({ cacheNotice: '' })
      this.setData({ otherPeople: (result.people || []).map(p => ({ ...p, displayName: (p.remark ? p.remark + ' · ' : '') + p.snapshot.student.name + ' · ' + (p.snapshot.student.class_name || '') })), loading: false })
      const current = this.data.otherPerson
      const person = this.previewOther || (result.people || []).find(p => current && p.student_id === current.student_id) || result.people[0]
      this.previewOther = null
      this.showOtherPerson(person || null)
    } catch (e) {
      if (this.closed || revision !== this.otherLoadRevision || this.data.scheduleScope !== 'others') return
      const cache = wx.getStorageSync('other_schedules_cache')
      if (cache && cache.session === wx.getStorageSync('session_token') && ![401, 403].includes(e.statusCode)) {
        const people = cache.people || []
        this.setData({ otherPeople: people.map(p => ({ ...p, displayName: (p.remark ? p.remark + ' · ' : '') + p.snapshot.student.name + ' · ' + (p.snapshot.student.class_name || '') })), cacheNotice: '离线课表 · 显示上次保存的同学课表' })
        const current = this.data.otherPerson
        this.showOtherPerson(this.previewOther || people.find(p => current && p.student_id === current.student_id) || people[0] || null)
        this.previewOther = null
      } else { this.setData({ loading: false }); this.toast(e.message) }
    }
  },
  showOtherPerson(person) {
    const snapshot = person && person.snapshot
    const schedule = snapshot ? { ...snapshot, id: 'other:' + person.student_id, name: snapshot.student.name + '的课表', term: person.term,
      courses: (snapshot.courses || []).map((c, i) => ({ ...c, id: 'other-course:' + i })) } : null
    this.setData({
      otherPerson: person,
      schedule,
      loading: false,
      detailOpen: false,
      weekOpen: false,
      scheduleActive: schedule ? isScheduleActiveToday(schedule) : false,
    })
    this.applyWeek(termWeek(schedule))
  },
  chooseOtherPerson(e) { if (!this.otherBusy) this.showOtherPerson(this.data.otherPeople[Number(e.detail.value)]) },
  async openOtherUpdateMenu() {
    if (this.otherBusy || this._openingOtherUpdateMenu) return
    if (this.data.otherSyncActive) { this.toast(this.data.otherSyncText); return }
    this._openingOtherUpdateMenu = true
    try {
      const items = [{ text: '更新当前课表' }, { text: `同步全部已保存课表（共 ${this.data.otherPeople.length} 人）` }]
      if (this.data.otherSyncTask && this.data.otherSyncTask.failed) items.push({ text: `重试失败项（${this.data.otherSyncTask.failed} 人）` })
      const { tapIndex } = await this.actionSheet(items)
      if (this.closed) return
      if (tapIndex === 0) await this.refreshOther()
      else if (tapIndex === 1) await this.startOtherSync(false)
      else if (tapIndex === 2) await this.startOtherSync(true)
    } finally { this._openingOtherUpdateMenu = false }
  },
  async startOtherSync(retry = false) {
    if (this._startingOtherSync || this.data.otherSyncActive) return
    this._startingOtherSync = true
    this.stopOtherSyncPoll()
    const session = wx.getStorageSync('session_token')
    try {
      const data = retry && this.data.otherSyncTask ? { retry_of: this.data.otherSyncTask.id } : {}
      const task = await app.request('/api/academic/others/sync/tasks', { method: 'POST', data })
      if (this.closed || wx.getStorageSync('session_token') !== session) return
      this._otherSyncPolls = 0
      this.applyOtherSyncTask(task)
      this.scheduleOtherSyncPoll()
    } catch (e) { if (!this.closed) this.toast(e.message) }
    finally { this._startingOtherSync = false }
  },
  applyOtherSyncTask(task) {
    this._otherSyncSession = wx.getStorageSync('session_token')
    const active = !!task && ['queued', 'running'].includes(task.state)
    if (active) this._otherSyncSeenActive = task.id
    let text = ''
    if (active) text = `同步中 ${task.done}/${task.total} · 离开页面后仍会继续`
    else if (task && this.shouldShowOtherSyncResult(task)) {
      const failedOnly = task.failed && !task.updated && !task.skipped
      text = `${failedOnly ? '同步失败' : '同步完成'}：成功 ${task.updated} 人，失败 ${task.failed} 人，跳过 ${task.skipped} 人${task.failed ? ' · 点更新可重试失败项' : ''}`
    }
    this.setData({ otherSyncTask: task || null, otherSyncActive: active, otherSyncText: text })
  },
  // /latest 返回的是最近一次任务（可能是几天前的）：完成横幅只在本页亲眼看到它跑完，
  // 或完成后 10 分钟内展示；用户手动关闭过的任务不再展示。
  shouldShowOtherSyncResult(task) {
    let dismissed = ''
    try { dismissed = wx.getStorageSync('other_sync_dismissed') } catch (_) {}
    if (dismissed && dismissed === task.id) return false
    if (this._otherSyncSeenActive === task.id) return true
    const finishedAt = Date.parse(task.updated_at || '')
    return !isNaN(finishedAt) && Date.now() - finishedAt < OTHER_SYNC_RESULT_WINDOW_MS
  },
  dismissOtherSyncStatus() {
    const task = this.data.otherSyncTask
    if (!task || this.data.otherSyncActive) return
    try { wx.setStorageSync('other_sync_dismissed', task.id) } catch (_) {}
    this._otherSyncSeenActive = null
    this.setData({ otherSyncText: '' })
  },
  stopOtherSyncPoll() {
    this._otherSyncRevision = (this._otherSyncRevision || 0) + 1
    if (this._otherSyncTimer && typeof clearTimeout === 'function') clearTimeout(this._otherSyncTimer)
    this._otherSyncTimer = null
  },
  scheduleOtherSyncPoll(delay = 2000) {
    if (this.closed || this._otherSyncHidden || this.data.scheduleScope !== 'others' || !this.data.otherSyncActive || typeof setTimeout !== 'function') return
    // 服务端每人间隔 6~10 秒，50 人批次约 5 分钟；快速轮询后转慢速兜底，
    // 不在批次完成前直接停掉。服务端会在 15 分钟后回收僵死任务。
    this._otherSyncPolls = (this._otherSyncPolls || 0) + 1
    let nextDelay = delay
    if (this._otherSyncPolls > OTHER_SYNC_MAX_POLLS) {
      if (this._otherSyncPolls > OTHER_SYNC_MAX_POLLS + OTHER_SYNC_SLOW_POLLS) {
        this.setData({ otherSyncText: '进度查询已暂停，可下拉刷新确认结果' })
        return
      }
      nextDelay = OTHER_SYNC_SLOW_DELAY
      if (this._otherSyncPolls === OTHER_SYNC_MAX_POLLS + 1) {
        this.setData({ otherSyncText: '后台仍在同步，可下拉刷新确认结果' })
      }
    }
    if (this._otherSyncTimer) clearTimeout(this._otherSyncTimer)
    this._otherSyncTimer = setTimeout(() => { this._otherSyncTimer = null; this.loadOtherSyncStatus() }, nextDelay)
  },
  // 用户主动进入/返回同学课表时：重置轮询额度；名单刚由调用方加载过，首次状态查询不必再拉一次
  resumeOtherSyncStatus() {
    this._otherSyncPolls = 0
    return this.loadOtherSyncStatus({ peopleFresh: true })
  },
  async loadOtherSyncStatus(options = {}) {
    const revision = this._otherSyncRevision = (this._otherSyncRevision || 0) + 1
    const session = wx.getStorageSync('session_token')
    try {
      const result = await app.request('/api/academic/others/sync/tasks/latest')
      if (this.closed || revision !== this._otherSyncRevision || wx.getStorageSync('session_token') !== session) return
      const before = this.data.otherSyncTask
      const task = result && result.task
      this.applyOtherSyncTask(task)
      const changed = !!task && (!before || before.id !== task.id
        || before.updated_at !== task.updated_at || before.updated !== task.updated)
      if (task && task.updated && changed && !options.peopleFresh && this.data.scheduleScope === 'others') await this.loadOtherPeople()
      this.scheduleOtherSyncPoll()
    } catch (e) {
      if (!this.closed && revision === this._otherSyncRevision && this.data.otherSyncActive) {
        this.setData({ otherSyncText: '暂时无法获取进度，后台仍会继续同步' })
        this.scheduleOtherSyncPoll(10000)
      }
    }
  },
  async refreshOther() {
    if (this.data.otherSyncActive) { this.toast(this.data.otherSyncText); return }
    const person = this.data.otherPerson
    if (!person || this.otherBusy) return
    this.otherBusy = true
    const session = wx.getStorageSync('session_token')
    this.setData({ otherBusy: true })
    try {
      const saved = this.data.otherPeople.some(p => p.student_id === person.student_id)
      let updated
      if (saved) {
        updated = await app.request('/api/academic/others/' + encodeURIComponent(person.student_id) + '/refresh', { method: 'POST', timeout: 120000 })
      } else {
        const snapshot = await app.request('/api/academic/students/' + encodeURIComponent(person.student_id) + '/schedule', { data: { term: person.term, refresh: true }, timeout: 120000 })
        if (snapshot.stale || !snapshot.complete) throw new Error('学校暂不可用，保留原课表')
        updated = { ...person, snapshot }
      }
      if (this.closed || this.data.otherPerson !== person || this.data.scheduleScope !== 'others' || wx.getStorageSync('session_token') !== session) return
      if (!this.closed && this.data.scheduleScope === 'others' && this.data.otherPerson === person) {
        const nextPeople = this.data.otherPeople.map(p => p.student_id === updated.student_id ? { ...updated, displayName: (updated.remark ? updated.remark + ' · ' : '') + updated.snapshot.student.name + ' · ' + (updated.snapshot.student.class_name || '') } : p)
        this.setData({ otherPeople: nextPeople })
        this.cacheOtherPeople(nextPeople)
        this.showOtherPerson(updated)
        this.toast('课表已更新', 'success')
      }
    } catch (e) { this.toast(e.message) }
    finally { this.otherBusy = false; if (!this.closed) this.setData({ otherBusy: false }) }
  },
  manageOther() {
    if (this.otherBusy) return
    const person = this.data.otherPerson
    if (!person) return
    wx.navigateTo({ url: '/pages/others/others?studentId=' + encodeURIComponent(person.student_id) })
  },
  openAcademicQuery() { this.setData({ scheduleScope: 'mine', scheduleCenterOpen: false }); wx.navigateTo({ url: '/pages/academic/academic' }) },
  openImportModal() { this.setData({ scheduleCenterOpen: true }) },
  closeScheduleCenter() { this.setData({ scheduleCenterOpen: false }) },
  chooseCenterImport() { this.setData({ scheduleCenterOpen: false }); this.openFileImportModal() },

  switchTab(e) {
    if (this.otherBusy) return
    const tab = (e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.tab) || 'home'
    if (this.data.currentTab === tab) return
    if (tab === 'mine' && this.data.scheduleScope === 'others') this.switchScheduleScope({ currentTarget: { dataset: { scope: 'mine' } } })
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
    scheduleScope: 'mine', otherPeople: [], otherPerson: null, otherBusy: false,
    otherSyncTask: null, otherSyncActive: false, otherSyncText: '',
    currentTab: 'home', // 'home' | 'mine'
    refreshing: false,
    cacheNotice: '', loading: true, schedules: [], schedule: null,
    week: 1, weekCount: 20, weekOpen: false, weekOptions: [],
    weekDays: [], monthLabel: '', gridCourses: [], shownSections: sections.slice(0, 10),
    rowHeightRpx: ROW_HEIGHT,
    gridHeight: 10 * ROW_HEIGHT, backgroundPath: '', scheduleActive: false,
    detailOpen: false, selectedCourse: null,
    scheduleCenterOpen: false, importOpen: false, importFile: null, semesterName: '', startDate: '', endDate: '', uploading: false,
    importProgressText: '',
    semesterOpen: false, semesterForm: {}, semesterWeeks: 20, semesterSaving: false,
    semesterStatusText: '', semesterStatusClass: 'unset', semesterChanged: false, calculatedNotice: '',
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
    this.closed = false
    this._otherSyncHidden = false
    this.setData({
      backgroundPath: wx.getStorageSync('schedule_background') || '',
      nightMode: wx.getStorageSync('night_mode') === true,
      boundStudent: wx.getStorageSync('bound_student') || null,
    })
    this.applyNavigationBarColor(this.data.nightMode)
    this.hookPrivacyAuthorization()
    const cachedOthers = wx.getStorageSync('other_schedules_cache')
    const currentSession = wx.getStorageSync('session_token')
    if (this._otherSyncSession && this._otherSyncSession !== currentSession) this.applyOtherSyncTask(null)
    if (cachedOthers && cachedOthers.session === currentSession && Array.isArray(cachedOthers.people)) {
      this.setData({ otherPeople: cachedOthers.people.map(p => ({ ...p, displayName: (p.remark ? p.remark + ' · ' : '') + p.snapshot.student.name + ' · ' + (p.snapshot.student.class_name || '') })) })
    } else if (cachedOthers && cachedOthers.session !== currentSession) {
      this.setData({ otherPeople: [] })
    }
    if (this.data.scheduleScope === 'others') { this.loadOtherPeople(); this.resumeOtherSyncStatus(); return }
    // 账号关联/解除会清除缓存；回到课表页时同步清除旧账号画面。
    if (!Array.isArray(wx.getStorageSync('schedules_cache'))) {
      this.setData({ schedule: null, schedules: [] })
    }
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
    if (this.data.scheduleScope === 'others') { this.toast('请切回我的课表使用助手'); return }
    const scheduleId = this.data.schedule && this.data.schedule.id
    wx.navigateTo({ url: `/pages/agent/agent${scheduleId ? `?scheduleId=${scheduleId}` : ''}` })
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
  onHide() { this._otherSyncHidden = true; this.stopOtherSyncPoll() },
  onUnload() {
    this.closed = true
    this.stopOtherSyncPoll()
    this.stopImportTimer()
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
    if (this.loadPromise && (!preferredId || preferredId === this.loadPreferredId)) return this.loadPromise
    const generation = (this.loadGeneration || 0) + 1
    this.loadGeneration = generation
    this.loadPreferredId = preferredId
    const pending = this.fetchSchedules(preferredId, silent, generation)
    this.loadPromise = pending
    try { return await pending }
    finally { if (this.loadPromise === pending) this.loadPromise = null }
  },
  async fetchSchedules(preferredId, silent, generation) {
    if (this._initialLoaded && silent === false) silent = true
    if (!silent) this.setData({ loading: true })
    try {
      const schedules = await app.request('/api/schedules')
      if (this.closed || generation !== this.loadGeneration) return false
      wx.setStorageSync('schedules_cache_at', new Date().toISOString())
      this.setData({ cacheNotice: '' })
      // 缓存最近一次完整课表：刷新更快，断网时也能兜底展示
      wx.setStorageSync('schedules_cache', schedules)
      this.applySchedules(schedules, preferredId)
      return true
    } catch (error) {
      if (this.closed || generation !== this.loadGeneration) return false
      const cached = wx.getStorageSync('schedules_cache')
      if (Array.isArray(cached) && cached.length) {
        this.applySchedules(cached, preferredId)
        const savedAt = wx.getStorageSync('schedules_cache_at')
        this.setData({ cacheNotice: '离线课表 · ' + (savedAt ? '最近更新于 ' + new Date(savedAt).toLocaleString() : '缓存时间未知') })
      } else {
        if (!silent) this.setData({ loading: false })
        this.toast(error.message)
      }
      return false
    }
  },
  // 导入成功指定的课表优先，并在重新打开或离线时保持。旧切换记录不再生效。
  applySchedules(schedules, preferredId) {
    if (this.data.scheduleScope === 'others') return
    const previous = this.data.schedule
    const previousWeek = this.data.week
    const sameDay = this.viewDate === isoDate(new Date())
    schedules = schedules.filter(item => item.variant_type !== 'adjusted')
    let index = schedules.findIndex(item => item.id === Number(preferredId))
    if (index >= 0) wx.setStorageSync('latest_import_schedule_id', schedules[index].id)
    if (index < 0) index = schedules.findIndex(item => item.id === Number(wx.getStorageSync('active_schedule_id')))
    if (index < 0) index = schedules.findIndex(item => item.id === Number(wx.getStorageSync('latest_import_schedule_id')))
    if (index < 0 && schedules.length) {
      const latest = schedules.reduce((result, item) => item.id > result.id ? item : result, schedules[0])
      index = schedules.indexOf(latest)
    }
    if (index < 0) index = 0
    const schedule = schedules[index] || null
    if (schedule) wx.setStorageSync('active_schedule_id', schedule.id)
    else wx.removeStorageSync('active_schedule_id')
    this.setData({
      schedules,
      schedule,
      scheduleActive: schedule ? isScheduleActiveToday(schedule) : false,
      loading: false,
    })
    const preserveWeek = previous && schedule && previous.id === schedule.id && previous.start_date === schedule.start_date && sameDay
    this.applyWeek(preserveWeek ? previousWeek : termWeek(schedule))
  },
  // 页面主体是 scroll-view，页面级下拉刷新不会触发，这里用 scroll-view 自带 refresher
  async onRefresh() {
    this.setData({ refreshing: true })
    try {
      if (this.data.scheduleScope === 'others') {
        // 批量同步进行中（含轮询已暂停）时，下拉 = 重新确认进度并恢复轮询
        if (this.data.otherSyncActive) { this._otherSyncPolls = 0; await this.loadOtherSyncStatus() }
        else await this.refreshOther()
      }
      else await this.load(this.data.schedule && this.data.schedule.id, true)
    }
    finally { this.setData({ refreshing: false }) }
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
    this.viewDate = isoDate(new Date())
    const count = weekCount(this.data.schedule)
    const safeWeek = Math.max(1, Math.min(count, week))
    const dates = datesForWeek(this.data.schedule, safeWeek)
    const sectionCount = sectionCountFor(this.data.schedule)
    const rowHeight = this.computeRowHeight(sectionCount)
    this.setData({
      week: safeWeek,
      weekCount: count,
      weekIsCurrent: !!this.data.schedule && !!this.data.scheduleActive && safeWeek === termWeek(this.data.schedule),
      weekOptions: buildWeekOptions(this.data.schedule, count, safeWeek),
      weekDays: dates.weekDays,
      monthLabel: dates.monthLabel,
      shownSections: sections.slice(0, sectionCount),
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
    if (this.data.scheduleScope === 'others') return
    const schedule = this.data.schedule
    if (!schedule) return
    const form = {
      name: schedule.name || '', term: schedule.term || '',
      start_date: (schedule.start_date || '').slice(0, 10), end_date: (schedule.end_date || '').slice(0, 10),
    }
    this._semesterOriginal = JSON.stringify(form)
    this.setData({ semesterOpen: true, semesterWeeks: weekCount(schedule), semesterForm: form,
      semesterChanged: false, calculatedNotice: '' })
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
      semesterChanged: JSON.stringify(form) !== this._semesterOriginal })
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
    this.setData({ importOpen: true })
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
    this.importElapsed = 0
    this.setData({ importProgressText: '正在安全读取工作簿…' })
    this.stopImportTimer()
    this.importTimer = setInterval(() => {
      this.importElapsed = (this.importElapsed || 0) + 1
      const elapsed = this.importElapsed
      const text = elapsed < 5 ? '正在安全读取工作簿…'
        : elapsed < 45 ? `正在识别课程信息… ${elapsed} 秒`
        : '服务器仍在解析，请稍候；若超时可下拉刷新确认结果。'
      this.setData({ importProgressText: text })
    }, 1000)
  },
  stopImportTimer() {
    if (this.importTimer) { clearInterval(this.importTimer); this.importTimer = null }
  },
  closeImport() {
    if (this.data.uploading) return
    this.stopImportTimer()
    this.setData({ importOpen: false, importFile: null })
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
    if (this.data.uploading) return
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
        this.setData({ importOpen: false, importFile: null }); await this.load(result.schedule_id)
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
