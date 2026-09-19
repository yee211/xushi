<script setup>
defineProps({
  open: { type: Boolean, default: true },
  authMode: { type: String, default: 'login' },
  authForm: { type: Object, required: true },
  authError: { type: String, default: '' },
  authLoading: { type: Boolean, default: false },
  appVersion: { type: String, default: '2.1.3' },
  isNative: { type: Boolean, default: false },
});

const emit = defineEmits([
  'submit',
  'update:authMode',
  'clear-error',
  'check-update',
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
