<script setup>
defineProps({
  open: { type: Boolean, default: false },
  user: { type: Object, default: null },
  schedule: { type: Object, default: null },
  bgMode: { type: String, default: 'transparent' },
  appVersion: { type: String, default: '2.2.8' },
  isNative: { type: Boolean, default: false },
});

const emit = defineEmits([
  'close',
  'upload',
  'toggle-night-mode',
  'check-update',
  'open-feedback',
  'delete-schedule',
  'logout',
]);

function onUpload(event) {
  emit('upload', event);
  emit('close');
}
</script>

<template>
  <div v-if="open" class="backdrop profile-backdrop" @click.self="emit('close')">
    <section class="modal profile-modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div>
          <p>个人中心</p>
          <h2>我的账号与设置</h2>
        </div>
        <button type="button" class="icon" aria-label="关闭" @click="emit('close')">×</button>
      </div>

      <!-- 用户名片 -->
      <div class="profile-card minimal-card">
        <div class="profile-avatar">
          {{ user?.username?.slice(0, 1)?.toUpperCase() || 'U' }}
        </div>
        <div class="profile-info">
          <b class="profile-username">{{ user?.username || '未登录用户' }}</b>
          <small class="profile-email">{{ user?.email || '暂无绑定邮箱' }}</small>
        </div>
      </div>

      <!-- 操作列表 -->
      <div class="profile-actions-list">
        <!-- 切换深色/浅色模式 -->
        <button
          type="button"
          class="profile-action-item minimal-card"
          @click="emit('toggle-night-mode')"
        >
          <span class="action-icon">{{ bgMode === 'night' ? '☀️' : '🌙' }}</span>
          <span class="action-label">深浅色主题</span>
          <span class="action-state-badge">{{ bgMode === 'night' ? '深色模式' : '浅色模式' }}</span>
        </button>

        <!-- 导入课表 -->
        <label class="profile-action-item minimal-card file-upload-label">
          <input type="file" accept=".xlsx,.xlsm,.xls" class="hidden-file-input" @change="onUpload">
          <span class="action-icon">📥</span>
          <span class="action-label">导入课表 Excel</span>
          <span class="action-arrow">›</span>
        </label>

        <!-- 检查更新 / 下载 App -->
        <button
          v-if="isNative"
          type="button"
          class="profile-action-item minimal-card"
          @click="emit('check-update'); emit('close')"
        >
          <span class="action-icon">🔄</span>
          <span class="action-label">检查新版本</span>
          <span class="action-version-tag">v{{ appVersion }}</span>
        </button>
        <a
          v-else
          href="/downloads/%E5%BA%8F%E6%97%B6.apk"
          download="序时.apk"
          class="profile-action-item minimal-card link-item"
          @click="emit('close')"
        >
          <span class="action-icon">📱</span>
          <span class="action-label">下载安卓 App (APK)</span>
          <span class="action-arrow">›</span>
        </a>

        <!-- 反馈建议 -->
        <button
          type="button"
          class="profile-action-item minimal-card"
          @click="emit('open-feedback'); emit('close')"
        >
          <span class="action-icon">💬</span>
          <span class="action-label">问题与反馈</span>
          <span class="action-arrow">›</span>
        </button>

        <!-- 删除当前课表 (如果存在) -->
        <button
          v-if="schedule"
          type="button"
          class="profile-action-item minimal-card danger-item"
          @click="emit('delete-schedule'); emit('close')"
        >
          <span class="action-icon">🗑️</span>
          <span class="action-label">删除当前课表</span>
          <span class="action-arrow">›</span>
        </button>
      </div>

      <!-- 退出登录按钮 -->
      <div class="profile-footer">
        <button
          type="button"
          class="profile-logout-btn"
          @click="emit('logout'); emit('close')"
        >
          退出登录
        </button>
      </div>
    </section>
  </div>
</template>
