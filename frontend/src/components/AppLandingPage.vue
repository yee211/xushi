<script setup>
import { computed, onMounted, ref } from 'vue';
import { appApi } from '../api/index.js';
import { CURRENT_VERSION_CODE, CURRENT_VERSION_NAME } from '../utils/version.js';

// 兜底版本信息
const defaultVersion = {
  versionCode: CURRENT_VERSION_CODE,
  versionName: CURRENT_VERSION_NAME,
  title: `发现新版本 v${CURRENT_VERSION_NAME}`,
  changelog: [
    '学期课表手动同步，多端修改秒级拉取最新数据',
    '优化单课表下拉交互与周次浏览状态保持',
    '提升课表助手连接稳定性'
  ],
  downloadUrl: `https://api.tanzeng.xyz/downloads/%E5%BA%8F%E6%97%B6_v${CURRENT_VERSION_NAME}.apk`,
  backupDownloadUrl: `https://api.tanzeng.xyz/downloads/%E5%BA%8F%E6%97%B6_v${CURRENT_VERSION_NAME}.apk`,
};

const versionData = ref({ ...defaultVersion });
const showModal = ref(false);
const modalTab = ref('wechat'); // 'wechat' | 'android'
const copySuccess = ref(false);

const qrCodeUrl = computed(() => {
  const url = encodeURIComponent(versionData.value.downloadUrl);
  return `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${url}`;
});

async function fetchVersion() {
  try {
    const data = await appApi.getVersion();
    if (data && data.versionName) {
      versionData.value = {
        ...defaultVersion,
        ...data,
      };
    }
  } catch {
    // 降级静态配置
  }
}

function openModal(tab = 'wechat') {
  modalTab.value = tab;
  showModal.value = true;
}

function handleDownload(type = 'primary') {
  const target = type === 'backup' && versionData.value.backupDownloadUrl
    ? versionData.value.backupDownloadUrl
    : versionData.value.downloadUrl;
  if (!target) return;
  window.open(target, '_blank');
}

async function copyLink() {
  const link = versionData.value.downloadUrl;
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(link);
      copySuccess.value = true;
      setTimeout(() => { copySuccess.value = false; }, 2200);
    }
  } catch {}
}

onMounted(() => {
  fetchVersion();
});
</script>

<template>
  <div class="m3-app">
    <!-- M3 顶部导航栏 (Top App Bar) -->
    <header class="m3-top-app-bar">
      <div class="app-bar-inner">
        <div class="app-brand">
          <img src="/app-icon.png" alt="序时 Logo" class="brand-icon" />
          <div class="brand-text">
            <span class="brand-title">序时</span>
            <span class="m3-chip m3-chip-sm">XuShi Schedule</span>
          </div>
        </div>

        <nav class="app-bar-actions">
          <button class="m3-btn m3-btn-tonal" @click="openModal('wechat')">
            <svg class="m3-icon" viewBox="0 0 24 24" fill="currentColor">
              <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
              <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
            </svg>
            <span>微信小程序</span>
          </button>
          <button class="m3-btn m3-btn-filled" @click="openModal('android')">
            <svg class="m3-icon" viewBox="0 0 24 24" fill="currentColor">
              <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
              <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
            </svg>
            <span>下载 Android 版</span>
          </button>
        </nav>
      </div>
    </header>

    <!-- 主体区域 -->
    <main class="m3-main">
      <!-- Hero 区域 -->
      <section class="m3-hero">
        <div class="m3-badge-pill">
          <span class="m3-badge-dot"></span>
          <span>Google Material 3 · 统一全栈驱动</span>
        </div>

        <h1 class="m3-hero-headline">
          课表装进微信，<br />
          <span class="m3-hero-accent">也装进每一台 Android。</span>
        </h1>

        <p class="m3-hero-subhead">
          为大学生打造的纯粹智能课表工具。微信小程序免安装即开即用，Android 原生端教务一键直连。
          全周日程清爽呈现，告别冗余与繁杂。
        </p>

        <div class="m3-hero-cta">
          <button class="m3-btn m3-btn-large m3-btn-wx-filled" @click="openModal('wechat')">
            <svg class="m3-icon m3-icon-lg" viewBox="0 0 24 24" fill="currentColor">
              <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
              <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
            </svg>
            <span>使用微信小程序</span>
          </button>

          <button class="m3-btn m3-btn-large m3-btn-android-filled" @click="handleDownload('primary')">
            <svg class="m3-icon m3-icon-lg" viewBox="0 0 24 24" fill="currentColor">
              <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
              <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
            </svg>
            <span>下载 Android APK (v{{ versionData.versionName }})</span>
          </button>
        </div>
      </section>

      <!-- 双端核心入口 (M3 Elevated Cards) -->
      <section class="m3-platforms">
        <div class="m3-platform-grid">
          <!-- 微信小程序卡片 -->
          <div class="m3-card m3-card-wx">
            <div class="m3-card-header">
              <div class="m3-icon-avatar m3-avatar-wx">
                <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
                  <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
                  <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
                </svg>
              </div>
              <div class="m3-header-meta">
                <span class="m3-chip m3-chip-wx">微信生态 · 即开即用</span>
                <h2 class="m3-card-title">微信小程序</h2>
                <p class="m3-card-sub">免安装 · 扫码或微信直接搜索</p>
              </div>
            </div>

            <div class="m3-card-body">
              <ul class="m3-feature-list">
                <li>
                  <div class="m3-list-icon m3-list-icon-wx">✓</div>
                  <div class="m3-list-text">
                    <strong>微信静默登录</strong>
                    <span>无需注册繁琐账号，微信生态一键直达</span>
                  </div>
                </li>
                <li>
                  <div class="m3-list-icon m3-list-icon-wx">✓</div>
                  <div class="m3-list-text">
                    <strong>智能 Agent 聊天查课</strong>
                    <span>微信聊天窗口随口问“明天有什么课”，秒级响应</span>
                  </div>
                </li>
                <li>
                  <div class="m3-list-icon m3-list-icon-wx">✓</div>
                  <div class="m3-list-text">
                    <strong>同域云端同步</strong>
                    <span>与 Android 端共用同一套后端，换设备不丢数据</span>
                  </div>
                </li>
              </ul>
            </div>

            <div class="m3-card-footer">
              <button class="m3-btn m3-btn-wx-tonal m3-btn-full" @click="openModal('wechat')">
                <span>扫码或搜索使用</span>
                <span class="m3-arrow">→</span>
              </button>
            </div>
          </div>

          <!-- Android 原生客户端卡片 -->
          <div class="m3-card m3-card-android">
            <div class="m3-card-header">
              <div class="m3-icon-avatar m3-avatar-android">
                <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
                  <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
                  <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
                </svg>
              </div>
              <div class="m3-header-meta">
                <span class="m3-chip m3-chip-android">v{{ versionData.versionName }} · 约 12MB</span>
                <h2 class="m3-card-title">Android 原生客户端</h2>
                <p class="m3-card-sub">教务直连 · 沉浸式排版体验</p>
              </div>
            </div>

            <div class="m3-card-body">
              <ul class="m3-feature-list">
                <li>
                  <div class="m3-list-icon m3-list-icon-android">✓</div>
                  <div class="m3-list-text">
                    <strong>高校教务一键直连</strong>
                    <span>内置原生 WebView 毫秒级抓取强智等教务</span>
                  </div>
                </li>
                <li>
                  <div class="m3-list-icon m3-list-icon-android">✓</div>
                  <div class="m3-list-text">
                    <strong>连堂大课合并排版</strong>
                    <span>2 节连堂与 4 节大课自动合为整块卡片</span>
                  </div>
                </li>
                <li>
                  <div class="m3-list-icon m3-list-icon-android">✓</div>
                  <div class="m3-list-text">
                    <strong>视频动态壁纸与离线缓存</strong>
                    <span>沉浸视觉体验，无网状态课表依然清晰可见</span>
                  </div>
                </li>
              </ul>
            </div>

            <div class="m3-card-footer m3-footer-actions">
              <button class="m3-btn m3-btn-android-filled m3-btn-grow" @click="handleDownload('primary')">
                <span>下载 APK 安装包</span>
                <span class="m3-arrow">↓</span>
              </button>
              <button class="m3-btn m3-btn-outlined" @click="openModal('android')">
                <span>扫码安装</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- 4 大核心特性网格 (M3 Tonal Surface Cards) -->
      <section class="m3-features">
        <div class="m3-section-header">
          <span class="m3-chip m3-chip-neutral">专为课表打造</span>
          <h2 class="m3-section-title">核心特性，简洁而从容</h2>
        </div>

        <div class="m3-features-grid">
          <div class="m3-feature-card">
            <div class="m3-feature-icon-box m3-icon-box-blue">
              <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
                <path d="M6 12v5c3 3 9 3 12 0v-5"/>
              </svg>
            </div>
            <h3>教务系统直连</h3>
            <p>内置原生 WebView 登录强智等主流教务，请求拦截毫秒级捕获课表，无需导出或繁琐抓包。</p>
          </div>

          <div class="m3-feature-card">
            <div class="m3-feature-icon-box m3-icon-box-green">
              <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="17 1 21 5 17 9"/>
                <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
                <polyline points="7 23 3 19 7 15"/>
                <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
              </svg>
            </div>
            <h3>AI 调课中心</h3>
            <p>上传调课通知截图，大模型视觉智能提取调整前后时段与教室，支持批量应用与变更追溯。</p>
          </div>

          <div class="m3-feature-card">
            <div class="m3-feature-icon-box m3-icon-box-amber">
              <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                <circle cx="9" cy="10" r="1"/>
                <circle cx="12" cy="10" r="1"/>
                <circle cx="15" cy="10" r="1"/>
              </svg>
            </div>
            <h3>微信 Agent 问课</h3>
            <p>与微信智能 Agent 绑定，在聊天对话框里直接问“明天有什么课”，意图调度秒级回复。</p>
          </div>

          <div class="m3-feature-card">
            <div class="m3-feature-icon-box m3-icon-box-purple">
              <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="8" y1="13" x2="16" y2="13"/>
                <line x1="8" y1="17" x2="13" y2="17"/>
              </svg>
            </div>
            <h3>Excel 智能解析</h3>
            <p>支持多种高校导出的 xlsx/xls/xlsm 表格，确定性规则结合大模型语义兜底，非标表轻松导入。</p>
          </div>
        </div>
      </section>
    </main>

    <!-- M3 极简页脚 -->
    <footer class="m3-footer">
      <div class="m3-footer-inner">
        <div class="m3-footer-brand">
          <img src="/app-icon.png" alt="Logo" class="m3-footer-logo" />
          <span>序时 (XuShi) · 极简智能大学课表</span>
        </div>
        <div class="m3-footer-links">
          <a :href="versionData.downloadUrl" target="_blank">APK 镜像下载</a>
          <span class="m3-sep">•</span>
          <span>纯粹无广告</span>
        </div>
      </div>
    </footer>

    <!-- M3 风格弹窗 (Material 3 Dialog) -->
    <div v-if="showModal" class="m3-dialog-scrim" @click="showModal = false">
      <div class="m3-dialog" @click.stop>
        <!-- 弹窗标签切换 (Segmented Button) -->
        <div class="m3-segmented-control">
          <button
            class="m3-segment-btn"
            :class="{ active: modalTab === 'wechat' }"
            @click="modalTab = 'wechat'"
          >
            微信小程序
          </button>
          <button
            class="m3-segment-btn"
            :class="{ active: modalTab === 'android' }"
            @click="modalTab = 'android'"
          >
            Android 安装包
          </button>
        </div>

        <button class="m3-dialog-close" @click="showModal = false" aria-label="关闭">
          ✕
        </button>

        <!-- 微信小程序内容 -->
        <div v-if="modalTab === 'wechat'" class="m3-dialog-content">
          <div class="m3-dialog-center">
            <div class="m3-qr-card-wx">
              <img src="/app-icon.png" alt="序时小程序" class="m3-qr-avatar" />
              <h3 class="m3-dialog-title">序时课表</h3>
              <p class="m3-dialog-sub">微信小程序 · 免安装即开即用</p>
            </div>

            <div class="m3-search-guide">
              <span class="m3-guide-label">使用方式</span>
              <div class="m3-search-input-sim">
                <span class="m3-sim-icon">🔍</span>
                <span>微信搜索 <strong>序时课表</strong> 即可使用</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Android 下载内容 -->
        <div v-else class="m3-dialog-content">
          <div class="m3-dialog-center">
            <div class="m3-qr-box">
              <img :src="qrCodeUrl" alt="APK 下载二维码" class="m3-qr-img" />
              <p class="m3-qr-hint">使用手机自带相机或浏览器扫码直链下载</p>
            </div>

            <div class="m3-dialog-actions">
              <button class="m3-btn m3-btn-android-filled m3-btn-full" @click="handleDownload('primary')">
                <span>下载 APK (v{{ versionData.versionName }})</span>
                <span>↓</span>
              </button>
              <button class="m3-btn m3-btn-tonal m3-btn-full" @click="copyLink">
                {{ copySuccess ? '✓ 已复制下载链接！' : '复制下载直链' }}
              </button>
            </div>

            <div v-if="versionData.changelog?.length" class="m3-changelog-box">
              <span class="m3-changelog-title">最近更新</span>
              <ul>
                <li v-for="(log, idx) in versionData.changelog.slice(0, 3)" :key="idx">{{ log }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==========================================================================
   Google Material 3 (Material Design 3 / M3) 设计系统
   配色契约：
   - Surface / Background: #f8f9fa / #ffffff (明亮清洁、柔和开阔)
   - Primary: #0b57d0 (Google M3 Blue)
   - Primary Container: #d3e3fd, On-Primary Container: #041e49
   - Secondary (WeChat Green): #0f8f4c / #e6f7ec
   - Neutral Surface Containers: #f0f4f9, #e9eef6, #e0e3e7
   - Typography: Google Sans, Roboto, PingFang SC
   ========================================================================== */

.m3-app {
  min-height: 100vh;
  background-color: #f8f9fa;
  color: #1f1f1f;
  font-family: "Google Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
  display: flex;
  flex-direction: column;
}

/* 顶部 Top App Bar */
.m3-top-app-bar {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(248, 249, 250, 0.92);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid #e0e3e7;
}
.app-bar-inner {
  max-width: 1100px;
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.app-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.brand-text {
  display: flex;
  align-items: center;
  gap: 8px;
}
.brand-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1f1f1f;
  letter-spacing: -0.02em;
}

/* M3 通用按钮系统 (Pill Shape) */
.m3-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 100px; /* M3 标准 Pill 药丸按钮 */
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s cubic-bezier(0.2, 0, 0, 1);
  text-decoration: none;
}
.m3-btn:active {
  transform: scale(0.98);
}
.m3-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}
.m3-icon-lg {
  width: 20px;
  height: 20px;
}

.m3-btn-filled {
  background: #0b57d0;
  color: #ffffff;
}
.m3-btn-filled:hover {
  background: #0842a0;
  box-shadow: 0 1px 3px 1px rgba(11, 87, 208, 0.25);
}

.m3-btn-tonal {
  background: #e9eef6;
  color: #1f1f1f;
}
.m3-btn-tonal:hover {
  background: #dbe4f0;
}

.m3-btn-outlined {
  background: transparent;
  border-color: #c4c7c5;
  color: #1f1f1f;
}
.m3-btn-outlined:hover {
  background: rgba(31, 31, 31, 0.04);
}

.m3-btn-wx-filled {
  background: #0f8f4c;
  color: #ffffff;
}
.m3-btn-wx-filled:hover {
  background: #0c733d;
  box-shadow: 0 3px 12px rgba(15, 143, 76, 0.25);
}

.m3-btn-android-filled {
  background: #0b57d0;
  color: #ffffff;
}
.m3-btn-android-filled:hover {
  background: #0842a0;
  box-shadow: 0 3px 12px rgba(11, 87, 208, 0.25);
}

.m3-btn-wx-tonal {
  background: #e6f7ec;
  color: #0c733d;
}
.m3-btn-wx-tonal:hover {
  background: #cfeed8;
}

.m3-btn-large {
  padding: 14px 28px;
  font-size: 0.96rem;
  border-radius: 100px;
}
.m3-btn-full {
  width: 100%;
}
.m3-btn-grow {
  flex: 1;
}

/* M3 Chips */
.m3-chip {
  display: inline-flex;
  align-items: center;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 8px;
}
.m3-chip-sm {
  padding: 2px 8px;
  font-size: 0.7rem;
  background: #e9eef6;
  color: #444746;
}
.m3-chip-wx {
  background: #e6f7ec;
  color: #0c733d;
}
.m3-chip-android {
  background: #d3e3fd;
  color: #041e49;
}
.m3-chip-neutral {
  background: #e0e3e7;
  color: #444746;
}

/* 主内容区域 */
.m3-main {
  flex: 1;
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
  padding: 50px 24px 70px;
  box-sizing: border-box;
}

/* Hero 区域 */
.m3-hero {
  text-align: center;
  padding: 20px 0 55px;
}
.m3-badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #e8f0fe;
  color: #1967d2;
  padding: 6px 16px;
  border-radius: 100px;
  font-size: 0.82rem;
  font-weight: 600;
  margin-bottom: 24px;
}
.m3-badge-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #1a73e8;
}

.m3-hero-headline {
  font-size: 2.85rem;
  line-height: 1.25;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #1f1f1f;
  margin: 0 0 18px;
}
.m3-hero-accent {
  color: #0b57d0;
}
.m3-hero-subhead {
  max-width: 640px;
  margin: 0 auto 36px;
  font-size: 1.1rem;
  line-height: 1.65;
  color: #444746;
}
.m3-hero-cta {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}

/* M3 双端卡片系统 (M3 Elevated Cards) */
.m3-platforms {
  margin-bottom: 60px;
}
.m3-platform-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 28px;
}

.m3-card {
  background: #ffffff;
  border-radius: 28px; /* M3 标准大圆角 */
  padding: 32px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
  border: 1px solid #e0e3e7;
  transition: transform 0.25s cubic-bezier(0.2, 0, 0, 1), box-shadow 0.25s cubic-bezier(0.2, 0, 0, 1);
}
.m3-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.09);
}

.m3-card-wx {
  background: linear-gradient(180deg, #ffffff 0%, #f6fcf8 100%);
  border-color: #d1ebd8;
}
.m3-card-android {
  background: linear-gradient(180deg, #ffffff 0%, #f4f8fd 100%);
  border-color: #d5e4f7;
}

.m3-card-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
}
.m3-icon-avatar {
  width: 54px;
  height: 54px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.m3-avatar-wx {
  background: #e6f7ec;
  color: #0f8f4c;
}
.m3-avatar-android {
  background: #d3e3fd;
  color: #0b57d0;
}

.m3-header-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.m3-card-title {
  font-size: 1.35rem;
  font-weight: 700;
  color: #1f1f1f;
  margin: 2px 0 0;
}
.m3-card-sub {
  font-size: 0.88rem;
  color: #444746;
  margin: 0;
}

.m3-card-body {
  flex: 1;
  margin-bottom: 28px;
}
.m3-feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.m3-feature-list li {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.m3-list-icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  flex-shrink: 0;
  margin-top: 2px;
}
.m3-list-icon-wx {
  background: #e6f7ec;
  color: #0f8f4c;
}
.m3-list-icon-android {
  background: #d3e3fd;
  color: #0b57d0;
}
.m3-list-text {
  display: flex;
  flex-direction: column;
}
.m3-list-text strong {
  font-size: 0.95rem;
  color: #1f1f1f;
}
.m3-list-text span {
  font-size: 0.84rem;
  color: #5e6368;
  line-height: 1.4;
}

.m3-card-footer {
  margin-top: auto;
}
.m3-footer-actions {
  display: flex;
  gap: 10px;
}
.m3-arrow {
  font-weight: 700;
}

/* 4 大核心特性网格 (M3 Tonal Surface Cards) */
.m3-features {
  padding-top: 10px;
}
.m3-section-header {
  text-align: center;
  margin-bottom: 32px;
}
.m3-section-title {
  font-size: 1.6rem;
  font-weight: 700;
  color: #1f1f1f;
  margin: 10px 0 0;
}

.m3-features-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
}
.m3-feature-card {
  background: #ffffff;
  border-radius: 20px;
  padding: 24px 20px;
  border: 1px solid #e0e3e7;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: all 0.2s cubic-bezier(0.2, 0, 0, 1);
}
.m3-feature-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-color: #c4c7c5;
}
.m3-feature-icon-box {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}
.m3-icon-box-blue {
  background: #e8f0fe;
  color: #1a73e8;
}
.m3-icon-box-green {
  background: #e6f4ea;
  color: #137333;
}
.m3-icon-box-amber {
  background: #fef7e0;
  color: #b06000;
}
.m3-icon-box-purple {
  background: #f3e8fd;
  color: #8430ce;
}
.m3-feature-card h3 {
  font-size: 1.05rem;
  font-weight: 700;
  color: #1f1f1f;
  margin: 0 0 8px;
}
.m3-feature-card p {
  font-size: 0.84rem;
  line-height: 1.6;
  color: #5e6368;
  margin: 0;
}

/* 页脚 */
.m3-footer {
  border-top: 1px solid #e0e3e7;
  background: #ffffff;
  padding: 24px;
  margin-top: auto;
}
.m3-footer-inner {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.85rem;
  color: #5e6368;
  flex-wrap: wrap;
  gap: 12px;
}
.m3-footer-brand {
  display: flex;
  align-items: center;
  gap: 8px;
}
.m3-footer-logo {
  width: 22px;
  height: 22px;
  border-radius: 6px;
}
.m3-footer-links {
  display: flex;
  align-items: center;
  gap: 10px;
}
.m3-footer-links a {
  color: #1a73e8;
  text-decoration: none;
}
.m3-footer-links a:hover {
  text-decoration: underline;
}
.m3-sep {
  color: #c4c7c5;
}

/* M3 弹窗系统 (Material 3 Dialog & Scrim) */
.m3-dialog-scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 20px;
}
.m3-dialog {
  background: #ffffff;
  border-radius: 28px; /* M3 标准 Dialog 圆角 */
  width: 100%;
  max-width: 420px;
  padding: 28px;
  position: relative;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.18);
  box-sizing: border-box;
}
.m3-dialog-close {
  position: absolute;
  top: 18px;
  right: 18px;
  background: #f0f4f9;
  border: none;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: #444746;
  font-size: 1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}
.m3-dialog-close:hover {
  background: #e0e3e7;
  color: #1f1f1f;
}

/* M3 Segmented Button (分段控件) */
.m3-segmented-control {
  display: flex;
  background: #f0f4f9;
  border-radius: 100px;
  padding: 4px;
  margin-bottom: 24px;
  margin-right: 36px;
}
.m3-segment-btn {
  flex: 1;
  padding: 8px 12px;
  border-radius: 100px;
  font-size: 0.85rem;
  font-weight: 600;
  border: none;
  background: transparent;
  color: #444746;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.2, 0, 0, 1);
}
.m3-segment-btn.active {
  background: #ffffff;
  color: #0b57d0;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.m3-dialog-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.m3-qr-card-wx {
  background: #f2f9f4;
  border: 1px solid #cce8d5;
  border-radius: 20px;
  padding: 24px;
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 18px;
}
.m3-qr-avatar {
  width: 60px;
  height: 60px;
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  margin-bottom: 12px;
}
.m3-dialog-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1f1f1f;
  margin: 0 0 4px;
}
.m3-dialog-sub {
  font-size: 0.85rem;
  color: #0f8f4c;
  margin: 0;
  font-weight: 500;
}

.m3-search-guide {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.m3-guide-label {
  font-size: 0.8rem;
  color: #5e6368;
  font-weight: 600;
  text-align: left;
}
.m3-search-input-sim {
  background: #f0f4f9;
  border: 1px solid #e0e3e7;
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 0.92rem;
  color: #1f1f1f;
  display: flex;
  align-items: center;
  gap: 8px;
}
.m3-sim-icon {
  font-size: 1rem;
}

.m3-qr-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.m3-qr-img {
  width: 180px;
  height: 180px;
  border-radius: 16px;
  background: #ffffff;
  padding: 10px;
  border: 1px solid #e0e3e7;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}
.m3-qr-hint {
  font-size: 0.82rem;
  color: #5e6368;
  margin: 0;
}

.m3-dialog-actions {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.m3-changelog-box {
  margin-top: 16px;
  width: 100%;
  text-align: left;
  background: #f0f4f9;
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 0.8rem;
  color: #444746;
  box-sizing: border-box;
}
.m3-changelog-title {
  font-weight: 700;
  color: #1f1f1f;
}
.m3-changelog-box ul {
  margin: 6px 0 0;
  padding-left: 18px;
}
.m3-changelog-box li {
  margin-bottom: 3px;
}

/* 响应式断点 */
@media (max-width: 860px) {
  .m3-hero-headline {
    font-size: 2.3rem;
  }
  .m3-platform-grid {
    grid-template-columns: 1fr;
    gap: 20px;
  }
  .m3-features-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .m3-main {
    padding: 30px 16px 50px;
  }
  .app-bar-inner {
    padding: 12px 16px;
  }
  .m3-hero-headline {
    font-size: 1.85rem;
  }
  .m3-hero-subhead {
    font-size: 0.95rem;
  }
  .m3-hero-cta {
    flex-direction: column;
    width: 100%;
  }
  .m3-btn-large {
    width: 100%;
  }
  .m3-features-grid {
    grid-template-columns: 1fr;
  }
  .m3-card {
    padding: 24px 20px;
  }
  .m3-footer-inner {
    flex-direction: column;
    text-align: center;
    gap: 10px;
  }
}
</style>
