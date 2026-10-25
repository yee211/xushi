const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
function harness(request = async () => ({ people: [] })) {
  let page
  let timer = null
  const storage = new Map([['active_schedule_id', 42], ['bound_student', { id: 'mine' }]])
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/index/index.js'), 'utf8'), {
    getApp: () => ({ request }), Page: p => { page = p },
    setTimeout: fn => { timer = fn; return 1 },
    clearTimeout: () => { timer = null },
    Date,
    wx: { getStorageSync: k => storage.get(k), setStorageSync: (k,v) => storage.set(k,v), removeStorageSync: k => storage.delete(k), getWindowInfo: () => ({ windowHeight: 800 }), showToast() {}, navigateTo(opts) { page.lastNavigation = opts.url } }
  })
  page.setData = values => Object.assign(page.data, values)
  page.actionSheet = async () => ({ tapIndex: -1 })
  return { page, storage, runTimer: () => { const t = timer; timer = null; if (t) t() }, hasTimer: () => !!timer }
}
const person = { student_id: 'other123', term: '2026-2027-1', snapshot: { student: { name: '同学' }, courses: [] } }

test('profile peer entry always opens management even with existing saved people', () => {
  const { page } = harness()
  page.setData({ currentTab: 'mine', otherPeople: [person] })
  page.openOtherFromMine()
  assert.equal(page.lastNavigation, '/pages/others/others')
  assert.equal(page.data.currentTab, 'mine')
  assert.equal(page.data.scheduleScope, 'mine')
})

test('management opens with a saved list without automatically opening a person', async () => {
  const { page, navigated } = searchHarness(async () => ({ people: [person] }))
  await page.onLoad({})
  assert.equal(page.data.savedPeople.length, 1)
  assert.equal(page.data.selected, null)
  assert.equal(navigated(), 0)
})

test('saved-list management selects a person without leaving the page', async () => {
  const { page, navigated } = searchHarness(async url => url.endsWith('/others') ? { people: [person] } : { terms: [person.term] })
  await page.onLoad({})
  await page.chooseSaved({ currentTarget: { dataset: { id: person.student_id } } })
  assert.equal(page.data.selected.name, '同学')
  assert.equal(page.data.saved, true)
  assert.equal(navigated(), 0)
})

test('saved-list remove option directly deletes saved peer without navigating away', async () => {
  let deletedId = ''
  const { page, storage, navigated } = searchHarness(async (url, options) => {
    if (options && options.method === 'DELETE') {
      deletedId = url.split('/').pop()
      return { ok: true }
    }
    return url.endsWith('/others') ? { people: [person] } : { terms: [person.term] }
  })
  await page.onLoad({})
  assert.equal(page.data.savedPeople.length, 1)
  page.removeSaved({ currentTarget: { dataset: { id: person.student_id } } })
  await page.removal
  assert.equal(deletedId, person.student_id)
  assert.equal(page.data.savedPeople.length, 0)
  assert.equal(navigated(), 0)
  assert.equal(storage.get('other_schedules_cache').people.length, 0)
})

test('saved-list remove option clears active form selection if the removed peer was selected', async () => {
  const { page } = searchHarness(async (url, options) => {
    if (options && options.method === 'DELETE') return { ok: true }
    return url.endsWith('/others') ? { people: [person] } : { terms: [person.term] }
  })
  await page.onLoad({})
  await page.chooseSaved({ currentTarget: { dataset: { id: person.student_id } } })
  assert.equal(page.data.selected.name, '同学')
  assert.equal(page.data.saved, true)
  page.removeSaved({ currentTarget: { dataset: { id: person.student_id } } })
  await page.removal
  assert.equal(page.data.selected, null)
  assert.equal(page.data.saved, false)
})

test('update menu offers current and all, plus failed-item retry', async () => {
  const { page } = harness()
  page.setData({ otherPeople: [person], otherSyncTask: { id: 'batch', failed: 1 } })
  let menu
  let retry
  page.actionSheet = async items => { menu = items; return { tapIndex: 2 } }
  page.startOtherSync = async value => { retry = value }
  await page.openOtherUpdateMenu()
  assert.equal(menu.length, 3)
  assert.match(menu[1].text, /共 1 人/)
  assert.equal(retry, true)
})

test('batch start deduplicates taps and stores server progress', async () => {
  let resolveStart
  let calls = 0
  const { page } = harness(() => { calls++; return new Promise(resolve => { resolveStart = resolve }) })
  const start = page.startOtherSync()
  await page.startOtherSync()
  resolveStart({ id: 'batch', state: 'queued', done: 0, total: 3, updated: 0, failed: 0, skipped: 0 })
  await start
  assert.equal(calls, 1)
  assert.equal(page.data.otherSyncActive, true)
  assert.match(page.data.otherSyncText, /0\/3/)
})

test('reopening resumes progress; stale polls cannot revive a hidden-page result', async () => {
  let resolvePoll
  const { page } = harness(() => new Promise(resolve => { resolvePoll = resolve }))
  const polling = page.loadOtherSyncStatus()
  page.onHide()
  resolvePoll({ task: { id: 'old', state: 'running', done: 1, total: 3 } })
  await polling
  assert.equal(page.data.otherSyncTask, null)
})

function searchHarness(request = async () => ({ terms: ['2026-2027-1'] }), failCache = false) {
  let page
  let navigated = 0
  const storage = new Map([['session_token', 'current-session']])
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/others/others.js'), 'utf8'), {
    getApp: () => ({ request }), Page: p => { page = p }, getCurrentPages: () => [page],
    wx: { getStorageSync: k => storage.get(k), setStorageSync: (k, v) => { if (failCache) throw new Error('quota'); storage.set(k, v) },
      navigateBack() { navigated++ }, showModal(opts) { page.removal = opts.success({ confirm: true }) } }
  })
  page.setData = v => Object.assign(page.data, v)
  return { page, storage, navigated: () => navigated }
}

test('missing preferred term remains selected instead of overwriting another term', async () => {
  const { page } = searchHarness()
  await page.loadTerms({ id: 'student123' }, '2025-2026-2')
  assert.equal(page.data.terms[page.data.termIndex], '2025-2026-2')
  assert.equal(page.data.terms.length, 2)
})

test('selecting student clears old terms even when favorites request fails', async () => {
  const { page } = searchHarness(async url => {
    if (url.endsWith('/others')) throw new Error('offline')
    return { terms: ['2026-2027-1'] }
  })
  page.setData({ terms: ['2025-2026-1'], students: [{ id: 'new-person' }] })
  await page.choose({ currentTarget: { dataset: { id: 'new-person' } } })
  assert.equal(page.data.selected.id, 'new-person')
  assert.equal(page.data.terms[0], '2026-2027-1')
})

test('cache quota failure cannot turn a committed save or deletion into an error', async () => {
  const { page, navigated } = searchHarness(async () => person, true)
  page.setData({ selected: { id: person.student_id }, terms: [person.term] })
  await page.save()
  assert.equal(page.data.error, '')
  assert.equal(navigated(), 1)
  page.setData({ saved: true })
  page.remove()
  await page.removal
  assert.equal(page.data.error, '')
  assert.equal(navigated(), 2)
})

test('saving creates a cache under the current session and discards prior session data', async () => {
  const { page, storage } = searchHarness(async () => person)
  page.setData({ selected: { id: person.student_id }, terms: [person.term] })
  await page.save()
  assert.equal(storage.get('other_schedules_cache').session, 'current-session')
  storage.set('other_schedules_cache', { session: 'old-session', people: [{ student_id: 'old-person' }] })
  await page.save()
  assert.equal(storage.get('other_schedules_cache').people.length, 1)
  assert.equal(storage.get('other_schedules_cache').people[0].student_id, person.student_id)
})

test('refresh uses a conditional server update and blocks conflicting navigation', async () => {
  let resolveRefresh
  const calls = []
  const { page } = harness((url, options) => {
    calls.push({ url, method: options.method })
    return new Promise(resolve => { resolveRefresh = resolve })
  })
  page.setData({ scheduleScope: 'others', otherPeople: [person], otherPerson: person })
  const refreshing = page.refreshOther()
  page.manageOther()
  await page.switchScheduleScope('mine')
  assert.equal(page.data.scheduleScope, 'others')
  resolveRefresh(person)
  await refreshing
  assert.equal(calls.length, 1)
  assert.equal(calls[0].method, 'POST')
  assert.match(calls[0].url, /\/others\/other123\/refresh$/)
})
test('viewing and refreshing others cannot select or overwrite personal timetable', async () => {
  const { page, storage } = harness(async () => { throw new Error('offline') })
  page.setData({ scheduleScope: 'others', otherPeople: [person] })
  page.showOtherPerson(person)
  page.applySchedules([{ id: 88, courses: [] }], 88)
  assert.equal(page.data.schedule.id, 'other:other123')
  await page.refreshOther()
  assert.equal(page.data.otherPerson, person)
  assert.equal(storage.get('active_schedule_id'), 42)
  assert.equal(storage.get('bound_student').id, 'mine')
  assert.equal(storage.has('latest_import_schedule_id'), false)
})
test('switching back restores own timetable and keeps saved people', async () => {
  const { page, storage } = harness(async () => [{ id: 42, courses: [] }])
  page.setData({ scheduleScope: 'others', otherPeople: [person] })
  page.showOtherPerson(person)
  await page.switchScheduleScope({ currentTarget: { dataset: { scope: 'mine' } } })
  assert.equal(page.data.schedule.id, 42)
  assert.equal(page.data.otherPeople.length, 1)
  assert.equal(storage.get('active_schedule_id'), 42)
})
test('deleted person is not retained after reloading favorites', async () => {
  const { page } = harness()
  page.setData({ scheduleScope: 'others', otherPerson: person })
  await page.loadOtherPeople()
  assert.equal(page.data.schedule, null)
  assert.equal(page.data.otherPerson, null)
})

test('offline favorites from another login session are never displayed', async () => {
  const { page, storage } = harness(async () => { throw new Error('offline') })
  storage.set('session_token', 'new-account')
  storage.set('other_schedules_cache', { session: 'old-account', people: [person] })
  page.otherSession = 'old-account'
  page.setData({ scheduleScope: 'others', otherPerson: person, otherPeople: [person] })
  page.showOtherPerson(person)
  await page.loadOtherPeople()
  assert.equal(page.data.schedule, null)
  assert.equal(page.data.otherPeople.length, 0)
})
test('offline favorites in the same session restore without changing personal selection', async () => {
  const { page, storage } = harness(async () => { throw new Error('offline') })
  storage.set('session_token', 'same-account')
  storage.set('other_schedules_cache', { session: 'same-account', people: [person] })
  page.setData({ scheduleScope: 'others' })
  await page.loadOtherPeople()
  assert.equal(page.data.schedule.id, 'other:other123')
  assert.match(page.data.cacheNotice, /离线课表/)
  assert.equal(storage.get('active_schedule_id'), 42)
})
test('preview and save share the isolated other-person flow', async () => {
  let searchPage
  const calls = []
  const previous = { data: { otherPerson: person }, setData(v) { Object.assign(this.data, v) }, showOtherPerson(p) { this.person = p } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/others/others.js'), 'utf8'), {
    getApp: () => ({ request: async (url, options) => {
      calls.push(url)
      if (url.endsWith('/others') && options) return { ...person, updated_at: '2026-10-23T00:00:00Z' }
      if (url.endsWith('/others')) return { people: [] }
      return { terms: [person.term] }
    } }),
    Page: p => { searchPage = p }, getCurrentPages: () => [previous, searchPage], wx: { navigateBack() {}, getStorageSync() { return 'session' }, setStorageSync() {} }
  })
  searchPage.setData = v => Object.assign(searchPage.data, v)
  await searchPage.onLoad({ studentId: person.student_id })
  assert.equal(searchPage.data.selected.name, '同学')
  assert.equal(searchPage.data.saved, false)
  await searchPage.save()
  assert.equal(previous.person.student_id, person.student_id)
  assert.equal(previous.data.scheduleScope, 'others')
  assert.equal(calls.some(url => url.includes('/binding') || url.includes('/api/schedules')), false)
})

test('onShow in others scope still syncs nightMode and backgroundPath', async () => {
  const { page, storage } = harness(async () => ({ people: [person] }))
  storage.set('night_mode', true)
  storage.set('schedule_background', '/tmp/bg.png')
  page.setData({ scheduleScope: 'others' })
  page.onShow()
  assert.equal(page.data.nightMode, true)
  assert.equal(page.data.backgroundPath, '/tmp/bg.png')
})

test('refreshing saved other person updates local cache for offline fallback', async () => {
  const updatedCourse = { name: '新课程', weekday: 1, start_section: 1, end_section: 2, weeks: [1] }
  const { page, storage } = harness(async (url, opts) => {
    if (url.includes('/schedule')) return { student: { name: '同学', class_name: '1班' }, courses: [updatedCourse], complete: true }
    if (url.endsWith('/refresh') && opts && opts.method === 'POST') return { ...person, snapshot: { student: { name: '同学', class_name: '1班' }, courses: [updatedCourse] } }
    return { people: [] }
  })
  storage.set('session_token', 'sess-1')
  page.setData({ scheduleScope: 'others', otherPeople: [person], otherPerson: person })
  await page.refreshOther()
  const cached = storage.get('other_schedules_cache')
  assert.equal(cached.session, 'sess-1')
  assert.equal(cached.people[0].snapshot.courses[0].name, '新课程')
})

test('switching to others with cached person renders immediately without loading flicker', async () => {
  let resolveNetwork
  const { page, storage } = harness(() => new Promise(resolve => { resolveNetwork = resolve }))
  storage.set('session_token', 'sess-1')
  storage.set('other_schedules_cache', { session: 'sess-1', people: [person] })
  const switching = page.switchScheduleScope('others')
  assert.equal(page.data.loading, false)
  assert.equal(page.data.schedule.id, 'other:other123')
  resolveNetwork({ people: [person] })
  await switching
})

test('other-sync polling switches to slow mode before stopping and refresh resumes it', async () => {
  const { page, hasTimer } = harness(async () => ({ task: { id: 'task-1', state: 'running', done: 0, total: 2, updated: 0, failed: 0, skipped: 0 } }))
  page.setData({ scheduleScope: 'others', otherSyncActive: true })
  page._otherSyncPolls = 150
  page.scheduleOtherSyncPoll()
  assert.equal(hasTimer(), true)
  assert.match(page.data.otherSyncText, /后台仍在同步/)

  page.stopOtherSyncPoll()
  page._otherSyncPolls = 190
  page.scheduleOtherSyncPoll()
  assert.equal(hasTimer(), false)
  assert.match(page.data.otherSyncText, /进度查询已暂停/)

  // 下拉刷新恢复快速轮询
  await page.onRefresh()
  assert.equal(page._otherSyncPolls, 1)
  assert.equal(hasTimer(), true)
})

test('completion banner is suppressed when task is older than 10 minutes unless witnessed active', async () => {
  const tenMinutesAgo = new Date(Date.now() - 11 * 60 * 1000).toISOString()
  const { page } = harness(async () => ({ task: { id: 'old-task', state: 'completed', done: 1, total: 1, updated: 1, failed: 0, skipped: 0, updated_at: tenMinutesAgo } }))
  page.setData({ scheduleScope: 'others' })
  await page.loadOtherSyncStatus()
  assert.equal(page.data.otherSyncText, '')

  // 若在此次页面访问中曾见证过 running，则显示完成横幅
  page._otherSyncSeenActive = 'old-task'
  page.applyOtherSyncTask({ id: 'old-task', state: 'completed', done: 1, total: 1, updated: 1, failed: 0, skipped: 0, updated_at: tenMinutesAgo })
  assert.match(page.data.otherSyncText, /同步完成/)
})

test('completion banner can be dismissed and does not reappear on revisit', async () => {
  const recent = new Date().toISOString()
  const task = { id: 'fresh-task', state: 'completed', done: 1, total: 1, updated: 1, failed: 0, skipped: 0, updated_at: recent }
  const { page, storage } = harness(async () => ({ task }))
  page.setData({ scheduleScope: 'others' })
  await page.loadOtherSyncStatus()
  assert.match(page.data.otherSyncText, /同步完成/)

  page.dismissOtherSyncStatus()
  assert.equal(page.data.otherSyncText, '')
  assert.equal(storage.get('other_sync_dismissed'), 'fresh-task')

  // 再次获取进度时不应重新弹出
  await page.loadOtherSyncStatus()
  assert.equal(page.data.otherSyncText, '')
})

test('entering others scope avoids redundant loadOtherPeople call', async () => {
  let loadPeopleCalls = 0
  const { page } = harness(async url => {
    if (url.endsWith('/others')) { loadPeopleCalls++; return { people: [person] } }
    if (url.endsWith('/latest')) return { task: { id: 'task-1', state: 'completed', done: 1, total: 1, updated: 1, failed: 0, skipped: 0 } }
    return {}
  })
  page.setData({ scheduleScope: 'others', otherPeople: [person] })
  await page.resumeOtherSyncStatus()
  assert.equal(loadPeopleCalls, 0)
})

test('term picker switches schedules in mine scope when multiple exist', async () => {
  const { page } = harness()
  const sched1 = { id: 101, term: '2025-2026-2', courses: [] }
  const sched2 = { id: 102, term: '2026-2027-1', courses: [] }
  page.setData({ scheduleScope: 'mine', schedules: [sched1, sched2], schedule: sched1 })

  let actionItems = []
  page.actionSheet = async items => {
    actionItems = items
    return { tapIndex: 1 }
  }
  await page.onTermPickerTap()
  assert.equal(actionItems.length, 2)
  assert.match(actionItems[0].text, /✓ 2025-2026-2/)
  assert.match(actionItems[1].text, /📅 2026-2027-1/)
  assert.equal(page.data.schedule.id, 102)
})


test('automatic session renewal always releases saved-list loading state', async () => {
  let storage
  const harness = searchHarness(async () => {
    storage.set('session_token', 'renewed-session')
    return { people: [person] }
  })
  storage = harness.storage
  await harness.page.loadSavedPeople()
  assert.equal(harness.page.data.loadingSaved, false)
  assert.equal(harness.page.data.savedPeople.length, 0)
  await harness.page.loadSavedPeople()
  assert.equal(harness.page.data.savedPeople.length, 1)
})
