import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parse, compileScript } from '@vue/compiler-sfc';

function scriptComponent(name, extra = {}) {
  const source = fs.readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8');
  const { descriptor } = parse(source);
  const result = compileScript(descriptor, { id: name });
  return { source, result, ...extra };
}

test('Android action button is removed and profile owns the retained actions', () => {
  const app = fs.readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  assert.ok(app.includes(`:show-action="currentTab === 'schedule' && !isNative"`));
  assert.ok(app.includes(':show-course-list="!isNative"'));
  const profile = scriptComponent('UserProfileView');
  assert.ok(profile.source.includes(`emit('open-import')`));
  assert.ok(app.includes(`@open-import=`));
  assert.equal(profile.source.includes('delete-schedule'), false);
  assert.equal(profile.source.includes('open-semester-settings'), false);
  assert.equal(profile.source.includes('学期设置'), false);
  assert.equal(profile.source.includes('删除备用课表'), false);
  assert.equal(profile.source.includes('全部课程'), false);
  assert.ok(profile.source.includes('native-actions'));
});

test('all courses has a usable list and no course-center component remains', () => {
  const list = scriptComponent('CourseListModal');
  assert.ok(list.source.includes('全部课程'));
  assert.ok(list.source.includes('filteredGroups'));
  assert.equal(fs.existsSync(new URL('../src/components/CourseCenterModal.vue', import.meta.url)), false);
});
