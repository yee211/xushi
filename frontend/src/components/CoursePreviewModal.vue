<script setup>
import { computed } from 'vue';
import {
  courseKey,
  days,
  formatWeeks,
  timeRange,
} from '../utils/schedule.js';

const props = defineProps({
  open: { type: Boolean, default: false },
  course: { type: Object, default: null },
  colorMap: { type: Map, default: () => new Map() },
  records: { type: Array, default: () => [] },
});

const emit = defineEmits(['close', 'edit', 'adjust', 'restore', 'revoke', 'delete', 'remove-adjustment']);

const courseHexColor = computed(() => {
  if (!props.course) return '#5B8DEF';
  return props.colorMap.get(courseKey(props.course.name)) || '#5B8DEF';
});

function formatPlace(weekday, start, end, room) {
  if (!weekday) return '未设置';
  return `${days[weekday - 1] || '周?'} 第${start}-${end}节${room ? ` · ${room}` : ''}`;
}

function formatTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return isoStr;
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function getRecordDiffs(rec) {
  if (!Array.isArray(rec.details) || !rec.details.length) return [];
  const diffs = [];
  for (const item of rec.details) {
    if (item.label && (item.old !== undefined || item.new !== undefined)) {
      diffs.push({
        label: item.label,
        old: item.old,
        new: item.new,
      });
    } else if (item.old_weekday || item.new_weekday) {
      diffs.push({
        label: '上课时间',
        old: formatPlace(item.old_weekday, item.old_start_section, item.old_end_section),
        new: formatPlace(item.new_weekday, item.new_start_section, item.new_end_section),
      });
      if (item.old_room !== item.new_room) {
        diffs.push({
          label: '教室地点',
          old: item.old_room || '未设置',
          new: item.new_room || '未设置',
        });
      }
    }
  }
  return diffs;
}

function canRevokeRecord(rec) {
  if (rec.can_revoke) return true;
  if (rec.course_id && Array.isArray(rec.details) && rec.details.length > 0) {
    return true;
  }
  return false;
}

function handleRevoke(rec) {
  emit('restore', rec);
}
</script>

<template>
  <div v-if="open" class="backdrop nested-modal-backdrop" @click.self="emit('close')">
    <section class="modal preview-modal">
      <div class="modal-head">
        <div>
          <p>课程详情</p>
          <h2>{{ course?.name }}</h2>
        </div>
        <button type="button" class="icon" @click="emit('close')">×</button>
      </div>

      <div class="preview-details">
        <div><span>教师</span><b>{{ course?.teacher || '未填写' }}</b></div>
        <div><span>教室</span><b>{{ course?.room || '未填写' }}</b></div>
        <div>
          <span>上课时间</span>
          <b>{{ days[(course?.weekday || 1) - 1] }} · {{ timeRange(course || {}) }}</b>
        </div>
        <div><span>上课周次</span><b>{{ formatWeeks(course?.weeks) || '每周' }}</b></div>
        <div>
          <span>课程颜色</span>
          <b class="color-preview">
            <i :style="{ background: courseHexColor }"></i>
            {{ courseHexColor }}
          </b>
        </div>
      </div>

      <!-- 本课程修改记录 -->
      <div v-if="records?.length" class="course-history-section">
        <div class="history-section-head">
          <div class="history-section-title">
            <b>修改记录</b>
            <span class="history-count">{{ records.length }}</span>
          </div>
          <small class="history-hint">向下滑动可查看全部</small>
        </div>

        <div class="course-history-list">
          <article
            v-for="rec in records"
            :key="rec.id"
            class="course-history-card"
            :class="`type-${rec.action_type}`"
          >
            <div class="history-card-head">
              <span class="badge-tag" :class="`tag-${rec.action_type}`">
                {{ rec.action_type === 'drag_move' ? '位置移动' : rec.action_type === 'manual_edit' ? '主动编辑' : '调课通知' }}
              </span>
              <span class="change-log-time">{{ formatTime(rec.created_at) }}</span>
            </div>

            <div class="history-card-body">
              <div class="change-log-desc">{{ rec.description }}</div>

              <!-- Diff Chips -->
              <div v-if="getRecordDiffs(rec).length" class="edit-diff-list">
                <span v-for="(diff, di) in getRecordDiffs(rec)" :key="di" class="diff-tag">
                  {{ diff.label }}: {{ diff.old }} → {{ diff.new }}
                </span>
              </div>

              <!-- Dual Actions: 撤销修改 & 删除记录 -->
              <div class="history-card-actions">
                <button
                  v-if="canRevokeRecord(rec)"
                  type="button"
                  class="revoke-action-btn"
                  title="回滚到该次修改发生前的状态"
                  @click.stop="handleRevoke(rec)"
                >
                  撤销修改
                </button>
                <button
                  type="button"
                  class="delete-record-btn"
                  title="删除此条记录"
                  @click.stop="emit('delete', rec)"
                >
                  删除记录
                </button>
              </div>
            </div>
          </article>
        </div>
      </div>

      <div class="modal-actions">
        <button
          v-if="course?.adjusted_week"
          class="danger-outline uiverse-button"
          type="button"
          title="取消当前周的调课，恢复至原课表排课"
          @click="emit('remove-adjustment', course)"
        >
          取消调课
        </button>
        <span></span>
        <button class="uiverse-button" type="button" @click="emit('close')">关闭</button>
        <button class="uiverse-button" type="button" @click="emit('adjust', course)">
          {{ course?.adjusted_week ? '修改调课' : '调课' }}
        </button>
        <button class="primary uiverse-button" type="button" @click="emit('edit', course)">编辑</button>
      </div>
    </section>
  </div>
</template>
