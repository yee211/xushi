<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue';
import {
  cleanSectionTime,
  courseKey,
  days,
  defaultSectionTimes,
  isDayToday,
  shortDay,
  timeRange,
  weekDayNumber,
  weekMonth,
} from '../utils/schedule.js';

const props = defineProps({
  schedule: { type: Object, default: null },
  week: { type: Number, default: 1 },
  loading: { type: Boolean, default: false },
  colorMap: { type: Map, default: () => new Map() },
});

const emit = defineEmits(['preview-course', 'move-course', 'move-conflict', 'prev-week', 'next-week']);
const gridRef = ref(null);
const transitionName = ref('slide-left');

watch(() => props.week, (newVal, oldVal) => {
  if (newVal > oldVal) {
    transitionName.value = 'slide-left';
  } else if (newVal < oldVal) {
    transitionName.value = 'slide-right';
  }
});

// 水平手势左右滑屏切周 (Swipe to Switch Weeks)
const touchSwipe = reactive({
  startX: 0,
  startY: 0,
  currentX: 0,
  currentY: 0,
  startTime: 0,
  swiping: false,
});

function onGridTouchStart(e) {
  if (drag.active) return;
  if (!e.touches || e.touches.length !== 1) return;
  touchSwipe.startX = e.touches[0].clientX;
  touchSwipe.startY = e.touches[0].clientY;
  touchSwipe.currentX = e.touches[0].clientX;
  touchSwipe.currentY = e.touches[0].clientY;
  touchSwipe.startTime = Date.now();
  touchSwipe.swiping = true;
}

function onGridTouchMove(e) {
  if (!touchSwipe.swiping || drag.active) return;
  if (e.touches && e.touches.length === 1) {
    touchSwipe.currentX = e.touches[0].clientX;
    touchSwipe.currentY = e.touches[0].clientY;
  }
}

function onGridTouchEnd(e) {
  if (!touchSwipe.swiping || drag.active) {
    touchSwipe.swiping = false;
    return;
  }
  touchSwipe.swiping = false;
  const touch = (e.changedTouches && e.changedTouches[0]) || (e.touches && e.touches[0]);
  const endX = touch ? touch.clientX : touchSwipe.currentX;
  const endY = touch ? touch.clientY : touchSwipe.currentY;
  if (endX === undefined) return;
  const dx = endX - touchSwipe.startX;
  const dy = endY - touchSwipe.startY;
  const dt = Date.now() - touchSwipe.startTime;

  // 判定：滑动时间 700ms 内，水平距离超过 35px 且横向位移比纵向明显大
  if (dt < 700 && Math.abs(dx) > 35 && Math.abs(dx) > Math.abs(dy) * 1.1) {
    if (dx < 0) {
      // 左滑 -> 下一周
      transitionName.value = 'slide-left';
      emit('next-week');
    } else {
      // 右滑 -> 上一周
      transitionName.value = 'slide-right';
      emit('prev-week');
    }
  }
}

const drag = reactive({
  active: false,
  pending: false,
  settling: false,
  course: null,
  weekday: 1,
  start: 1,
  pointerId: null,
  pointerType: '',
  x: 0,
  y: 0,
  dx: 0,
  dy: 0,
});
let holdTimer = null;
let settleTimer = null;
let suppressClick = false;
let dragElement = null;

const maxSections = computed(() => {
  const courses = props.schedule?.courses || [];
  const maxInCourses = courses.length ? Math.max(...courses.map(c => c.end_section || 0)) : 10;
  return Math.min(12, Math.max(10, maxInCourses));
});

const gridStyle = computed(() => ({
  gridTemplateRows: `var(--grid-header-height, 46px) repeat(${maxSections.value}, var(--grid-section-height, 68px))`,
}));

const activeCourses = computed(() => {
  return (props.schedule?.courses || [])
    .filter(c => !c.weeks?.length || c.weeks.includes(props.week))
    .map(course => {
      const adjustment = course.adjustments?.find(item => item.week === props.week);
      return adjustment
        ? {
          ...course,
          ...adjustment,
          id: course.id,
          adjustment_id: adjustment.id,
          adjusted_week: props.week,
          original_course: course,
        }
        : course;
    });
});

const displayCourses = computed(() => {
  const result = [];
  const sorted = [...activeCourses.value].sort((a, b) => a.weekday - b.weekday || a.start_section - b.start_section);
  for (const course of sorted) {
    const previous = result[result.length - 1];
    const canMerge = previous
      && courseKey(previous.name) === courseKey(course.name)
      && previous.teacher === course.teacher
      && previous.room === course.room
      && previous.weekday === course.weekday
      && previous.end_section + 1 === course.start_section;
    if (canMerge) {
      previous.end_section = course.end_section;
    } else {
      result.push({ ...course });
    }
  }
  return result;
});

function courseStyle(course) {
  const isDragging = (drag.active || drag.settling) && drag.course?.id === course.id;
  const span = course.end_section - course.start_section + 1;
  return {
    gridColumn: `${course.weekday + 1}`,
    gridRow: `${course.start_section + 1}/${course.start_section + span + 1}`,
    '--course': props.colorMap.get(courseKey(course.name)) || '#5B8DEF',
    '--max-lines': span * 4,
    ...(isDragging ? {
      transform: `translate3d(${drag.dx}px, ${drag.dy}px, 0) scale(1.04)`,
      zIndex: 99,
      willChange: 'transform',
    } : {}),
  };
}

let cachedMetrics = null;

function computeGridMetrics() {
  const grid = gridRef.value;
  if (!grid) return null;
  const rect = grid.getBoundingClientRect();
  const corner = grid.querySelector('.corner')?.getBoundingClientRect();
  const day = grid.querySelector('.day')?.getBoundingClientRect();
  const leftWidth = corner?.width || 48;
  const headerHeight = day?.height || 46;
  return {
    rect,
    leftWidth,
    headerHeight,
    dayWidth: (rect.width - leftWidth) / 7,
    rowHeight: (rect.height - headerHeight) / maxSections.value,
  };
}

function updateDragTarget(clientX, clientY) {
  if (!cachedMetrics) cachedMetrics = computeGridMetrics();
  if (!cachedMetrics || !drag.course) return;
  const { rect, leftWidth, headerHeight, dayWidth, rowHeight } = cachedMetrics;
  const rawDuration = drag.course.end_section - drag.course.start_section + 1;
  const duration = rawDuration <= 2 ? 2 : rawDuration;
  drag.weekday = Math.max(1, Math.min(7, Math.floor((clientX - rect.left - leftWidth) / dayWidth) + 1));
  const rawSection = Math.floor((clientY - rect.top - headerHeight) / rowHeight) + 1;
  // 默认对齐 2 节制大课时 (1-2, 3-4, 5-6, 7-8, 9-10)，起始节只能是奇数 1, 3, 5, 7, 9...
  // 严格禁止出现跨大节的 2-3, 4-5, 6-7, 8-9
  const blockIndex = Math.floor((rawSection - 1) / 2);
  const maxStart = 2 * Math.floor((maxSections.value - duration) / 2) + 1;
  drag.start = Math.max(1, Math.min(maxStart, blockIndex * 2 + 1));
  drag.dx = clientX - drag.x;
  drag.dy = clientY - drag.y;
}

function activateDrag(element) {
  drag.pending = false;
  drag.active = true;
  drag.dx = 0;
  drag.dy = 0;
  suppressClick = true;
  cachedMetrics = computeGridMetrics();
  try {
    element?.setPointerCapture?.(drag.pointerId);
  } catch (_) {}
}

function onWindowPointerMove(event) {
  if (drag.pointerId !== event.pointerId || (!drag.pending && !drag.active)) return;
  if (drag.pending) {
    const distance = Math.hypot(event.clientX - drag.x, event.clientY - drag.y);
    if (drag.pointerType !== 'touch' && distance > 4) {
      activateDrag(dragElement);
      if (event.cancelable) event.preventDefault();
      updateDragTarget(event.clientX, event.clientY);
    } else if (drag.pointerType === 'touch' && distance > 10) {
      window.clearTimeout(holdTimer);
      resetDrag();
    }
    return;
  }
  if (drag.active) {
    if (event.cancelable) event.preventDefault();
    updateDragTarget(event.clientX, event.clientY);
  }
}

function onWindowPointerUp(event) {
  if (drag.pointerId !== event.pointerId) return;
  finishDrag(event, false);
}

function onWindowPointerCancel(event) {
  if (drag.pointerId !== event.pointerId) return;
  finishDrag(event, true);
}

function removeWindowListeners() {
  window.removeEventListener('pointermove', onWindowPointerMove);
  window.removeEventListener('pointerup', onWindowPointerUp);
  window.removeEventListener('pointercancel', onWindowPointerCancel);
}

function resetDrag() {
  removeWindowListeners();
  window.clearTimeout(holdTimer);
  window.clearTimeout(settleTimer);
  if (dragElement && drag.pointerId != null) {
    try {
      dragElement.releasePointerCapture(drag.pointerId);
    } catch (_) {}
  }
  drag.active = false;
  drag.pending = false;
  drag.settling = false;
  drag.course = null;
  drag.pointerId = null;
  drag.dx = 0;
  drag.dy = 0;
  dragElement = null;
  cachedMetrics = null;
  window.setTimeout(() => { suppressClick = false; }, 50);
}

function beginDrag(event, course) {
  if (event.button !== undefined && event.button !== 0) return;
  if (drag.active || drag.pending || drag.settling) {
    resetDrag();
  }
  drag.course = course;
  drag.pointerId = event.pointerId;
  drag.pointerType = event.pointerType || 'mouse';
  dragElement = event.currentTarget;
  drag.x = event.clientX;
  drag.y = event.clientY;
  drag.weekday = course.weekday;
  const rawDuration = course.end_section - course.start_section + 1;
  const duration = rawDuration <= 2 ? 2 : rawDuration;
  const blockIndex = Math.floor((course.start_section - 1) / 2);
  const maxStart = 2 * Math.floor((maxSections.value - duration) / 2) + 1;
  drag.start = Math.max(1, Math.min(maxStart, blockIndex * 2 + 1));
  drag.dx = 0;
  drag.dy = 0;
  drag.settling = false;
  drag.pending = true;
  cachedMetrics = computeGridMetrics();

  window.addEventListener('pointermove', onWindowPointerMove, { passive: false });
  window.addEventListener('pointerup', onWindowPointerUp);
  window.addEventListener('pointercancel', onWindowPointerCancel);

  if (drag.pointerType === 'touch') {
    holdTimer = window.setTimeout(() => activateDrag(dragElement), 350);
  }
}

function finishDrag(event, cancelled = false) {
  window.clearTimeout(holdTimer);
  if (drag.active && drag.course) {
    const sourceCourse = drag.course;
    const targetWeekday = drag.weekday;
    const targetStart = drag.start;
    const rawDuration = drag.course.end_section - drag.course.start_section + 1;
    const duration = rawDuration <= 2 ? 2 : rawDuration;
    const end = targetStart + duration - 1;
    const conflict = activeCourses.value.some(course => course.id !== sourceCourse.id
      && course.weekday === targetWeekday
      && targetStart <= course.end_section && end >= course.start_section);
    const changed = targetWeekday !== sourceCourse.weekday
      || targetStart !== sourceCourse.start_section
      || end !== sourceCourse.end_section;
    const shouldMove = !cancelled && !conflict && changed;

    if (!cancelled && conflict) {
      emit('move-conflict');
    } else if (shouldMove) {
      emit('move-course', {
        course: sourceCourse,
        weekday: targetWeekday,
        start_section: targetStart,
        end_section: end,
      });
    }
  }
  resetDrag();
}

function openCourse(course) {
  if (!suppressClick) emit('preview-course', course);
}

onUnmounted(() => {
  resetDrag();
});
</script>

<template>
  <section
    class="schedule glass"
    :class="{ busy: loading }"
    aria-label="每周课程表"
    tabindex="0"
    style="touch-action: pan-y;"
    @touchstart.passive="onGridTouchStart"
    @touchmove.passive="onGridTouchMove"
    @touchend.passive="onGridTouchEnd"
    @touchcancel.passive="onGridTouchEnd"
  >
    <div v-if="loading" class="state">正在读取课表…</div>
    <div v-else-if="!schedule" class="state">还没有课表</div>
    <div v-else class="schedule-carousel-viewport">
      <Transition :name="transitionName">
        <div
          :key="week"
          ref="gridRef"
          class="grid"
          :class="{ 'is-dragging': drag.active || drag.settling }"
          :style="gridStyle"
        >
          <div class="corner">
            <span class="corner-month">{{ weekMonth(schedule.start_date, week) }}</span>
            <span class="corner-label">节次</span>
          </div>
          <div
            v-for="(day, index) in days"
            :key="day"
            class="day"
            :class="{ 'is-today': isDayToday(schedule.start_date, index + 1, week, schedule) }"
          >
            <span class="day-date">{{ weekDayNumber(schedule.start_date, index + 1, week) }}</span>
            <b class="day-name">{{ shortDay(day) }}</b>
          </div>
          <template v-for="section in maxSections" :key="section">
            <div class="section" :style="{ gridColumn: 1, gridRow: section + 1 }">
              <b class="section-num">{{ section }}</b>
              <div class="section-times">
                <span>{{ cleanSectionTime(defaultSectionTimes[section - 1]?.[0]) }}</span>
                <span>{{ cleanSectionTime(defaultSectionTimes[section - 1]?.[1]) }}</span>
              </div>
            </div>
            <div
              v-for="day in 7"
              :key="day"
              class="cell"
              :style="{ gridColumn: day + 1, gridRow: section + 1 }"
            ></div>
          </template>
          <!-- 拖拽对齐落点预览 (1-2, 3-4, 5-6, 7-8, 9-10) -->
          <div
            v-if="drag.active && drag.course"
            class="drag-target-slot"
            :style="{
              gridColumn: drag.weekday + 1,
              gridRow: `${drag.start + 1} / ${drag.start + (drag.course.end_section - drag.course.start_section + 1 <= 2 ? 2 : (drag.course.end_section - drag.course.start_section + 1)) + 1}`,
            }"
          ></div>
          <button
            v-for="course in displayCourses"
            :key="`${course.id}-${course.adjusted_week || 'regular'}`"
            class="course"
            :class="{ dragging: (drag.active || drag.settling) && drag.course?.id === course.id, settling: drag.settling && drag.course?.id === course.id }"
            :style="courseStyle(course)"
            @click="openCourse(course)"
            @pointerdown="beginDrag($event, course)"
            @contextmenu.prevent
          >
            <span class="course-text">
              <span v-if="course.adjusted_week" class="course-adjusted">调</span>
              <span class="course-name">{{ course.name }}</span>
              <span class="course-room" v-if="course.room">({{ course.room }})</span>
              <span class="course-teacher" v-if="course.teacher">{{ course.teacher }}</span>
            </span>
          </button>
        </div>
      </Transition>
    </div>
  </section>
</template>
