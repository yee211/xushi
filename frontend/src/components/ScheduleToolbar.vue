<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import {
  courseLessonCount,
  isScheduleActiveToday,
  scheduleWeekCount,
  uniqueCourseCount,
  weekRange,
} from '../utils/schedule.js';

const props = defineProps({
  schedules: { type: Array, default: () => [] },
  schedule: { type: Object, default: null },
  week: { type: Number, default: 1 },
  currentWeek: { type: Number, default: 1 },
  weekOptions: { type: Array, default: () => [] },
});

const emit = defineEmits([
  'update:week',
  'select-schedule',
  'go-current-week',
  'open-semester-settings',
  'open-adjustments',
  'open-course-center',
]);

const weekMenuOpen = ref(false);
const termMenuOpen = ref(false);

const isActiveSchedule = computed(() => isScheduleActiveToday(props.schedule));

function toggleWeekMenu() {
  weekMenuOpen.value = !weekMenuOpen.value;
  if (weekMenuOpen.value) {
    termMenuOpen.value = false;
  }
}

function toggleTermMenu() {
  if (props.schedules.length > 1) {
    termMenuOpen.value = !termMenuOpen.value;
    if (termMenuOpen.value) {
      weekMenuOpen.value = false;
    }
  } else {
    emit('open-semester-settings');
  }
}

function closeAllMenus(event) {
  if (!event.target.closest('.week-menu')) {
    weekMenuOpen.value = false;
  }
  if (!event.target.closest('.term-menu')) {
    termMenuOpen.value = false;
  }
}

function selectWeek(value) {
  emit('update:week', value);
  weekMenuOpen.value = false;
}

function onGoCurrentWeek() {
  emit('go-current-week');
  weekMenuOpen.value = false;
}

function prevWeek() {
  emit('update:week', Math.max(1, props.week - 1));
}

function nextWeek() {
  emit('update:week', Math.min(props.weekOptions.length, props.week + 1));
}

function onPickSchedule(id) {
  emit('select-schedule', id);
  termMenuOpen.value = false;
}

onMounted(() => {
  document.addEventListener('click', closeAllMenus);
});

onUnmounted(() => {
  document.removeEventListener('click', closeAllMenus);
});
</script>

<template>
  <section class="toolbar simplified-toolbar minimal-card" aria-label="学期与周次">
    <!-- 左边：学期名字 -->
    <div class="simplified-term-section" @click.stop>
      <button
        type="button"
        class="simplified-term-btn"
        :aria-expanded="termMenuOpen"
        aria-haspopup="listbox"
        @click="toggleTermMenu"
      >
        <span class="term-title-text">{{ schedule?.term || schedule?.name || '我的课表' }}</span>
        <span v-if="schedules.length > 1" class="dropdown-caret" :class="{ open: termMenuOpen }">⌄</span>
      </button>

      <!-- 学期下拉卡片菜单 -->
      <div v-if="termMenuOpen" class="term-menu-panel glass" role="listbox" aria-label="选择学期">
        <div class="term-menu-head">
          <b>切换学期课表</b>
          <span class="term-count-tip">共 {{ schedules.length }} 个学期</span>
        </div>
        <div class="term-menu-list">
          <button
            v-for="item in schedules"
            :key="item.id"
            type="button"
            class="term-card-option"
            :class="{ selected: schedule?.id === item.id }"
            :aria-selected="schedule?.id === item.id"
            @click="onPickSchedule(item.id)"
          >
            <div class="term-card-main">
              <div class="term-card-title-row">
                <span class="term-card-title">{{ item.term || item.name || `课表 ${item.id}` }}</span>
                <span v-if="isScheduleActiveToday(item)" class="status-pill active">进行中</span>
                <span v-else class="status-pill history">往期</span>
              </div>
              <div class="term-card-meta">
                <span v-if="item.start_date && item.end_date" class="term-dates">
                  {{ item.start_date.slice(0, 10) }} ~ {{ item.end_date.slice(0, 10) }}
                </span>
                <span v-else class="term-dates">日期未设置</span>
                <span class="term-courses-count">
                  {{ uniqueCourseCount(item.courses) }} 门课程 · 共 {{ courseLessonCount(item.courses, scheduleWeekCount(item)) }} 节课
                </span>
              </div>
            </div>
            <span v-if="schedule?.id === item.id" class="term-selected-icon">✓</span>
          </button>
        </div>
        <div class="term-menu-footer">
          <button
            type="button"
            class="term-settings-btn"
            @click="emit('open-course-center'); termMenuOpen = false;"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
            </svg>
            <span>课表中心 · 全部课程</span>
          </button>
          <button
            type="button"
            class="term-settings-btn"
            @click="emit('open-semester-settings'); termMenuOpen = false;"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span>学期与作息设置</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 右边：周数显示与切换 -->
    <div class="simplified-right-actions">
      <div class="simplified-week-section" @click.stop>
        <button
          type="button"
          class="simplified-week-btn"
          :aria-expanded="weekMenuOpen"
          aria-haspopup="listbox"
          @click="toggleWeekMenu"
        >
          <span class="week-number-display">第 {{ week }} 周</span>
          <span v-if="isActiveSchedule && week === currentWeek" class="week-badge-today">本周</span>
          <span class="dropdown-caret" :class="{ open: weekMenuOpen }">⌄</span>
        </button>

      <!-- 周次下拉选择卡片菜单 -->
      <div v-if="weekMenuOpen" class="week-menu-panel glass" role="listbox" aria-label="选择周次">
        <div class="week-menu-head">
          <b>选择周次</b>
          <button type="button" class="uiverse-button" @click="onGoCurrentWeek">
            回到本周
          </button>
        </div>
        <div class="week-menu-grid">
          <button
            v-for="item in weekOptions"
            :key="item"
            type="button"
            class="week-option"
            :class="{ selected: week === item }"
            :aria-selected="week === item"
            @click="selectWeek(item)"
          >
            <b>第{{ item }}周</b><small>{{ weekRange(schedule?.start_date, item) }}</small>
          </button>
        </div>
      </div>
    </div>
    </div>
  </section>
</template>

<style scoped>
.term-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.term-status-line {
  margin: 0 !important;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.history-pill {
  font-size: 0.68rem;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.25);
  color: #64748b;
  font-weight: 600;
}
.term-edit-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px !important;
  font-size: 0.72rem !important;
  border-radius: 999px !important;
  color: #64748b !important;
  cursor: pointer;
}
.term-edit-btn:hover {
  color: #0284c7 !important;
}

/* 学期切换菜单 */
.term-menu {
  position: relative;
  display: inline-block;
  max-width: 100%;
}

.term-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 14px;
  border-radius: 999px;
  cursor: pointer;
  max-width: 100%;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}

.term-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(340px, 55vw);
}

.term-trigger i {
  font-style: normal;
  font-size: 0.95rem;
  line-height: 1;
  color: #64748b;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.term-trigger i.open {
  transform: rotate(180deg);
}

.term-menu-panel {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: auto;
  width: min(380px, calc(100vw - 32px));
  box-sizing: border-box;
  padding: 14px;
  border-radius: 20px;
  z-index: 50;
  animation: menu-spring 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.4);
}

.week-menu-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  left: auto;
  width: min(360px, calc(100vw - 32px));
  box-sizing: border-box;
  padding: 14px;
  border-radius: 20px;
  z-index: 50;
  animation: menu-spring 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.4);
}

.term-menu-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.3);
  font-size: 0.85rem;
  font-weight: 600;
  color: #0f172a;
}

.term-count-tip {
  font-size: 0.72rem;
  color: #64748b;
  font-weight: 500;
}

.term-menu-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: min(52vh, 340px);
  overflow-y: auto;
  padding: 2px;
}

.term-card-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.7);
  text-align: left;
  cursor: pointer;
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 2px 8px rgba(50, 75, 110, 0.05);
}

.term-card-option:hover {
  background: rgba(255, 255, 255, 0.88);
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(50, 75, 110, 0.12);
}

.term-card-option.selected {
  background: var(--minimal-bg-surface);
  border-color: var(--minimal-text-primary);
  box-shadow: 0 2px 8px rgba(17, 24, 39, 0.08);
}

.term-card-main {
  flex: 1;
  min-width: 0;
}

.term-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.term-card-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-pill {
  font-size: 0.68rem;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 600;
  white-space: nowrap;
}

.status-pill.active {
  background: rgba(17, 24, 39, 0.08);
  color: #111827;
  border: 1px solid rgba(17, 24, 39, 0.2);
}

.status-pill.history {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}

.term-card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 0.74rem;
  color: #64748b;
}

.term-selected-icon {
  font-size: 1.15rem;
  font-weight: bold;
  color: #111827;
  padding-left: 4px;
}

/* 夜间模式适配 */
html[data-bg="night"] .term-trigger {
  color: #f8fafc;
}
html[data-bg="night"] .term-trigger i {
  color: #94a3b8;
}
html[data-bg="night"] .term-menu-panel {
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.12);
}
html[data-bg="night"] .term-menu-head {
  color: #f8fafc;
  border-bottom-color: rgba(255, 255, 255, 0.12);
}
html[data-bg="night"] .term-count-tip {
  color: #94a3b8;
}
html[data-bg="night"] .term-card-option {
  background: rgba(30, 41, 59, 0.65);
  border-color: rgba(148, 163, 184, 0.25);
}
html[data-bg="night"] .term-card-option:hover {
  background: rgba(51, 65, 85, 0.85);
}
html[data-bg="night"] .term-card-option.selected {
  background: rgba(241, 245, 249, 0.12);
  border-color: #f1f5f9;
}
html[data-bg="night"] .term-card-title {
  color: #f8fafc;
}
html[data-bg="night"] .status-pill.active {
  background: rgba(241, 245, 249, 0.12);
  color: #f1f5f9;
  border-color: rgba(241, 245, 249, 0.3);
}
html[data-bg="night"] .status-pill.history {
  background: rgba(71, 85, 105, 0.4);
  color: #94a3b8;
}
html[data-bg="night"] .term-card-meta {
  color: #94a3b8;
}
html[data-bg="night"] .term-selected-icon {
  color: #f1f5f9;
}

/* 移动端与不同手机屏幕适配：缩小尺寸与防止右侧溢出 */
@media (max-width: 680px) {
  .term-meta-row {
    margin-bottom: 0;
    gap: 6px;
    flex-shrink: 0;
  }

  .term-status-line {
    font-size: 0.72rem;
    white-space: nowrap;
  }

  .history-pill {
    font-size: 0.64rem;
    padding: 1px 5px;
  }

  .term-edit-btn {
    padding: 2px 6px !important;
    font-size: 0.68rem !important;
    height: 26px;
  }

  .term-menu {
    flex: 1;
    min-width: 0;
    display: flex;
    justify-content: flex-end;
  }

  .term-trigger {
    padding: 2px 9px;
    font-size: 0.82rem;
    font-weight: 600;
    gap: 4px;
    height: 30px;
    border-radius: 20px;
    max-width: 100%;
  }

  .term-name {
    font-size: 0.82rem;
    max-width: 100%;
  }

  .term-trigger i {
    font-size: 0.82rem;
  }

  /* 学期下拉面板：靠左对齐向右展开，杜绝超出屏幕左边缘 */
  .term-menu-panel {
    left: 0 !important;
    right: auto !important;
    width: min(340px, calc(100vw - 24px));
    max-width: calc(100vw - 24px);
    padding: 10px;
    border-radius: 16px;
    box-sizing: border-box;
  }

  .term-menu-head {
    font-size: 0.78rem;
    margin-bottom: 8px;
    padding-bottom: 6px;
  }

  .term-count-tip {
    font-size: 0.68rem;
  }

  .term-card-option {
    padding: 8px 10px;
    border-radius: 12px;
    gap: 8px;
  }

  .term-card-title {
    font-size: 0.86rem;
  }

  .status-pill {
    font-size: 0.64rem;
    padding: 1px 5px;
  }

  .term-card-meta {
    font-size: 0.68rem;
    gap: 6px;
  }

  .term-selected-icon {
    font-size: 0.98rem;
  }

  /* 周次下拉面板：靠右对齐向左展开，杜绝超出屏幕右边缘 */
  .week-menu-panel {
    right: 0 !important;
    left: auto !important;
    width: min(320px, calc(100vw - 24px));
    max-width: calc(100vw - 24px);
    box-sizing: border-box;
    padding: 10px;
    border-radius: 16px;
  }
}

/* 窄屏手机特殊优化 (<=360px，如小屏机型或开启高 DPI 缩放模式) */
@media (max-width: 360px) {
  .term-meta-row {
    gap: 4px;
  }

  .term-status-line span:first-child {
    font-size: 0.68rem;
  }

  .term-edit-btn {
    padding: 1px 5px !important;
    font-size: 0.64rem !important;
  }

  .term-trigger {
    padding: 2px 7px;
    font-size: 0.76rem;
    height: 28px;
  }

  .term-name {
    font-size: 0.76rem;
  }

  .term-menu-panel {
    left: 0 !important;
    right: auto !important;
    width: calc(100vw - 16px) !important;
    max-width: calc(100vw - 16px) !important;
    padding: 8px;
  }

  .week-menu-panel {
    right: 0 !important;
    left: auto !important;
    width: calc(100vw - 16px) !important;
    max-width: calc(100vw - 16px) !important;
    padding: 8px;
  }
}
</style>
