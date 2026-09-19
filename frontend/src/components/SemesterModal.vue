<script setup>
import { computed, ref, watch } from 'vue';
import {
  defaultEndDate,
  isScheduleActiveToday,
  localDate,
  scheduleWeekCount,
  termWeek,
} from '../utils/schedule.js';

const props = defineProps({
  open: { type: Boolean, default: false },
  schedule: { type: Object, default: null },
  saving: { type: Boolean, default: false },
});

const emit = defineEmits(['close', 'save', 'delete']);

const form = ref({
  name: '',
  term: '',
  start_date: '',
  end_date: '',
});

const errorMsg = ref('');
const noticeMsg = ref('');
const weekCount = ref(20);

function scheduleForm(sched) {
  return {
    name: sched?.name || '',
    term: sched?.term || '',
    start_date: sched?.start_date?.slice(0, 10) || '',
    end_date: sched?.end_date?.slice(0, 10) || '',
  };
}

function resetForm() {
  form.value = scheduleForm(props.schedule);
  weekCount.value = props.schedule?.start_date
    ? scheduleWeekCount(props.schedule)
    : 20;
  errorMsg.value = '';
  noticeMsg.value = '';
}

watch(
  [() => props.open, () => props.schedule],
  ([open]) => {
    if (open) resetForm();
  },
  { immediate: true }
);

const hasChanges = computed(() => {
  return JSON.stringify(form.value) !== JSON.stringify(scheduleForm(props.schedule));
});
const hasInvalidDates = computed(() => Boolean(
  form.value.start_date
  && form.value.end_date
  && form.value.end_date < form.value.start_date
));
const canSave = computed(() => Boolean(
  form.value.name.trim()
  && !hasInvalidDates.value
  && hasChanges.value
  && !props.saving
));

const totalWeeks = computed(() => {
  return scheduleWeekCount({
    start_date: form.value.start_date,
    end_date: form.value.end_date,
    courses: props.schedule?.courses,
  });
});

const statusText = computed(() => {
  if (!form.value.start_date) return '尚未设置开学日期';
  const dummy = {
    start_date: form.value.start_date,
    end_date: form.value.end_date,
  };
  const active = isScheduleActiveToday(dummy);
  if (active) {
    const curr = termWeek(form.value.start_date, totalWeeks.value);
    return `进行中 · 当前为第 ${curr} 周`;
  }
  const start = localDate(form.value.start_date);
  const now = new Date();
  if (start && start > now) {
    return '未开学 · 将在开学后自动生效';
  }
  return '历史学期 · 已结束，浏览时默认显示第 1 周';
});

const isActiveToday = computed(() => {
  return isScheduleActiveToday({
    start_date: form.value.start_date,
    end_date: form.value.end_date,
  });
});

function applyWeekCount() {
  if (!form.value.start_date) {
    errorMsg.value = '请先选择开学日期';
    return;
  }
  const weeks = Math.max(1, Math.min(30, Number(weekCount.value) || 20));
  weekCount.value = weeks;
  form.value.end_date = defaultEndDate(form.value.start_date, weeks);
  errorMsg.value = '';
  noticeMsg.value = `已按 ${weeks} 周推算，结束日期为 ${form.value.end_date}。`;
}

function onSave() {
  errorMsg.value = '';
  noticeMsg.value = '';
  if (!form.value.name.trim()) {
    errorMsg.value = '课表名称不能为空';
    return;
  }
  if (form.value.start_date && form.value.end_date && form.value.end_date < form.value.start_date) {
    errorMsg.value = '学期结束日期不能早于开学日期';
    return;
  }
  emit('save', {
    name: form.value.name.trim(),
    term: form.value.term.trim(),
    start_date: form.value.start_date || null,
    end_date: form.value.end_date || null,
  });
}
</script>

<template>
  <div v-if="open" class="backdrop" @click.self="emit('close')">
    <form class="modal" @submit.prevent="onSave">
      <div class="modal-head">
        <div>
          <p>学期与日期管理</p>
          <h2>学期设置</h2>
        </div>
        <button type="button" class="icon" @click="emit('close')">×</button>
      </div>

      <div class="status-card" :class="{ active: isActiveToday }">
        <span class="status-dot"></span>
        <div class="status-info">
          <b>{{ statusText }}</b>
          <small>根据开学与结束日期推算，课表共 {{ totalWeeks }} 周</small>
        </div>
      </div>

      <label>
        课表名称
        <input v-model="form.name" required maxlength="80" placeholder="例如：我的课表">
      </label>

      <label>
        所属学期
        <input v-model="form.term" maxlength="80" placeholder="例如：2026-2027学年第1学期">
      </label>

      <div class="fields">
        <label>
          开学日期 (周一)
          <input v-model="form.start_date" type="date">
        </label>
        <label>
          学期周数
          <input v-model.number="weekCount" type="number" min="1" max="30" inputmode="numeric">
        </label>
      </div>

      <div class="date-result">
        <label>
          结束日期 (周日)
          <input v-model="form.end_date" type="date" readonly>
        </label>
        <button
          type="button"
          class="calc-week-btn"
          :disabled="!form.start_date || !weekCount || saving"
          @click="applyWeekCount"
        >
          按周数推算结束日期
        </button>
      </div>

      <p v-if="errorMsg" class="import-inline-error">{{ errorMsg }}</p>
      <p v-else-if="noticeMsg" class="date-notice">{{ noticeMsg }}</p>

      <p class="import-help">
        提示：每个学年、学期拥有独立的开学日期与周数。历史学期打开时会自动保持独立定位，不会影响当前学期的“今天”高亮与自动选周。
      </p>

      <div class="modal-actions semester-modal-actions">
        <button
          v-if="schedule?.id"
          type="button"
          class="danger uiverse-button semester-btn-delete"
          :disabled="saving"
          @click="emit('delete')"
        >
          删除此课表
        </button>
        <div class="semester-btn-group">
          <button class="uiverse-button semester-btn-cancel" type="button" :disabled="saving" @click="emit('close')">取消</button>
          <button class="primary uiverse-button semester-btn-save" type="submit" :disabled="!canSave">
            {{ saving ? '保存中…' : hasChanges ? '保存设置' : '已保存' }}
          </button>
        </div>
      </div>
    </form>
  </div>
</template>

<style scoped>
.status-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.10);
  border: 1px solid var(--minimal-border);
  margin-bottom: 4px;
}
.status-card.active {
  background: rgba(17, 24, 39, 0.06);
  border-color: rgba(17, 24, 39, 0.18);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  flex-shrink: 0;
}
.status-card.active .status-dot {
  background: #111827;
  box-shadow: 0 0 0 3px rgba(17, 24, 39, 0.12);
}
.status-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.status-info b {
  font-size: 0.88rem;
  color: var(--minimal-text-primary);
}
.status-info small {
  font-size: 0.76rem;
  color: var(--minimal-text-secondary);
}
.date-notice {
  margin: 0;
  color: var(--minimal-text-secondary);
  font-size: 0.8rem;
}
.date-result {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 6px;
}
.date-result label {
  margin: 0;
}
.calc-week-btn {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--minimal-border);
  border-radius: var(--minimal-radius-card);
  background: var(--minimal-bg-surface);
  color: var(--minimal-text-primary);
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.15s ease;
  text-align: center;
}
.calc-week-btn:hover {
  background: var(--minimal-border);
}
.calc-week-btn:active {
  transform: scale(0.98);
}
.calc-week-btn:disabled {
  opacity: 0.38;
  cursor: not-allowed;
  transform: none;
}
html[data-bg="night"] .calc-week-btn {
  background: rgba(30, 41, 59, 0.7);
  border-color: rgba(148, 163, 184, 0.25);
  color: #f1f5f9;
}
html[data-bg="night"] .calc-week-btn:hover {
  background: rgba(51, 65, 85, 0.85);
}
.semester-modal-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
}
.semester-btn-delete {
  margin: 0 !important;
  flex: none;
  white-space: nowrap;
}
.semester-btn-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  justify-content: flex-end;
}
.semester-btn-cancel,
.semester-btn-save {
  margin: 0 !important;
  white-space: nowrap;
}
@media (max-width: 480px) {
  .semester-modal-actions {
    gap: 8px;
  }
  .semester-btn-group {
    gap: 8px;
  }
  .semester-btn-delete,
  .semester-btn-cancel,
  .semester-btn-save {
    padding: 8px 10px !important;
    font-size: 0.8rem;
  }
}
</style>
