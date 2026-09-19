/**
 * 课表业务计算与格式化工具函数。
 */

export const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

// 默认 1~12 节作息时间表
export const defaultSectionTimes = [
  ['08:20', '09:05'], ['09:15', '10:00'], ['10:20', '11:05'], ['11:15', '12:00'],
  ['14:00', '14:45'], ['14:55', '15:40'], ['16:00', '16:45'], ['16:55', '17:40'],
  ['19:00', '19:45'], ['19:55', '20:40'], ['20:50', '21:35'], ['21:45', '22:30'],
];

// 极简低饱和淡雅调色板 (Minimalist Muted / Morandi Palette)
export const courseColors = [
  '#637D91', // 烟灰蓝 (Muted Slate Blue)
  '#7A8F7D', // 鼠尾草绿 (Sage Green)
  '#9B8477', // 暖陶土灰 (Warm Taupe)
  '#7D7A8E', // 灰雾紫 (Dusty Lavender)
  '#6E8B8B', // 冰湖青 (Muted Teal)
  '#9E8B6D', // 亚麻原木 (Soft Ochre)
  '#6E7B94', // 黛蓝石 (Dusk Indigo)
  '#9E7B87', // 烟粉豆沙 (Dusty Rose)
  '#7E8B73', // 橄榄软苔 (Muted Olive)
  '#687E84', // 冷灰松青 (Ash Pine)
  '#9E7E73', // 浅赭暖灰 (Soft Terracotta)
  '#728198', // 雾霾蓝 (Fog Blue)
  '#8E8177', // 摩卡米灰 (Muted Mocha)
  '#6B8A7E', // 柔青苔绿 (Soft Forest)
  '#8C7C8C', // 柔紫灰 (Muted Plum)
  '#648291', // 海盐淡蓝 (Sea Salt Blue)
];

export const emptyCourse = () => ({
  id: null,
  name: '',
  teacher: '',
  room: '',
  weekday: 1,
  start_section: 1,
  end_section: 2,
  weeks: '1-16',
  color: '#637D91',
});

export function parseWeeks(text) {
  const result = [];
  String(text || '').split(/[,，]/).forEach(part => {
    const [a, b] = part.trim().split('-').map(Number);
    if (a && b) {
      for (let i = a; i <= b; i++) result.push(i);
    } else if (a) {
      result.push(a);
    }
  });
  return [...new Set(result)].filter(n => n >= 1 && n <= 30).sort((a, b) => a - b);
}

export function formatWeeks(weeks) {
  if (!weeks?.length) return '';
  const ranges = [];
  let start = weeks[0], last = start;
  for (const n of weeks.slice(1)) {
    if (n === last + 1) {
      last = n;
      continue;
    }
    ranges.push(start === last ? `${start}` : `${start}-${last}`);
    start = last = n;
  }
  ranges.push(start === last ? `${start}` : `${start}-${last}`);
  return ranges.join(',');
}

export function localDate(value) {
  const [year, month, day] = String(value || '').slice(0, 10).split('-').map(Number);
  return year && month && day ? new Date(year, month - 1, day) : null;
}

export function isoDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function defaultEndDate(startValue, weeks = 20) {
  const start = localDate(startValue);
  if (!start) return '';
  const safeWeeks = Math.max(1, Math.min(30, Number(weeks) || 20));
  start.setDate(start.getDate() + safeWeeks * 7 - 1);
  return isoDate(start);
}

export function scheduleWeekCount(schedule) {
  const start = localDate(schedule?.start_date);
  const end = localDate(schedule?.end_date);
  if (start && end) {
    const daysDiff = Math.floor((end - start) / 86400000) + 1;
    return Math.max(1, Math.min(30, Math.ceil(daysDiff / 7)));
  }
  const courseWeeks = schedule?.courses?.flatMap(course => course.weeks || []) || [];
  return Math.min(30, Math.max(20, ...courseWeeks, 20));
}

export function isScheduleActiveToday(schedule) {
  const start = localDate(schedule?.start_date);
  if (!start) return false;
  const totalWeeks = scheduleWeekCount(schedule);
  const end = localDate(schedule?.end_date) || new Date(start.getTime() + (totalWeeks * 7 - 1) * 86400000);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startTime = new Date(start.getFullYear(), start.getMonth(), start.getDate()).getTime();
  const endTime = new Date(end.getFullYear(), end.getMonth(), end.getDate(), 23, 59, 59).getTime();
  return today >= startTime && today <= endTime;
}

export function findCurrentSchedule(schedules) {
  if (!schedules?.length) return null;
  // 1. 优先定位包含当前日期的进行中学期
  const active = schedules.find(s => isScheduleActiveToday(s));
  if (active) return active;

  // 2. 若处于假期/无严格匹配，选择开学日期最新的课表
  const withDates = schedules.filter(s => s.start_date);
  if (withDates.length) {
    return [...withDates].sort((a, b) => (b.start_date > a.start_date ? 1 : -1) || (b.id - a.id))[0];
  }

  // 3. 兜底返回最新课表
  return [...schedules].sort((a, b) => b.id - a.id)[0];
}

export function suggestSemesterDates(termStr) {
  const text = String(termStr || '').trim();
  const match = text.match(/(\d{4})\s*[-–—/]\s*(\d{4})[^\d]*(?:第\s*)?([12一二秋春])/);
  if (match) {
    const year1 = Number(match[1]);
    const termType = match[3];
    const isFirstTerm = termType === '1' || termType === '一' || termType === '秋';

    if (isFirstTerm) {
      const sept1 = new Date(year1, 8, 1);
      const day = sept1.getDay();
      const mondayOffset = day === 0 ? 1 : (day === 1 ? 0 : 8 - day);
      const start = new Date(year1, 8, 1 + mondayOffset);
      const end = new Date(start.getTime() + (20 * 7 - 1) * 86400000);
      return { start: isoDate(start), end: isoDate(end) };
    } else {
      const year2 = match[2] ? Number(match[2]) : year1 + 1;
      const mar1 = new Date(year2, 2, 1);
      const day = mar1.getDay();
      const mondayOffset = day === 0 ? 1 : (day === 1 ? 0 : 8 - day);
      const start = new Date(year2, 2, 1 + mondayOffset);
      const end = new Date(start.getTime() + (20 * 7 - 1) * 86400000);
      return { start: isoDate(start), end: isoDate(end) };
    }
  }

  return null;
}

export function termWeek(startDate, totalWeeks = 20, schedule = null) {
  if (!startDate) return 1;
  const start = localDate(startDate);
  if (!start) return 1;

  if (schedule && !isScheduleActiveToday(schedule)) {
    // 历史或未来学期：打开时默认从第 1 周开始看起
    return 1;
  }

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const elapsedDays = Math.floor((today - start) / 86400000);
  const calculated = Math.floor(elapsedDays / 7) + 1;
  return Math.max(1, Math.min(totalWeeks, calculated));
}

export function weekRange(startDate, weekNumber) {
  const start = localDate(startDate);
  if (!start) return '日期待设置';
  start.setDate(start.getDate() + (weekNumber - 1) * 7);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const format = date => `${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')}`;
  return `${format(start)}–${format(end)}`;
}

export function weekDayDate(startDate, dayNumber, weekNumber) {
  const start = localDate(startDate);
  if (!start) return '日期待设置';
  start.setDate(start.getDate() + (weekNumber - 1) * 7 + dayNumber - 1);
  return `${String(start.getMonth() + 1).padStart(2, '0')}.${String(start.getDate()).padStart(2, '0')}`;
}

export function weekMonth(startDate, weekNumber) {
  const start = localDate(startDate);
  if (!start) return '';
  start.setDate(start.getDate() + (weekNumber - 1) * 7);
  return `${String(start.getMonth() + 1).padStart(2, '0')}月`;
}

export function weekDayNumber(startDate, dayNumber, weekNumber) {
  const start = localDate(startDate);
  if (!start) return '';
  start.setDate(start.getDate() + (weekNumber - 1) * 7 + dayNumber - 1);
  return String(start.getDate()).padStart(2, '0');
}

export function shortDay(day) {
  return String(day || '').replace('周', '');
}

export function isDayToday(startDate, dayNumber, weekNumber, schedule = null) {
  if (schedule && !isScheduleActiveToday(schedule)) {
    return false;
  }
  const start = localDate(startDate);
  if (!start) return false;
  start.setDate(start.getDate() + (weekNumber - 1) * 7 + dayNumber - 1);
  const now = new Date();
  return start.getFullYear() === now.getFullYear()
    && start.getMonth() === now.getMonth()
    && start.getDate() === now.getDate();
}


export function cleanSectionTime(timeStr) {
  return String(timeStr || '').replace(/^0/, '');
}

export function courseKey(name) {
  return String(name || '未命名课程').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
}

export function uniqueCourseCount(courses) {
  return new Set((courses || []).map(course => courseKey(course.name))).size;
}

export function courseLessonCount(courses, fallbackWeeks = 20) {
  return (courses || []).reduce((total, course) => {
    const weekCount = course.weeks?.length || fallbackWeeks;
    const sectionCount = Math.max(1, (course.end_section || 1) - (course.start_section || 1) + 1);
    return total + weekCount * Math.ceil(sectionCount / 2);
  }, 0);
}

export function buildCourseColorMap(courses) {
  const names = [...new Set((courses || []).map(course => courseKey(course.name)))].sort();
  return new Map(names.map((name, index) => [name, courseColors[index % courseColors.length]]));
}

export function timeRange(course, sectionTimes = defaultSectionTimes) {
  if (!course) return '';
  const start = sectionTimes[course.start_section - 1]?.[0] || '';
  const end = sectionTimes[course.end_section - 1]?.[1] || '';
  return start && end ? `${start}-${end}` : '';
}
