import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8');
const start = source.indexOf('async function restoreCourseRecord(');
const end = source.indexOf('async function removeCourse()', start);
const restore = source.slice(start, end);

for (const details of [null, {}, 'legacy', []]) {
  test(`history restore tolerates non-array details: ${JSON.stringify(details)}`, async () => {
    const messages = [];
    await vm.runInNewContext(restore + '; restoreCourseRecord(record)', {
      record: { course_id: 1, details }, schedule: { value: { courses: [{ id: 1 }] } },
      notify: text => messages.push(text),
    });
    assert.deepEqual(messages, ['未找到可恢复的变更项']);
  });
}
