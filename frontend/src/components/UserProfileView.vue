<script setup>
import { computed, onMounted, ref } from 'vue';
import { api } from '../api';
import ConfirmModal from './ConfirmModal.vue';

const props = defineProps({
  user: { type: Object, default: null },
  schedule: { type: Object, default: null },
  customBg: { type: String, default: 'default' },
  appVersion: { type: String, default: '2.2.8' },
  isNative: { type: Boolean, default: false },
});

const BG_LABELS = {
  default: '极简纯白', cream: '温润米白', stone: '中性暖灰', paper: '轻古书页',
  lavender: '淡紫雅韵', sky: '澄澈晴空', mint: '清新薄荷', peach: '柔暖杏桃', rose: '山茶微粉', slate: '静谧青灰',
};

const customBgLabel = computed(() => BG_LABELS[props.customBg] || '默认');

const emit = defineEmits([
  'open-bg-picker',
  'check-update',
  'open-feedback',
  'logout',
  'notify',
]);

// ---------- 微信小程序绑定（账号互通） ----------
const linkStatus = ref(null);
const linkCode = ref('');
const linkExpiresLabel = ref('');
const linkBusy = ref(false);
const unbindOpen = ref(false);

onMounted(refreshLinkStatus);

async function refreshLinkStatus() {
  try {
    linkStatus.value = await api('/api/account/link');
  } catch {
    linkStatus.value = null;
  }
}

const linkBadge = computed(() => {
  if (!linkStatus.value) return '状态未知';
  return linkStatus.value.openid_bound ? '已绑定' : '未绑定';
});

async function onLinkAction() {
  if (linkStatus.value?.openid_bound) {
    unbindOpen.value = true;
    return;
  }
  linkBusy.value = true;
  try {
    const result = await api('/api/account/link/code', { method: 'POST' });
    linkCode.value = result.code;
    const expires = new Date(result.expires_at);
    linkExpiresLabel.value = Number.isNaN(expires.getTime()) ? '' :
      `${String(expires.getHours()).padStart(2, '0')}:${String(expires.getMinutes()).padStart(2, '0')}`;
  } catch (error) {
    emit('notify', error.message);
  } finally {
    linkBusy.value = false;
  }
}

async function unbindWechat() {
  unbindOpen.value = false;
  linkBusy.value = true;
  try {
    await api('/api/account/link', { method: 'DELETE' });
    linkCode.value = '';
    emit('notify', '已解除微信绑定');
  } catch (error) {
    emit('notify', error.message);
  } finally {
    linkBusy.value = false;
    refreshLinkStatus();
  }
}
</script>

<template>
  <div class="profile-page-view">
    <!-- 页面标题 -->
    <div class="profile-page-header">
      <h2>个人中心</h2>
      <p>账号信息与偏好设置</p>
    </div>

    <!-- 用户信息名片 -->
    <div class="profile-card minimal-card">
      <div class="profile-avatar">
        {{ user?.username?.slice(0, 1)?.toUpperCase() || 'U' }}
      </div>
      <div class="profile-info">
        <b class="profile-username">{{ user?.username || '未登录用户' }}</b>
        <small class="profile-email">{{ user?.email || '暂无绑定邮箱' }}</small>
      </div>
    </div>

    <!-- 偏好设置分组 -->
    <div class="profile-section">
      <span class="profile-section-label">外观</span>
      <div class="profile-actions-list">
        <!-- 自定义背景 -->
        <button
          type="button"
          class="profile-action-item minimal-card"
          @click="emit('open-bg-picker')"
        >
          <span class="action-icon">🎨</span>
          <span class="action-label">自定义背景</span>
          <span class="action-state-badge">{{ customBgLabel }}</span>
          <span class="action-arrow">›</span>
        </button>
      </div>
    </div>

    <!-- 账号互通分组 -->
    <div class="profile-section">
      <span class="profile-section-label">账号互通</span>
      <div class="profile-actions-list">
        <button
          type="button"
          class="profile-action-item minimal-card"
          :disabled="linkBusy"
          @click="onLinkAction"
        >
          <span class="action-icon">🔗</span>
          <span class="action-label">微信小程序</span>
          <span class="action-state-badge">{{ linkBadge }}</span>
          <span class="action-arrow">›</span>
        </button>
        <div v-if="linkCode" class="link-code-panel minimal-card">
          <b class="link-code">{{ linkCode }}</b>
          <small class="link-code-tip">
            在微信小程序「课表助手」页输入此码，绑定后小程序与 App 共用同一份课表<template v-if="linkExpiresLabel">，{{ linkExpiresLabel }} 前有效</template>
          </small>
        </div>
      </div>
    </div>

    <!-- 数据与账号分组 -->
    <div class="profile-section">
      <span class="profile-section-label">其他</span>
      <div class="profile-actions-list">
        <!-- 检查更新 / 下载 App -->
        <button
          v-if="isNative"
          type="button"
          class="profile-action-item minimal-card"
          @click="emit('check-update')"
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
        >
          <span class="action-icon">📱</span>
          <span class="action-label">下载安卓 App (APK)</span>
          <span class="action-arrow">›</span>
        </a>

        <!-- 反馈建议 -->
        <button
          type="button"
          class="profile-action-item minimal-card"
          @click="emit('open-feedback')"
        >
          <span class="action-icon">💬</span>
          <span class="action-label">问题与反馈</span>
          <span class="action-arrow">›</span>
        </button>
      </div>
    </div>

    <!-- 退出登录 -->
    <div class="profile-footer">
      <button
        type="button"
        class="profile-logout-btn"
        @click="emit('logout')"
      >
        退出登录
      </button>
    </div>

    <ConfirmModal
      :open="unbindOpen"
      title="解除微信绑定"
      message="解除后，微信小程序将恢复为独立账号，需要重新输入绑定码才能再次同步课表。"
      confirm-text="解除绑定"
      danger
      @confirm="unbindWechat"
      @cancel="unbindOpen = false"
    />
  </div>
</template>




<style scoped>
.profile-section {
  margin-bottom: 6px;
}

.profile-section-label {
  display: block;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--minimal-text-secondary);
  padding: 0 4px;
  margin-bottom: 8px;
}

.link-code-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  text-align: center;
}

.link-code {
  font-size: 1.5rem;
  letter-spacing: 0.45em;
  text-indent: 0.45em;
  font-weight: 700;
  color: var(--minimal-text, #1c1e21);
}

.link-code-tip {
  font-size: 0.78rem;
  line-height: 1.5;
  color: var(--minimal-text-secondary);
}
</style>
