<script setup>
defineProps({
  open: { type: Boolean, default: true },
  authMode: { type: String, default: 'login' },
  authForm: { type: Object, required: true },
  authError: { type: String, default: '' },
  authLoading: { type: Boolean, default: false },
  appVersion: { type: String, default: '2.1.3' },
  isNative: { type: Boolean, default: false },
  savedAccounts: { type: Array, default: () => [] },
  rememberAccount: { type: Boolean, default: true },
});

const emit = defineEmits([
  'submit',
  'update:authMode',
  'clear-error',
  'check-update',
  'saved-login',
  'remove-account',
  'update:rememberAccount',
  'clear-accounts',
]);

function switchMode(mode) {
  emit('update:authMode', mode);
  emit('clear-error');
}
</script>

<template>
  <div v-if="open" class="auth-backdrop">
    <section class="modal auth-card">
      <div class="auth-brand">
        <span class="brand-dot"></span>
        <strong>序时</strong>
      </div>
      <div class="auth-head">
        <h2>{{ authMode === 'register' ? '创建账号' : '欢迎回来' }}</h2>
        <p>{{ authMode === 'register' ? '注册后即可拥有属于你的课表空间' : '登录后继续管理你的课表' }}</p>
      </div>
      <div v-if="isNative && authMode === 'login' && savedAccounts.length" class="saved-accounts">
        <p>已保存账号 · 点击登录</p>
        <div v-for="account in savedAccounts" :key="account.email" class="saved-account-row">
          <button type="button" class="saved-account-login" :disabled="authLoading" @click="emit('saved-login', account)">
            <strong>{{ account.username || account.email }}</strong><small>{{ account.email }}</small>
          </button>
          <button type="button" class="saved-account-remove" :disabled="authLoading" :aria-label="`移除已保存账号 ${account.email}`" @click="emit('remove-account', account)">移除</button>
        </div>
      </div>
      <form class="auth-form" @submit.prevent="emit('submit')">
        <label>
          邮箱
          <input
            v-model="authForm.email"
            type="email"
            maxlength="254"
            autocomplete="email"
            placeholder="用于登录的邮箱"
            required
          >
        </label>
        <label v-if="authMode === 'register'">
          用户名
          <input
            v-model="authForm.username"
            maxlength="40"
            autocomplete="nickname"
            required
          >
        </label>
        <label>
          密码
          <input
            v-model="authForm.password"
            type="password"
            maxlength="72"
            :autocomplete="authMode === 'register' ? 'new-password' : 'current-password'"
            placeholder="至少 6 位密码"
            required
          >
        </label>
        <label v-if="isNative" class="remember-account">
          <input type="checkbox" :checked="rememberAccount" @change="emit('update:rememberAccount', $event.target.checked)">
          保存账号，下次点击即可登录
        </label>
        <p v-if="authError" class="auth-error">{{ authError }}</p>
        <button class="uiverse-button auth-submit" type="submit" :disabled="authLoading">
          {{ authLoading ? '请稍候…' : (authMode === 'register' ? '注册并登录' : '登录') }}
        </button>
      </form>
      <p class="auth-switch">
        <template v-if="authMode === 'register'">
          已有账号？<button type="button" @click="switchMode('login')">去登录</button>
        </template>
        <template v-else>
          还没有账号？<button type="button" @click="switchMode('register')">立即注册</button>
        </template>
      </p>
      <button v-if="isNative" type="button" class="auth-check-btn" :disabled="authLoading" @click="emit('clear-accounts')">清空已保存账号</button>
      <div class="auth-version-bar">
        <span>序时 {{ isNative ? `App v${appVersion}` : '网页版' }}</span>
        <template v-if="isNative">
          <span class="auth-version-sep">·</span>
          <button type="button" class="auth-check-btn" @click="emit('check-update')">检查更新</button>
        </template>
        <template v-else>
          <span class="auth-version-sep">·</span>
          <a
            href="/downloads/%E5%BA%8F%E6%97%B6.apk"
            download="序时.apk"
            class="auth-check-btn"
            title="下载 Android 安装包"
          >
            📱 下载安卓 App
          </a>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.auth-card{max-height:calc(100dvh - 36px);overflow-y:auto}.saved-accounts{max-height:230px;overflow-y:auto}
.saved-accounts{margin-bottom:16px}.saved-accounts>p{font-size:13px;color:#64748b}.saved-account-row{display:flex;align-items:center;border:1px solid #dce3ea;border-radius:14px;margin-top:8px;overflow:hidden}.saved-account-login{flex:1;min-width:0;text-align:left;padding:12px;background:transparent;border:0;cursor:pointer}.saved-account-login strong,.saved-account-login small{display:block;overflow-wrap:anywhere}.saved-account-login small{margin-top:3px;color:#64748b}.saved-account-remove{border:0;background:transparent;padding:12px;color:#64748b;cursor:pointer}.auth-form .remember-account{display:flex;align-items:center;gap:8px;font-size:13px}.auth-form .remember-account input{width:16px;height:16px;padding:0;flex-shrink:0}
.auth-version-bar {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 0.78rem;
  color: #94a3b8;
}
.auth-version-sep {
  opacity: 0.5;
}
.auth-check-btn {
  background: none;
  border: none;
  color: #0284c7;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: opacity 0.2s;
}
.auth-check-btn:hover {
  opacity: 0.8;
  text-decoration: underline;
}
</style>
