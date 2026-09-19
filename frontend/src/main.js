import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import './styles/accessibility.css'

createApp(App).mount('#app')

// 清理由旧版本注册的 PWA Service Worker，防止继续展示安装入口或旧缓存。
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations()
    .then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())))
    .catch(() => {});
}
if ('caches' in window) {
  caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key.startsWith('jianke-cache-')).map((key) => caches.delete(key))))
    .catch(() => {});
}
