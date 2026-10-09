const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')

function harness() {
  let page
  const storage = new Map([['active_schedule_id', 2]])
  const navigations = []
  const sandbox = {
    getApp: () => ({ request: async () => [] }),
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
  return { page, storage, navigations }
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

test('school update remains accessible and closes both menus', () => {
  const { page, navigations } = harness()
  page.setData({ scheduleCenterOpen: true, termSheetOpen: true })
  page.openAcademicQuery()
  assert.equal(page.data.scheduleCenterOpen, false)
  assert.equal(page.data.termSheetOpen, false)
  assert.deepEqual(navigations, ['/pages/academic/academic'])
})

test('retired write and clone methods are removed; backup import remains usable', () => {
  const { page } = harness()
  for (const name of ['addCourse', 'editSelectedCourse', 'openAdjustment', 'startMoveMode', 'cellTap', 'openRecords', 'openShareModal', 'openShareImportModal']) {
    assert.equal(page[name], undefined, name)
  }
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
