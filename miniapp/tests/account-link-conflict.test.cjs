const { test } = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
function harness(confirm) {
  let page
  const requests = []
  const removed = []
  const sandbox = {
    require: () => ({}),
    getApp: () => ({ request: async (url, options) => {
      requests.push(options.data)
      if (requests.length === 1) {
        const error = new Error('学校身份冲突')
        error.code = 'SCHOOL_BINDING_CONFLICT'
        error.data = { app: { name: 'App同学' }, wechat: { name: '微信同学' }, conflict_version: 'v1' }
        throw error
      }
      assert.equal(options.data.school_choice, 'wechat')
      assert.equal(options.data.conflict_version, 'v1')
      return { email: 'test@example.com', school_conflict_resolved: true, schedule_id: 42 }
    } }),
    Page: config => { page = config },
    wx: { showActionSheet: options => options.success({ tapIndex: 1 }), removeStorageSync: key => removed.push(key), setStorageSync: () => {} }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/agent/agent.js'), 'utf8'), sandbox)
  page.setData = changes => Object.assign(page.data, changes)
  page.modal = async options => {
    assert.match(options.content, /另一端自动解除学校绑定/)
    return { confirm }
  }
  page.toast = () => {}
  page.loadStatus = () => {}
  page.data.linkCode = 'ABCD23'
  return { page, requests, removed }
}

test('school conflict selection retries only after explicit overwrite confirmation', async () => {
  const { page, requests, removed } = harness(true)
  await page.submitLinkCode()
  assert.equal(requests.length, 2)
  assert.equal(page.data.account.linked, true)
  for (const key of ['schedules_cache', 'bound_student', 'latest_import_schedule_id']) assert.ok(removed.includes(key))
  assert.equal(page.data.linking, false)
})

test('cancelling overwrite does not retry or merge accounts', async () => {
  const { page, requests } = harness(false)
  await page.submitLinkCode()
  assert.equal(requests.length, 1)
  assert.equal(page.data.account.linked, false)
  assert.equal(page.data.linking, false)
})


test('unlink clears all previous account timetable and identity cache', async () => {
  const { page, removed } = harness(true)
  page.modal = async () => ({ confirm: true })
  page.loadStatus = () => {}
  // This path does not use the conflict retry fixture.
  let config
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/agent/agent.js'), 'utf8'), {
    require: () => ({}), getApp: () => ({ request: async () => ({}) }),
    Page: value => { config = value },
    wx: { removeStorageSync: key => removed.push(key) },
  })
  config.setData = changes => Object.assign(config.data, changes)
  config.modal = async () => ({ confirm: true })
  config.toast = () => {}
  config.loadStatus = () => {}
  await config.unlinkAccount()
  for (const key of ['session_token', 'schedules_cache', 'bound_student', 'active_schedule_id', 'latest_import_schedule_id', 'academic_pending_task_id']) {
    assert.ok(removed.includes(key), key)
  }
})
