const { test } = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')

function pageHarness(request) {
  let config, timer
  const storage = new Map(), loads = []
  const sandbox = {
    getApp: () => ({ request }),
    Page: value => { config = value },
    getCurrentPages: () => [{ load: async id => loads.push(id) }, {}],
    wx: {
      setStorageSync: (key, value) => storage.set(key, value),
      getStorageSync: key => storage.get(key),
      removeStorageSync: key => storage.delete(key),
      showToast: () => {}, showModal: options => options.success?.({ confirm: true })
    },
    setTimeout: callback => { timer = callback; return 1 },
    clearTimeout: () => { timer = null }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/academic/academic.js'), 'utf8'), sandbox)
  config.setData = values => Object.assign(config.data, values)
  return { page: config, storage, loads, wx: sandbox.wx, tick: async () => { const callback = timer; timer = null; if (callback) await callback() }, hasTimer: () => !!timer }
}

test('queued sync polls until success and reloads the primary timetable', async () => {
  let count = 0
  const harness = pageHarness(async url => {
    assert.equal(url, '/api/academic/binding/sync/tasks/job-1')
    return ++count === 1 ? { id: 'job-1', state: 'running' } : { id: 'job-1', state: 'succeeded', result: { schedule_id: 42, last_synced_at: '2026-10-08T12:00:00Z' } }
  })
  await harness.page.followTask({ id: 'job-1', state: 'queued' })
  assert.equal(harness.page.data.busy, true)
  assert.equal(harness.storage.get('academic_pending_task_id'), 'job-1')
  await harness.tick()
  assert.match(harness.page.data.syncStatus, /正在从学校/)
  await harness.tick()
  assert.equal(harness.page.data.busy, false)
  assert.equal(harness.storage.get('active_schedule_id'), 42)
  assert.deepEqual(harness.loads, [42])
  assert.equal(harness.hasTimer(), false)
})

test('closing the page stops polling while failure keeps active timetable', async () => {
  const harness = pageHarness(async () => assert.fail('must not poll after unload'))
  harness.storage.set('active_schedule_id', 77)
  await harness.page.followTask({ id: 'job-1', state: 'queued' })
  harness.page.onUnload()
  await harness.tick()
  assert.equal(harness.storage.get('active_schedule_id'), 77)
  const failed = pageHarness(async () => {})
  failed.storage.set('active_schedule_id', 77)
  await failed.page.followTask({ id: 'job-1', state: 'failed', error: '学校连接过期' })
  assert.equal(failed.page.data.busy, false)
  assert.equal(failed.storage.get('active_schedule_id'), 77)
  assert.equal(failed.page.data.error, '学校连接过期')
})

test('reopening restores a task that completed while the page was closed', async () => {
  const harness = pageHarness(async url => {
    if (url === '/api/academic/binding') return { student: { id: 'student01', default_term: '2026-2027-1' } }
    if (url.endsWith('/terms')) return { terms: ['2026-2027-1'] }
    if (url.endsWith('/latest')) return { task: { id: 'job-1', state: 'succeeded', result: { schedule_id: 42, last_synced_at: '2026-10-08T12:00:00Z' } } }
    assert.fail(url)
  })
  harness.storage.set('academic_pending_task_id', 'job-1')
  await harness.page.onLoad()
  assert.deepEqual(harness.loads, [42])
  assert.equal(harness.storage.has('academic_pending_task_id'), false)
})

test('fuzzy school search, select, bind, queued sync completes the miniapp flow', async () => {
  const calls = []
  const student = { id: 'student01', name: '张同学', major_name: '计算机', class_name: '24计科7班', default_term: '2026-2027-1' }
  const harness = pageHarness(async (url, options) => {
    calls.push([url, options])
    if (url === '/api/academic/binding' && !options) return { student: null }
    if (url === '/api/academic/students') {
      assert.equal(options.data.q, '计科')
      assert.equal(options.data.grade, undefined)
      assert.equal(options.timeout, 120000)
      return { students: [student] }
    }
    if (url === '/api/academic/binding' && options.method === 'PUT') {
      assert.equal(options.data.student_id, student.id)
      return { student }
    }
    if (url.endsWith('/terms')) return { terms: [student.default_term] }
    if (url.endsWith('/sync/tasks')) {
      assert.equal(options.data.term, student.default_term)
      return { id: 'job-1', state: 'queued' }
    }
    if (url.endsWith('/tasks/job-1')) return { id: 'job-1', state: 'succeeded', result: { schedule_id: 42, last_synced_at: '2026-10-09T00:00:00Z' } }
    assert.fail(url)
  })
  await harness.page.onLoad()
  assert.equal(calls.length, 1) // Opening search does not require the school grade directory.
  harness.page.inputKeyword({ detail: { value: ' 计科 ' } })
  await harness.page.search()
  assert.equal(harness.page.data.students.length, 1)
  harness.page.choose({ currentTarget: { dataset: { id: student.id } } })
  assert.equal(calls.length, 2) // Selection is local, like Android.
  await harness.page.bindSchool()
  assert.equal(harness.page.data.bound.id, student.id)
  assert.equal(harness.storage.get('bound_student').id, student.id)
  await harness.page.syncSchool()
  await harness.tick()
  assert.deepEqual(harness.loads, [42])
})

test('fuzzy search displays truncation and ignores responses after unload', async () => {
  const harness = pageHarness(async () => ({ students: [], truncated: true }))
  harness.page.inputKeyword({ detail: { value: '24' } })
  await harness.page.search()
  assert.match(harness.page.data.notice, /补充姓名或班级/)
  assert.equal(harness.page.data.error, '')
  let resolve
  const closed = pageHarness(() => new Promise(done => { resolve = done }))
  closed.page.inputKeyword({ detail: { value: '张' } })
  const pending = closed.page.search()
  closed.page.onUnload()
  resolve({ students: [{ id: 'late-response' }] })
  await pending
  assert.equal(closed.page.data.students.length, 0)
})

test('term lookup failure preserves completed binding and its default semester', async () => {
  const student = { id: 'student01', default_term: '2026-2027-1' }
  const harness = pageHarness(async url => {
    if (url === '/api/academic/binding') return { student }
    throw new Error('学期查询超时')
  })
  harness.page.data.selected = student
  await harness.page.bindSchool()
  assert.equal(harness.page.data.bound.id, student.id)
  assert.equal(harness.page.data.terms[0], student.default_term)
  assert.match(harness.page.data.error, /学期查询超时/)
  assert.equal(harness.page.data.busy, false)
})

test('recovery waits for confirmation then reloads restored timetable', async () => {
  const calls = []
  const harness = pageHarness(async (url, options) => {
    calls.push([url, options])
    if (url === '/api/academic/backups') return { backups: [{ id: 7, created_at: '2026-10-09T00:00:00Z', schedule_count: 2 }] }
    assert.equal(url, '/api/academic/backups/7/restore')
    assert.equal(options.method, 'POST')
    return { schedule_id: 42, restored: true }
  })
  let sheet, modal
  harness.wx.showActionSheet = options => { sheet = options }
  harness.wx.showModal = options => { modal = options }
  await harness.page.restoreSchoolBackup()
  sheet.success({ tapIndex: 0 })
  assert.equal(calls.length, 1)
  await modal.success({ confirm: true })
  assert.equal(harness.storage.get('active_schedule_id'), 42)
  assert.deepEqual(harness.loads, [42])
  assert.equal(harness.page.data.busy, false)
})

test('cancelling recovery leaves current timetable untouched', async () => {
  const harness = pageHarness(async url => {
    assert.equal(url, '/api/academic/backups')
    return { backups: [{ id: 7, created_at: '2026-10-09T00:00:00Z', schedule_count: 2 }] }
  })
  harness.storage.set('active_schedule_id', 77)
  let modal
  harness.wx.showActionSheet = options => { options.success({ tapIndex: 0 }) }
  harness.wx.showModal = options => { modal = options }
  await harness.page.restoreSchoolBackup()
  await modal.success({ confirm: false })
  assert.equal(harness.storage.get('active_schedule_id'), 77)
  assert.deepEqual(harness.loads, [])
})


test('school sync sends no request before confirmation or after cancellation', async () => {
  const calls = []
  const harness = pageHarness(async url => { calls.push(url); return { id: 'job-1', state: 'queued' } })
  harness.page.setData({ bound: { id: 'student01' }, terms: ['2026-2027-1'] })
  let modal
  harness.wx.showModal = options => { modal = options }
  const pending = harness.page.syncSchool()
  assert.deepEqual(calls, [])
  assert.equal(modal.confirmText, '同步课表')
  assert.match(modal.content, /个人调课会被替换/)
  modal.success({ confirm: false })
  await pending
  assert.deepEqual(calls, [])
  assert.equal(harness.page.data.busy, false)
})

test('repeated sync clicks share one confirmation and closed page does not submit', async () => {
  const harness = pageHarness(async () => assert.fail('must not submit after page closes'))
  harness.page.setData({ bound: { id: 'student01' }, terms: ['2026-2027-1'] })
  let modal, count = 0
  harness.wx.showModal = options => { modal = options; count++ }
  const pending = harness.page.syncSchool()
  await harness.page.syncSchool()
  assert.equal(count, 1)
  harness.page.onUnload()
  modal.success({ confirm: true })
  await pending
})
