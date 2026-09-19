<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { FEATURES } from '../utils/features.js';

const featureFlags = FEATURES;

const props = defineProps({
  activeTab: { type: String, default: 'schedule' },
  showAction: { type: Boolean, default: true },
  iconType: { type: String, default: 'grid' }, // 'grid' | 'plus' | 'more' | 'sliders'
});

const emit = defineEmits([
  'update:activeTab',
  'open-profile',
  'open-course-center',
  'add-course',
  'upload',
  'open-import',
  'open-adjustments',
  'delete-schedule',
]);

const menuOpen = ref(false);
const actionWrapRef = ref(null);

function handleTabClick(tab) {
  emit('update:activeTab', tab);
  if (tab === 'profile') {
    emit('open-profile');
  }
}

function toggleMenu() {
  menuOpen.value = !menuOpen.value;
}

function closeMenu() {
  menuOpen.value = false;
}

function handleAction(action) {
  closeMenu();
  if (action === 'course-center') {
    emit('open-course-center');
  } else if (action === 'add') {
    emit('add-course');
  } else if (action === 'adjust') {
    emit('open-adjustments');
  } else if (action === 'delete') {
    emit('delete-schedule');
  } else if (action === 'import') {
    emit('open-import');
  }
}

function handleFileChange(event) {
  closeMenu();
  emit('upload', event);
}

function handleDocClick(event) {
  if (actionWrapRef.value && !actionWrapRef.value.contains(event.target)) {
    closeMenu();
  }
}

function handleKeydown(event) {
  if (event.key === 'Escape' && menuOpen.value) {
    closeMenu();
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocClick);
  document.addEventListener('keydown', handleKeydown);
});

onUnmounted(() => {
  document.removeEventListener('click', handleDocClick);
  document.removeEventListener('keydown', handleKeydown);
});
</script>

<template>
  <div class="dock-wrap" aria-label="底部导航与操作">
    <!-- 极简双 Tab 导航 -->
    <nav class="dock" role="tablist">
      <button
        type="button"
        class="dock-item"
        :class="{ active: activeTab === 'schedule' }"
        role="tab"
        :aria-selected="activeTab === 'schedule'"
        aria-label="课表视图"
        @click="handleTabClick('schedule')"
      >
        <svg
          class="dock-icon"
          width="16" height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
          <line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8" y1="2" x2="8" y2="6"/>
          <line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
        <span>课表</span>
      </button>

      <button
        type="button"
        class="dock-item"
        :class="{ active: activeTab === 'profile' }"
        role="tab"
        :aria-selected="activeTab === 'profile'"
        aria-label="个人中心"
        @click="handleTabClick('profile')"
      >
        <svg
          class="dock-icon"
          width="16" height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
          <circle cx="12" cy="7" r="4"/>
        </svg>
        <span>我的</span>
      </button>
    </nav>

    <!-- 课表专属统一快捷操作入口 -->
    <div v-if="showAction" ref="actionWrapRef" class="dock-action-wrap">
      <!-- 极简操作弹层菜单 (添加课程 / 调课中心 / 删除课表) -->
      <Transition name="dock-menu">
        <div v-if="menuOpen" class="dock-action-menu" role="menu" aria-label="课表操作菜单">
          <!-- 0. 课表中心 (全部课程与学时) -->
          <button
            type="button"
            class="dock-menu-item"
            role="menuitem"
            @click="handleAction('course-center')"
          >
            <div class="menu-item-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
              </svg>
            </div>
            <div class="menu-item-content">
              <span class="menu-item-title">课表中心</span>
              <span class="menu-item-desc">查看本学期全部课程与学时</span>
            </div>
          </button>

          <!-- 1. 添加课程（功能开关隐藏，代码保留） -->
          <button
            v-if="featureFlags.addCourse"
            type="button"
            class="dock-menu-item"
            role="menuitem"
            @click="handleAction('add')"
          >
            <div class="menu-item-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
            </div>
            <div class="menu-item-content">
              <span class="menu-item-title">添加课程</span>
              <span class="menu-item-desc">新建单门或多周课程</span>
            </div>
          </button>

          <!-- 2. 导入课表 -->
          <button
            type="button"
            class="dock-menu-item"
            role="menuitem"
            @click="handleAction('import')"
          >
            <div class="menu-item-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </div>
            <div class="menu-item-content">
              <span class="menu-item-title">导入课表</span>
              <span class="menu-item-desc">Excel 文件或教务在线导入</span>
            </div>
          </button>

          <!-- 3. 调课中心（功能开关隐藏，代码保留） -->
          <button
            v-if="featureFlags.adjustmentCenter"
            type="button"
            class="dock-menu-item"
            role="menuitem"
            @click="handleAction('adjust')"
          >
            <div class="menu-item-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M16 3h5v5"/>
                <path d="M4 20L21 3"/>
                <path d="M21 16v5h-5"/>
                <path d="M15 15l6 6"/>
                <path d="M4 4l5 5"/>
              </svg>
            </div>
            <div class="menu-item-content">
              <span class="menu-item-title">调课中心</span>
              <span class="menu-item-desc">通知识别与单周微调</span>
            </div>
          </button>



          <div class="dock-menu-divider" role="separator"></div>

          <!-- 3. 删除课表 (危险警示态) -->
          <button
            type="button"
            class="dock-menu-item danger"
            role="menuitem"
            @click="handleAction('delete')"
          >
            <div class="menu-item-icon danger-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                <line x1="10" y1="11" x2="10" y2="17"/>
                <line x1="14" y1="11" x2="14" y2="17"/>
              </svg>
            </div>
            <div class="menu-item-content">
              <span class="menu-item-title">删除课表</span>
              <span class="menu-item-desc">删除当前学期及全部课程</span>
            </div>
          </button>
        </div>
      </Transition>

      <!-- 快捷操作按钮 (默认极简四宫格 Grid ⊞，展开顺滑变幻为关闭 ×) -->
      <button
        type="button"
        class="dock-action"
        :class="{ open: menuOpen }"
        aria-label="课表操作菜单"
        :aria-expanded="menuOpen"
        @click.stop="toggleMenu"
      >
        <!-- 闭合状态图标：四宫格功能矩阵 (Grid ⊞) -->
        <svg
          v-if="!menuOpen && iconType === 'grid'"
          class="dock-action-icon"
          width="20" height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect x="3" y="3" width="7" height="7" rx="1.5"/>
          <rect x="14" y="3" width="7" height="7" rx="1.5"/>
          <rect x="14" y="14" width="7" height="7" rx="1.5"/>
          <rect x="3" y="14" width="7" height="7" rx="1.5"/>
        </svg>

        <!-- 备选方案：经典加号图标 -->
        <svg
          v-else-if="!menuOpen && iconType === 'plus'"
          class="dock-action-icon"
          width="20" height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.4"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>

        <!-- 备选方案：三点更多图标 -->
        <svg
          v-else-if="!menuOpen && iconType === 'more'"
          class="dock-action-icon"
          width="20" height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.4"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="1.5"/>
          <circle cx="12" cy="5" r="1.5"/>
          <circle cx="12" cy="19" r="1.5"/>
        </svg>

        <!-- 展开状态图标：简洁关闭 (×) -->
        <svg
          v-else
          class="dock-action-icon close"
          width="20" height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.4"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.dock-wrap {
  position: fixed;
  left: 50%;
  bottom: calc(20px + var(--safe-area-bottom, 0px));
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  z-index: 50;
  pointer-events: auto;
}

.dock {
  display: flex;
  gap: 4px;
  padding: 6px;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: var(--minimal-radius-pill, 9999px);
  background: rgba(243, 244, 246, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
}

.dock-item {
  height: 40px;
  padding: 0 16px;
  border: 0;
  border-radius: var(--minimal-radius-pill, 9999px);
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #8a8f99;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.18s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.dock-item:active {
  transform: scale(0.94);
}

.dock-item.active {
  background: #ffffff;
  color: #111827;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.dock-icon {
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.18s ease;
  will-change: transform;
  flex-shrink: 0;
}

.dock-item.active .dock-icon {
  transform: scale(1.06);
}

/* 操作按钮容器 */
.dock-action-wrap {
  position: relative;
}

.dock-action {
  width: 48px;
  height: 48px;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: var(--minimal-radius-pill, 9999px);
  background: var(--minimal-bg-surface, #f3f4f6);
  color: #111827;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1),
              background-color 0.15s ease,
              color 0.15s ease,
              box-shadow 0.2s ease;
}

.dock-action:active {
  transform: scale(0.92);
}

.dock-action.open {
  background: #111827;
  color: #ffffff;
  box-shadow: 0 4px 16px rgba(17, 24, 39, 0.2);
}

.dock-action-icon {
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  will-change: transform;
}

.dock-action-icon.close {
  animation: close-spin 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes close-spin {
  from {
    transform: scale(0.7) rotate(-90deg);
    opacity: 0;
  }
  to {
    transform: scale(1) rotate(0);
    opacity: 1;
  }
}

/* 操作弹出菜单 */
.dock-action-menu {
  position: absolute;
  bottom: calc(100% + 12px);
  right: 0;
  width: 224px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 20px;
  padding: 8px;
  box-shadow: 0 16px 36px -4px rgba(0, 0, 0, 0.12), 0 4px 12px -2px rgba(0, 0, 0, 0.05);
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transform-origin: bottom right;
}

.dock-menu-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: 12px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background-color 0.15s ease, transform 0.1s ease;
}

.dock-menu-item:hover {
  background: #f3f4f6;
}

.dock-menu-item:active {
  transform: scale(0.98);
  background: #e5e7eb;
}

.menu-item-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #111827;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.menu-item-content {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.menu-item-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #111827;
  line-height: 1.25;
}

.menu-item-desc {
  font-size: 11px;
  color: #8a8f99;
  margin-top: 2px;
  white-space: nowrap;
}

.dock-menu-divider {
  height: 1px;
  background: #e5e7eb;
  margin: 4px 6px;
}

/* 危险删除样式 */
.dock-menu-item.danger .menu-item-icon {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.dock-menu-item.danger .menu-item-title {
  color: #ef4444;
}

.dock-menu-item.danger:hover {
  background: rgba(239, 68, 68, 0.08);
}

.dock-menu-item.danger:active {
  background: rgba(239, 68, 68, 0.14);
}

/* 菜单展开/收起过渡动效 */
.dock-menu-enter-active,
.dock-menu-leave-active {
  transition: opacity 0.18s cubic-bezier(0.16, 1, 0.3, 1), transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.dock-menu-enter-from,
.dock-menu-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.94);
}

/* ── 夜间模式适配 ────────────────────────────────────── */
html[data-bg="night"] .dock {
  background: rgba(30, 41, 59, 0.85);
  border-color: rgba(255, 255, 255, 0.08);
}

html[data-bg="night"] .dock-item {
  color: #94a3b8;
}

html[data-bg="night"] .dock-item.active {
  background: #0f172a;
  color: #f8fafc;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
}

html[data-bg="night"] .dock-action {
  background: #1e293b;
  color: #f8fafc;
  border-color: rgba(255, 255, 255, 0.08);
}

html[data-bg="night"] .dock-action.open {
  background: #f8fafc;
  color: #0f172a;
}

html[data-bg="night"] .dock-action-menu {
  background: #1e293b;
  border-color: #334155;
  box-shadow: 0 16px 36px -4px rgba(0, 0, 0, 0.45);
}

html[data-bg="night"] .dock-menu-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

html[data-bg="night"] .dock-menu-item:active {
  background: rgba(255, 255, 255, 0.10);
}

html[data-bg="night"] .menu-item-icon {
  background: #0f172a;
  color: #f8fafc;
}

html[data-bg="night"] .menu-item-title {
  color: #f8fafc;
}

html[data-bg="night"] .dock-menu-divider {
  background: #334155;
}

.hidden-file-input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}

.file-upload-item {
  cursor: pointer;
}
</style>
