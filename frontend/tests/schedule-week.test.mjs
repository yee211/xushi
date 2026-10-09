import test from 'node:test';
import assert from 'node:assert/strict';
import { termWeek } from '../src/utils/schedule.js';

test('a Wednesday term start changes teaching week on the next Monday', () => {
  const RealDate = globalThis.Date;
  globalThis.Date = class extends RealDate {
    constructor(...args) { super(...(args.length ? args : ['2026-10-12T12:00:00'])); }
  };
  try {
    assert.equal(termWeek('2026-10-07', 20), 2);
  } finally {
    globalThis.Date = RealDate;
  }
});
