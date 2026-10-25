import test from 'node:test';
import assert from 'node:assert/strict';
import { scheduleWeekCount, termWeek, weekRange, weekDayDate, weekMonth, weekDayNumber, isDayToday } from '../src/utils/schedule.js';

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


test('all displayed dates use the same Monday as teaching weeks', () => {
  assert.equal(weekRange('2026-10-07', 2), '10.12–10.18');
  assert.equal(weekDayDate('2026-10-07', 1, 2), '10.12');
  assert.equal(weekDayNumber('2026-10-07', 7, 2), '18');
  assert.equal(weekMonth('2026-09-30', 1), '09月');
});


test('week count includes the partial first and last natural weeks', () => {
  assert.equal(scheduleWeekCount({ start_date: '2026-10-07', end_date: '2026-10-13' }), 2);
  assert.equal(scheduleWeekCount({ start_date: '2026-10-07', end_date: '2026-10-11' }), 1);
});
