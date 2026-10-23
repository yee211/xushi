const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
function harness(request = async () => ({ people: [] })) {
  let page
  const storage = new Map([['active_schedule_id', 42], ['bound_student', { id: 'mine' }]])
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/index/index.js'), 'utf8'), {
    getApp: () => ({ request }), Page: p => { page = p },
    wx: { getStorageSync: k => storage.get(k), setStorageSync: (k,v) => storage.set(k,v), removeStorageSync: k => storage.delete(k), getWindowInfo: () => ({ windowHeight: 800 }), showToast() {} }
  })
  page.setData = values => Object.assign(page.data, values)
  return { page, storage }
}
const person = { student_id: 'other123', term: '2026-2027-1', snapshot: { student: { name: '同学' }, courses: [] } }

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
    Page: p => { searchPage = p }, getCurrentPages: () => [previous, searchPage], wx: { navigateBack() {} }
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
