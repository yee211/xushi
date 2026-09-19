<script setup>
defineProps({
  open: { type: Boolean, default: false },
  updateInfo: { type: Object, default: () => ({}) },
  currentVersion: { type: String, default: '2.0.0' },
});

const emit = defineEmits(['close', 'ignore', 'confirm']);
</script>

<template>
  <div
    v-if="open"
    class="backdrop"
    @click.self="!updateInfo.forceUpdate && emit('close')"
  >
    <section class="modal update-modal">
      <div class="modal-head">
        <div>
          <div class="update-tag-row">
            <span class="update-tag">版本升级</span>
            <span class="version-badge">v{{ updateInfo.versionName }}</span>
          </div>
          <h2>{{ updateInfo.title || '发现新版本' }}</h2>
        </div>
        <button
          v-if="!updateInfo.forceUpdate"
          type="button"
          class="icon"
          title="关闭"
          @click="emit('close')"
        >
          ×
        </button>
      </div>

      <div class="update-body">
        <div class="version-compare">
          <div class="compare-box">
            <span class="compare-label">当前版本</span>
            <span class="compare-val current">v{{ currentVersion }}</span>
          </div>
          <div class="compare-arrow">➔</div>
          <div class="compare-box">
            <span class="compare-label">最新版本</span>
            <span class="compare-val latest">v{{ updateInfo.versionName }}</span>
          </div>
        </div>

        <div v-if="updateInfo.changelog && updateInfo.changelog.length" class="changelog-card">
          <h4 class="changelog-title">✨ 更新内容</h4>
          <ul class="changelog-list">
            <li v-for="(item, idx) in updateInfo.changelog" :key="idx">
              <span class="changelog-bullet">•</span>
              <span class="changelog-text">{{ item }}</span>
            </li>
          </ul>
        </div>

        <div class="update-tip">
          <span class="tip-icon">💡</span>
          <div class="tip-content">
            <p class="tip-text">点击后将调起手机浏览器高速下载，完成后点击安装即可覆盖升级（现有课表数据完整保留）。</p>
            <p v-if="updateInfo.backupDownloadUrl" class="backup-tip">
              如遇网络波动，可尝试：<button type="button" class="link-btn" @click="emit('confirm', updateInfo.backupDownloadUrl)">切换服务器直连通道</button>
            </p>
          </div>
        </div>

        <div v-if="updateInfo.forceUpdate" class="force-update-notice">
          ⚠️ 当前版本已停用，需升级后方可继续正常使用。
        </div>
      </div>

      <div class="modal-actions">
        <button
          v-if="!updateInfo.forceUpdate"
          type="button"
          class="btn-secondary"
          @click="emit('ignore')"
        >
          稍后提醒
        </button>
        <span></span>
        <button
          type="button"
          class="primary"
          @click="emit('confirm', updateInfo.downloadUrl)"
        >
          🚀 立即更新 (CDN 极速下载)
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.update-modal {
  max-width: 460px;
}

.update-tag-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.update-tag {
  font-size: 0.75rem;
  font-weight: 600;
  color: #2563eb;
  background: rgba(37, 99, 235, 0.1);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.2);
}

.version-badge {
  font-size: 0.78rem;
  font-weight: 700;
  color: #0284c7;
  background: rgba(14, 165, 233, 0.12);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(14, 165, 233, 0.25);
}

.update-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin: 12px 0 20px;
}

.version-compare {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 16px;
  padding: 12px 18px;
  backdrop-filter: blur(10px);
}

.compare-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.compare-label {
  font-size: 0.72rem;
  color: #64748b;
}

.compare-val {
  font-size: 1.05rem;
  font-weight: 700;
}

.compare-val.current {
  color: #64748b;
}

.compare-val.latest {
  color: #0284c7;
}

.compare-arrow {
  color: #94a3b8;
  font-size: 1.1rem;
}

.changelog-card {
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.85);
  border-radius: 18px;
  padding: 14px 16px;
}

.changelog-title {
  margin: 0 0 10px;
  font-size: 0.88rem;
  font-weight: 600;
  color: #1e293b;
}

.changelog-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.changelog-list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 0.84rem;
  line-height: 1.45;
  color: #334155;
}

.changelog-bullet {
  color: #3b82f6;
  font-weight: bold;
}

.update-tip {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: rgba(240, 249, 255, 0.75);
  border: 1px solid rgba(186, 230, 253, 0.6);
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 0.78rem;
  color: #0369a1;
  line-height: 1.4;
}

.tip-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tip-content p {
  margin: 0;
}

.backup-tip {
  color: #64748b;
  font-size: 0.75rem;
}

.link-btn {
  background: none;
  border: none;
  padding: 0;
  color: #0284c7;
  font-size: 0.75rem;
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
}

.tip-icon {
  font-size: 0.95rem;
}

.force-update-notice {
  font-size: 0.8rem;
  color: #dc2626;
  background: rgba(254, 242, 242, 0.8);
  border: 1px solid rgba(254, 202, 202, 0.7);
  padding: 8px 12px;
  border-radius: 10px;
  text-align: center;
  font-weight: 500;
}

.btn-secondary {
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(255, 255, 255, 0.7);
  color: #475569;
  border-radius: 999px;
  padding: 9px 18px;
  font-size: 0.88rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.95);
  color: #1e293b;
}
</style>
