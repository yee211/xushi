<script setup>
import { computed, ref, watch } from 'vue';
import {
  courseKey,
  days,
  formatWeeks,
  timeRange,
} from '../utils/schedule.js';

const props = defineProps({
  open: { type: Boolean, default: false },
  schedule: { type: Object, default: null },
  week: { type: Number, default: 1 },
  colorMap: { type: Map, default: () => new Map() },
});

const emit = defineEmits([
  'close',
  'preview-course',
  'edit-course',
  'adjust-course',
  'add-course',
  'import-course',
]);

const searchQuery = ref('');
const selectedCourse = ref(null);

watch(() => props.open, (val) => {
  if (val) {
    searchQuery.value = '';
    selectedCourse.value = null;
  }
});

const courses = computed(() => props.schedule?.courses || []);

// 按课程名去重，每门课归总全部排课时段
const uniqueCourseGroups = computed(() => {
  const groupMap = new Map();
  courses.value.forEach((c) => {
    const key = courseKey(c.name);
    if (!groupMap.has(key)) {
      groupMap.set(key, { name: c.name, key, representative: c, slots: [] });
    }
    groupMap.get(key).slots.push(c);
  });
  return Array.from(groupMap.values());
});

const filteredGroups = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return uniqueCourseGroups.value;
  return uniqueCourseGroups.value.filter(g => g.name.toLowerCase().includes(q));
});

// 从前端整体 colorMap 获取统一的课程主题色
function getCourseHex(courseName) {
  return props.colorMap?.get(courseKey(courseName)) || '#637D91';
}

function toggleDetail(group) {
  selectedCourse.value = selectedCourse.value?.key === group.key ? null : group;
}

function openPreview(course) {
  emit('preview-course', course);
}

function openEdit(event, course) {
  event.stopPropagation();
  emit('edit-course', course);
}

function openAdjust(event, course) {
  event.stopPropagation();
  emit('adjust-course', course);
}

function isActiveThisWeek(slot) {
  return Array.isArray(slot.weeks) && slot.weeks.includes(props.week);
}

function slotTimeDesc(slot) {
  const start = slot.start_section ?? 1;
  const end = slot.end_section ?? start;
  const day = days[slot.weekday - 1] || '周?';
  const t = timeRange(slot);
  return `${day} 第${start}-${end}节${t ? ' ' + t : ''}`;
}
</script>

<template>
  <div v-if="open" class="backdrop nested-modal-backdrop" @click.self="emit('close')">
    <section class="modal course-center-modal" role="dialog" aria-modal="true" aria-labelledby="cc-title">

      <!-- ── 顶部栏 ── -->
      <div class="cc-head">
        <button type="button" class="back-btn" aria-label="关闭" @click="emit('close')">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M19 12H5M12 5l-7 7 7 7"/>
          </svg>
        </button>
        <h2 id="cc-title" class="cc-title">课程管理</h2>
        <button type="button" class="import-btn" @click="emit('import-course'); emit('close')">
          导入
        </button>
      </div>

      <!-- ── 信息统计 ── -->
      <div class="cc-meta-row">
        <span class="cc-hint">轻触卡片查看时段详情</span>
        <span class="cc-count">共 <strong>{{ uniqueCourseGroups.length }}</strong> 门课程</span>
      </div>

      <!-- ── 搜索框（课程数量较多时展开）── -->
      <div v-if="courses.length >= 6" class="cc-search-wrap">
        <svg class="cc-search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"/>
          <line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input v-model="searchQuery" type="text" placeholder="搜索课程名称..." class="cc-search-input" />
        <button v-if="searchQuery" type="button" class="cc-clear-btn" @click="searchQuery = ''">×</button>
      </div>

      <!-- ── 滚动卡片区域 ── -->
      <div class="cc-scroll">
        <!-- 空状态 -->
        <div v-if="!courses.length" class="cc-empty">
          <div class="cc-empty-icon">📋</div>
          <p class="cc-empty-title">暂无导入课程</p>
          <p class="cc-empty-sub">支持 Excel 文件导入与教务系统在线同步</p>
          <div class="cc-empty-actions">
            <button type="button" class="btn-dark" @click="emit('import-course'); emit('close')">导入课表</button>
            <button type="button" class="btn-ghost" @click="emit('add-course'); emit('close')">手动添加</button>
          </div>
        </div>

        <div v-else-if="!filteredGroups.length" class="cc-empty">
          <div class="cc-empty-icon">🔍</div>
          <p class="cc-empty-title">未找到相关课程</p>
          <button type="button" class="btn-ghost" @click="searchQuery = ''">清除搜索</button>
        </div>

        <template v-else>
          <!-- 课程卡片双列网格 -->
          <div class="course-grid">
            <button
              v-for="group in filteredGroups"
              :key="group.key"
              type="button"
              class="course-tile"
              :class="{ 'is-active': selectedCourse?.key === group.key }"
              :style="{ '--course': getCourseHex(group.name) }"
              @click="toggleDetail(group)"
            >
              <span class="tile-name">{{ group.name }}</span>
              <span class="tile-slots">{{ group.slots.length }} 个上课时段</span>
            </button>
          </div>

          <!-- 选中课程详情折叠面板 -->
          <transition name="detail-slide">
            <div v-if="selectedCourse" class="course-detail-panel" :style="{ '--course': getCourseHex(selectedCourse.name) }">
              <div class="detail-panel-head">
                <div class="detail-head-left">
                  <h3 class="detail-course-name">{{ selectedCourse.name }}</h3>
                </div>
                <div class="detail-head-actions">
                  <button type="button" class="detail-action-btn"
                          @click="openEdit($event, selectedCourse.representative)">编辑</button>
                  <button type="button" class="detail-action-btn detail-action-preview"
                          @click="openPreview(selectedCourse.representative)">详情 ›</button>
                </div>
              </div>

              <!-- 时段卡片列表 -->
              <div class="detail-slots-list">
                <div v-for="(slot, si) in selectedCourse.slots" :key="si" class="detail-slot-item">
                  <div class="slot-item-header">
                    <span class="slot-week-badge" :class="isActiveThisWeek(slot) ? 'badge-active' : 'badge-muted'">
                      {{ isActiveThisWeek(slot) ? `第${week}周上课` : '本周无课' }}
                    </span>
                    <span class="slot-time-text">{{ slotTimeDesc(slot) }}</span>
                    <button type="button" class="slot-adjust-btn" @click="openAdjust($event, slot)">调课</button>
                  </div>
                  <div class="slot-meta-row">
                    <span v-if="slot.room" class="slot-meta-chip">📍 {{ slot.room }}</span>
                    <span v-if="slot.teacher" class="slot-meta-chip">👤 {{ slot.teacher }}</span>
                    <span class="slot-meta-chip">📅 第 {{ formatWeeks(slot.weeks) }} 周</span>
                  </div>
                </div>
              </div>

              <button type="button" class="detail-close-btn" @click="selectedCourse = null">收起详情</button>
            </div>
          </transition>
        </template>
      </div>

    </section>
  </div>
</template>

<style scoped>
/* ── 模态尺寸与防溢出限制 ── */
.course-center-modal {
  width: min(440px, 92vw);
  max-height: min(76vh, 580px);
  margin: auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
  border-radius: 22px;
  background: #FFFFFF !important;
  border: 1px solid var(--minimal-border, #E5E7EB);
  box-shadow: 0 20px 48px -10px rgba(15, 23, 42, 0.16);
  box-sizing: border-box;
}

/* ── 顶部导航栏 ── */
.cc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 10px;
  border-bottom: 1px solid var(--minimal-border, #E5E7EB);
  flex-shrink: 0;
}

.back-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: none;
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-primary, #111827);
  cursor: pointer;
  transition: background 0.15s;
}

.back-btn:hover { background: #E5E7EB; }

.cc-title {
  font-size: 0.96rem;
  font-weight: 700;
  color: var(--minimal-text-primary, #111827);
  margin: 0;
  flex: 1;
  text-align: center;
}

.import-btn {
  padding: 3px 11px;
  border-radius: 9999px;
  border: 1px solid var(--minimal-border, #E5E7EB);
  background: transparent;
  color: var(--minimal-text-secondary, #8A8F99);
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.import-btn:hover {
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-primary, #111827);
}

/* ── 统计行 ── */
.cc-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px 4px;
  flex-shrink: 0;
}

.cc-hint, .cc-count {
  font-size: 0.74rem;
  color: var(--minimal-text-secondary, #8A8F99);
}

.cc-count strong {
  color: var(--minimal-text-primary, #111827);
  font-weight: 700;
}

/* ── 搜索框 ── */
.cc-search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  padding: 4px 14px 6px;
  flex-shrink: 0;
}

.cc-search-icon {
  position: absolute;
  left: 24px;
  color: var(--minimal-text-secondary, #8A8F99);
  pointer-events: none;
}

.cc-search-input {
  width: 100%;
  padding: 6px 26px 6px 28px;
  border-radius: 9999px;
  border: 1px solid var(--minimal-border, #E5E7EB);
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-primary, #111827);
  font-size: 0.8rem;
  outline: none;
  transition: all 0.2s;
}

.cc-search-input:focus {
  background: #fff;
  border-color: #0f172a;
}

.cc-clear-btn {
  position: absolute;
  right: 22px;
  background: transparent;
  border: none;
  color: var(--minimal-text-secondary, #8A8F99);
  font-size: 1rem;
  cursor: pointer;
  padding: 2px 4px;
  line-height: 1;
}

/* ── 滚动内容区域 ── */
.cc-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 6px 12px 14px;
  -webkit-overflow-scrolling: touch;
}

/* ── 双列课程网格 ── */
.course-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

/* ── 课程磁贴（严格适配前端整体课程配色与边框样式）── */
.course-tile {
  background: color-mix(in srgb, var(--course) 14%, #FFFFFF 86%);
  border: 1px solid color-mix(in srgb, var(--course) 25%, rgba(0, 0, 0, 0.06));
  border-left: 4px solid var(--course);
  border-radius: 14px;
  padding: 12px 10px 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 4px;
  min-height: 64px;
  text-align: left;
  transition: all 0.16s ease;
  box-sizing: border-box;
}

.course-tile:hover {
  transform: translateY(-1.5px);
  box-shadow: 0 4px 14px color-mix(in srgb, var(--course) 18%, rgba(0, 0, 0, 0.05));
}

.course-tile:active { transform: scale(0.97); }

.course-tile.is-active {
  box-shadow: 0 0 0 2px var(--course), 0 4px 12px rgba(0, 0, 0, 0.08);
}

.tile-name {
  font-size: 0.82rem;
  font-weight: 700;
  color: #111827;
  line-height: 1.35;
  word-break: break-word;
}

.tile-slots {
  font-size: 0.66rem;
  color: color-mix(in srgb, var(--course) 75%, #475569 25%);
  font-weight: 600;
}

/* ── 展开详情面板 ── */
.course-detail-panel {
  margin-top: 10px;
  border-radius: 16px;
  background: #FFFFFF;
  border: 1px solid var(--minimal-border, #E5E7EB);
  border-left: 4px solid var(--course);
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.detail-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--course) 10%, #FFFFFF 90%);
  border-bottom: 1px solid var(--minimal-border, #E5E7EB);
  gap: 8px;
}

.detail-course-name {
  font-size: 0.88rem;
  font-weight: 700;
  color: var(--minimal-text-primary, #111827);
  margin: 0;
  line-height: 1.35;
}

.detail-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.detail-action-btn {
  padding: 3px 9px;
  border-radius: 9999px;
  border: 1px solid var(--minimal-border, #E5E7EB);
  background: #FFFFFF;
  color: var(--minimal-text-primary, #111827);
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.detail-action-btn:hover { background: #F3F4F6; }

.detail-action-preview {
  background: var(--course);
  color: #FFFFFF;
  border-color: var(--course);
}

.detail-action-preview:hover { opacity: 0.9; }

/* 时段列表 */
.detail-slots-list { padding: 0; }

.detail-slot-item {
  padding: 9px 12px;
  border-bottom: 1px solid var(--minimal-border, #E5E7EB);
}

.detail-slot-item:last-child { border-bottom: none; }

.slot-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.slot-week-badge {
  font-size: 0.65rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 9999px;
  flex-shrink: 0;
}

.badge-active {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.badge-muted {
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-secondary, #8A8F99);
}

.slot-time-text {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--minimal-text-primary, #111827);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.slot-adjust-btn {
  padding: 2px 8px;
  border-radius: 9999px;
  border: 1px solid var(--minimal-border, #E5E7EB);
  background: #FFFFFF;
  color: var(--minimal-text-secondary, #8A8F99);
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
}

.slot-adjust-btn:hover {
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-primary, #111827);
}

.slot-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.slot-meta-chip {
  font-size: 0.68rem;
  color: var(--minimal-text-secondary, #8A8F99);
  background: var(--minimal-bg-surface, #F3F4F6);
  padding: 1px 6px;
  border-radius: 9999px;
}

/* 收起按钮 */
.detail-close-btn {
  width: 100%;
  padding: 8px;
  border: none;
  border-top: 1px solid var(--minimal-border, #E5E7EB);
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-secondary, #8A8F99);
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.detail-close-btn:hover {
  background: #E5E7EB;
  color: var(--minimal-text-primary, #111827);
}

/* ── 展开动画 ── */
.detail-slide-enter-active,
.detail-slide-leave-active {
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

.detail-slide-enter-from,
.detail-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
  max-height: 0;
}

.detail-slide-enter-to,
.detail-slide-leave-from {
  opacity: 1;
  transform: translateY(0);
  max-height: 500px;
}

/* ── 空状态 ── */
.cc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 30px 14px;
  text-align: center;
}

.cc-empty-icon { font-size: 2rem; }

.cc-empty-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--minimal-text-primary, #111827);
  margin: 3px 0 0;
}

.cc-empty-sub {
  font-size: 0.78rem;
  color: var(--minimal-text-secondary, #8A8F99);
  margin: 0 0 6px;
}

.cc-empty-actions { display: flex; gap: 8px; margin-top: 4px; }

.btn-dark {
  padding: 7px 16px;
  border-radius: 9999px;
  background: #0f172a;
  color: #fff;
  border: none;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-ghost {
  padding: 7px 16px;
  border-radius: 9999px;
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-primary, #111827);
  border: 1px solid var(--minimal-border, #E5E7EB);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}
</style>
