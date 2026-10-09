const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '..')

test('registered pages have complete source files', () => {
  const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'))
  assert.equal(app.pages.includes('pages/editor/editor'), false)
  for (const page of app.pages) {
    for (const ext of ['js', 'json', 'wxml', 'wxss']) {
      assert.ok(fs.existsSync(path.join(root, `${page}.${ext}`)), `${page}.${ext}`)
    }
  }
})

test('retired editor is excluded in both project entry points', () => {
  for (const [file, folder] of [['project.config.json', 'pages/editor'], ['../project.config.json', 'miniapp/pages/editor']]) {
    const config = JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'))
    assert.ok(config.packOptions.ignore.some(item => item.type === 'folder' && item.value === folder))
  }
})

test('cached editor page redirects without exposing editor actions', () => {
  let page, destination
  vm.runInNewContext(fs.readFileSync(path.join(root, 'pages/editor/editor.js'), 'utf8'), {
    Page: value => { page = value },
    wx: { reLaunch: options => { destination = options.url } },
  })
  page.onLoad()
  assert.equal(destination, '/pages/index/index')
  assert.deepEqual(Object.keys(page), ['onLoad'])
})
