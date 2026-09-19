<script setup>
import { ref, watch, computed } from 'vue';
import { days } from '../utils/schedule.js';

const props = defineProps({
  open: { type: Boolean, default: false },
  records: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(['close', 'image', 'revoke', 'revoke-batch', 'restore', 'delete']);
const mode = ref('menu');
const imageInput = ref(null);
const expandedRecordId = ref(null);

watch(() => props.open, value => {
  if (value) {
    mode.value = 'menu';
    expandedRecordId.value = null;
  }
});

function chooseImage() {
  imageInput.value?.click();
}

// 进入记录列表时，默认折叠明细（与 wx 端保持一致，使界面整洁）
function showRecords() {
  mode.value = 'records';
  expandedRecordId.value = null;
}

function onImage(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (file) emit('image', file);
}

function formatTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return isoStr;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatSection(weekday, start, end) {
  if (!weekday) return '未设置';
  return `${days[weekday - 1] || '周?'} 第${start}-${end}节`;
}

// 每门课的改动聚成一个分组块：课程名 + 周次 + 时间/教室变更，块内自带撤销按钮
function getDetailGroups(rec) {
  const details = Array.isArray(rec.details) ? rec.details : [];
  const groups = [];
  let current = null;
  for (const item of details) {
    if (item.old_weekday || item.new_weekday) {
      const lines = [
        `${formatSection(item.old_weekday, item.old_start_section, item.old_end_section)} → ${formatSection(item.new_weekday, item.new_start_section, item.new_end_section)}`,
      ];
      if ((item.old_room || '') !== (item.new_room || '')) {
        lines.push(`教室：${item.old_room || '未设置'} → ${item.new_room || '未设置'}`);
      }
      current = {
        courseName: item.course_name || '',
        week: item.week ?? null,
        lines,
        canRevoke: !!item.can_revoke,
        item,
      };
      groups.push(current);
    } else if (item.label) {
      if (current && item.label.includes('教室') && current.lines.some(l => l.startsWith('教室'))) {
        continue;
      }
      const line = `${item.label}：${item.old ?? '—'} → ${item.new ?? '—'}`;
      if (current) {
        current.lines.push(line);
      } else {
        current = { courseName: '', week: null, lines: [line], canRevoke: false, item };
        groups.push(current);
      }
    }
  }
  return groups;
}

const decoratedRecords = computed(() => {
  return props.records
    .filter(r => r.action_type === 'batch_import')
    .map(rec => ({
      ...rec,
      groups: getDetailGroups(rec),
      collapsible: (rec.details?.length || 0) > 1 || rec.action_type === 'batch_import',
    }));
});

function isExpanded(rec) {
  return !rec.collapsible || expandedRecordId.value === rec.id;
}

function toggleExpand(rec) {
  expandedRecordId.value = expandedRecordId.value === rec.id ? null : rec.id;
}
</script>

<template>
  <div v-if="open" class="backdrop" @click.self="!loading && emit('close')">
    <section class="modal adjustment-center-modal">
      <div class="modal-head">
        <div>
          <p>课程变更</p>
          <h2>{{ mode === 'menu' ? '调课中心' : '调课通知记录' }}</h2>
        </div>
        <button type="button" class="icon" :disabled="loading" @click="emit('close')">×</button>
      </div>

      <!-- Menu Mode -->
      <div v-if="mode === 'menu'" class="adjustment-entry-grid">
        <button type="button" class="adjustment-entry" @click="chooseImage">
          <span>▣</span><b>课程图片识别调课</b><small>上传学校调课通知截图自动识别</small>
        </button>
        <button type="button" class="adjustment-entry" @click="showRecords">
          <span>≡</span><b>调课通知记录</b><small>查看学校调课通知与批量调整详情</small>
        </button>
        <input ref="imageInput" class="sr-only" type="file" accept="image/jpeg,image/png,image/webp" @change="onImage">
      </div>

      <!-- Records Mode -->
      <div v-else class="adjustment-records-container">
        <div class="adjustment-records-list">
          <p v-if="loading" class="empty-records">正在读取记录…</p>
          <p v-else-if="!decoratedRecords.length" class="empty-records">暂无调课通知记录</p>
          <article
            v-for="rec in decoratedRecords"
            :key="rec.id"
            class="change-log-item"
            :class="`type-${rec.action_type}`"
          >
            <div class="change-log-head">
              <span class="badge-tag" :class="`tag-${rec.action_type}`">
                {{ rec.action_type === 'batch_import' ? '图片调课' : rec.action_type === 'drag_move' ? '位置移动' : '主动编辑' }}
              </span>
              <span class="change-log-time">{{ formatTime(rec.created_at) }}</span>
            </div>

            <div class="change-log-title">{{ rec.title }}</div>
            <div class="change-log-desc">{{ rec.description }}</div>

            <!-- 逐课程分组明细：每门课的修改集中在一块 -->
            <div v-if="isExpanded(rec) && rec.groups.length" class="record-detail-groups">
              <div v-for="(group, gi) in rec.groups" :key="gi" class="record-group-block">
                <div class="group-main">
                  <div v-if="group.courseName || group.week" class="group-head">
                    <span class="group-course">《{{ group.courseName }}》</span>
                    <span v-if="group.week" class="badge-week">第 {{ group.week }} 周</span>
                  </div>
                  <p v-for="(line, li) in group.lines" :key="li" class="group-line">{{ line }}</p>
                </div>
                <button
                  v-if="group.canRevoke"
                  type="button"
                  class="group-revoke-btn"
                  @click="emit('revoke', group.item)"
                >
                  撤销
                </button>
              </div>
            </div>

            <!-- Actions: 收起/展开详情 & 一键撤销 & 恢复修改 & 删除记录 -->
            <div class="change-log-actions">
              <button
                v-if="rec.collapsible"
                type="button"
                class="view-detail-btn"
                @click="toggleExpand(rec)"
              >
                {{ isExpanded(rec) ? '收起详情' : `查看详情 ${rec.details.length} 条` }}
              </button>
              <button
                v-if="(rec.details.length > 1 || rec.action_type === 'batch_import') && rec.can_revoke"
                type="button"
                class="revoke-action-btn"
                title="一键撤销本次调课的所有改动，恢复课表原状"
                @click="emit('revoke-batch', rec)"
              >
                一键撤销
              </button>
              <button
                v-if="!rec.can_revoke && rec.course_id"
                type="button"
                class="revoke-action-btn"
                @click="emit('restore', rec)"
              >
                恢复修改
              </button>
              <button
                type="button"
                class="delete-record-btn"
                @click="emit('delete', rec)"
              >
                删除记录
              </button>
            </div>
          </article>
        </div>

        <div class="modal-actions">
          <button type="button" class="uiverse-button" @click="mode = 'menu'">返回</button>
          <span></span>
          <button type="button" class="uiverse-button" @click="emit('close')">关闭</button>
        </div>
      </div>
    </section>
  </div>
</template>
