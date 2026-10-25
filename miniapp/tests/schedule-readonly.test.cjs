const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')

function harness(request = async () => []) {
  let page
  const storage = new Map([['active_schedule_id', 2]])
  const navigations = []
  const sandbox = {
    getApp: () => ({ request }),
    Page: value => { page = value },
    wx: {
      getStorageSync: key => storage.get(key),
      setStorageSync: (key, value) => storage.set(key, value),
      removeStorageSync: key => storage.delete(key),
      getWindowInfo: () => ({ windowHeight: 800 }),
      navigateTo: options => navigations.push(options.url),
    },
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/index/index.js'), 'utf8'), sandbox)
  page.setData = value => Object.assign(page.data, value)
  return { page, storage, navigations, wx: sandbox.wx }
}

test('old adjusted copy cannot remain the selected timetable', () => {
  const { page, storage } = harness()
  page.applySchedules([
    { id: 2, name: 'adjusted', variant_type: 'adjusted', courses: [] },
    { id: 1, name: 'school', variant_type: 'original', courses: [], start_date: '2026-09-07', end_date: '2027-01-24' },
  ])
  assert.equal(page.data.schedule.id, 1)
  assert.equal(page.data.schedules.length, 1)
  assert.equal(storage.get('active_schedule_id'), 1)
})

test('school update remains accessible and closes schedule center', () => {
  const { page, navigations } = harness()
  page.setData({ scheduleCenterOpen: true })
  page.openAcademicQuery()
  assert.equal(page.data.scheduleCenterOpen, false)
  assert.deepEqual(navigations, ['/pages/academic/academic'])
})

test('retired write and clone methods are removed; backup import remains usable', () => {
  const { page } = harness()
  for (const name of ['addCourse', 'editSelectedCourse', 'openAdjustment', 'startMoveMode', 'cellTap', 'openRecords', 'openShareModal', 'openShareImportModal', 'openTermSheet', 'openSemesterFromSheet', 'syncSchedules']) {
    assert.equal(page[name], undefined, name)
  }
  assert.equal(page.data.termSheetOpen, undefined)
  page.chooseCenterImport()
  assert.equal(page.data.importOpen, true)
  assert.equal(typeof page.prepareImport, 'function')
  assert.equal(typeof page.upload, 'function')
})


test('overwriting an older timetable remains selected after reopening and cache fallback', () => {
  const { page, storage } = harness()
  const schedules = [
    { id: 8, variant_type: 'original', courses: [] },
    { id: 3, variant_type: 'original', courses: [] },
  ]
  page.applySchedules(schedules, 3)
  assert.equal(storage.get('latest_import_schedule_id'), 3)
  page.applySchedules(schedules)
  assert.equal(page.data.schedule.id, 3)
  page.applySchedules([schedules[0]])
  assert.equal(page.data.schedule.id, 8)
})


test('refresh preserves the selected timetable and week', () => {
  const { page, storage } = harness()
  const schedules = [{ id: 2, courses: [], start_date: '2026-09-07' }, { id: 3, courses: [] }]
  page.applySchedules(schedules, 2)
  page.applyWeek(9)
  page.applySchedules(schedules)
  assert.equal(page.data.schedule.id, 2)
  assert.equal(page.data.week, 9)
  assert.equal(storage.get('active_schedule_id'), 2)
})

test('concurrent refreshes share a request and obsolete responses cannot overwrite new data', async () => {
  const pending = []
  const { page } = harness(() => new Promise(resolve => pending.push(resolve)))
  const first = page.load()
  const same = page.load()
  assert.equal(pending.length, 1)
  const newer = page.load(7)
  pending[1]([{ id: 7, courses: [] }])
  await newer
  pending[0]([{ id: 1, courses: [] }])
  await Promise.all([first, same])
  assert.equal(page.data.schedule.id, 7)
})

test('failed refresh displays cache age and successful refresh clears it', async () => {
  let offline = true
  const { page, storage } = harness(async () => {
    if (offline) throw new Error('断网')
    return [{ id: 2, courses: [] }]
  })
  storage.set('schedules_cache', [{ id: 2, courses: [] }])
  storage.set('schedules_cache_at', '2026-10-11T00:00:00Z')
  await page.load()
  assert.match(page.data.cacheNotice, /离线课表.*最近更新于/)
  offline = false
  await page.load()
  assert.equal(page.data.cacheNotice, '')
})


test('fallback semester end date uses local calendar in a negative UTC offset', () => {
  const previous = process.env.TZ
  try {
    process.env.TZ = 'America/Los_Angeles'
    const source = fs.readFileSync(path.join(__dirname, '../pages/index/index.js'), 'utf8')
    const sandbox = { getApp: () => ({}), Page: () => {} }
    vm.runInNewContext(source + '\nthis.suggest = suggestSemesterDates', sandbox)
    const result = sandbox.suggest('2026-2027学年第1学期')
    assert.equal(result.start, '2026-09-07')
    assert.equal(result.end, '2027-01-24')
  } finally {
    if (previous === undefined) delete process.env.TZ
    else process.env.TZ = previous
  }
})


test('non-Monday semester preserves its partial final week', () => {
  const { page } = harness()
  page.applySchedules([{ id: 2, courses: [], start_date: '2026-10-07', end_date: '2026-10-13' }])
  page.applyWeek(2)
  assert.equal(page.data.week, 2)
})

test('failed cache write cannot give old data a fresh timestamp', async () => {
  const { page, storage, wx } = harness(async () => [{ id: 3, courses: [] }])
  storage.set('schedules_cache', [{ id: 2, courses: [] }])
  storage.set('schedules_cache_at', '2026-10-01T00:00:00Z')
  const write = wx.setStorageSync
  wx.setStorageSync = (key, value) => {
    if (key === 'schedules_cache') throw new Error('storage quota')
    return write(key, value)
  }
  assert.equal(await page.load(), false)
  assert.equal(storage.get('schedules_cache_at'), '2026-10-01T00:00:00Z')
  assert.equal(page.data.schedule.id, 2)
})
