<script setup>
import { computed, onMounted, ref } from 'vue';
import { appApi } from '../api/index.js';
import { CURRENT_VERSION_CODE, CURRENT_VERSION_NAME } from '../utils/version.js';

// 兜底数据：接口异常时展示；正常情况以 /api/app/version 实时数据为准
const defaultVersion = {
  versionCode: CURRENT_VERSION_CODE,
  versionName: CURRENT_VERSION_NAME,
  title: `发现新版本 v${CURRENT_VERSION_NAME}`,
  changelog: [],
  downloadUrl: `https://api.tanzeng.xyz/downloads/%E5%BA%8F%E6%97%B6_v${CURRENT_VERSION_NAME}.apk`,
  backupDownloadUrl: `https://api.tanzeng.xyz/downloads/%E5%BA%8F%E6%97%B6_v${CURRENT_VERSION_NAME}.apk`,
};

const versionData = ref({ ...defaultVersion });
const activeTab = ref('regular'); // 'regular' | 'design' | 'webview'
const showQrModal = ref(false);
const copySuccess = ref(false);

const currentScreenshot = computed(() => {
  if (activeTab.value === 'design') {
    return '/screenshots/preview_design.png';
  }
  if (activeTab.value === 'webview') {
    return '/screenshots/preview_webview.png';
  }
  return '/screenshots/preview_regular.png';
});

const qrCodeUrl = computed(() => {
  const url = encodeURIComponent(versionData.value.downloadUrl);
  return `https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=${url}`;
});

const androidChangelog = computed(() => (versionData.value.changelog || []).slice(0, 4));

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
    // 降级使用默认静态配置
  }
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
  } catch {
    // ignore
  }
}

function scrollToSection(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 双端能力对照（true=支持，false=不支持，字符串=说明文字）
const compareRows = [
  { name: '登录方式', miniapp: '微信静默登录 · 免注册', android: '邮箱注册 / 登录' },
  { name: '获取方式', miniapp: '微信内搜索，即开即用', android: 'APK 安装（约 12MB）' },
  { name: '教务系统一键直连', miniapp: false, android: true },
  { name: 'Excel 导入 · AI 智能解析', miniapp: true, android: true },
  { name: '调课中心 · 通知图片 AI 识别', miniapp: true, android: true },
  { name: '连堂大课合并排版', miniapp: true, android: true },
  { name: '自定义背景', miniapp: '相册背景', android: '视频壁纸 / 相册' },
  { name: '微信 Agent 聊天查课', miniapp: true, android: false },
  { name: '版本更新', miniapp: '随微信平台自动更新', android: '应用内检查 APK 更新' },
  { name: '数据同步', miniapp: '同一后端 · 双端互通', android: '同一后端 · 双端互通' },
];

const coreFeatures = [
  {
    tag: '小程序',
    tagType: 'miniapp',
    title: '微信静默登录 · 免注册',
    desc: '打开即用，无需注册账号。数据按微信账号隔离，登录态静默续期，换手机课表也不丢。',
    icon: 'wechat',
  },
  {
    tag: 'Android',
    tagType: 'android',
    title: '高校教务一键直连',
    desc: '原生 WebView 内登录强智教务，请求拦截毫秒级捕获课表数据，全程无需手动导出文件或抓包。',
    icon: 'android',
  },
  {
    tag: '双端',
    tagType: 'both',
    title: 'Excel 导入 · AI 智能兜底',
    desc: '支持教务系统导出的 xlsx/xlsm/xls，确定性规则秒级解析；遇到非标表格自动切换大模型语义解析，导入无忧。',
    icon: 'file',
  },
  {
    tag: '双端',
    tagType: 'both',
    title: '调课中心 · 图片 AI 识别',
    desc: '上传调课通知截图，AI 自动提取「调整前 / 调整后」并匹配课程，勾选确认后批量应用；变更记录随时追溯撤销。',
    icon: 'swap',
  },
  {
    tag: '双端',
    tagType: 'both',
    title: '连堂大课规范排版',
    desc: '2 节连堂与 4 节课程设计自动合并为整块大卡片，拒绝单节碎卡片的割裂感，全周作息一目了然。',
    icon: 'grid',
  },
  {
    tag: '微信生态',
    tagType: 'miniapp',
    title: '微信 Agent 聊天查课',
    desc: '完成绑定后，直接在微信对话里问「明天有什么课」，课表 Agent 意图识别 + 技能调度，秒级回复。',
    icon: 'chat',
  },
];

onMounted(() => {
  fetchVersion();
});
</script>

<template>
  <div class="landing-container">
    <!-- 顶部极简导航栏 -->
    <header class="landing-header">
      <div class="header-inner">
        <div class="brand-box">
          <img src="/app-icon.png" alt="序时" class="brand-icon-img" />
          <div class="brand-text">
            <span class="brand-name">序时</span>
            <span class="version-badge">微信小程序 · Android</span>
          </div>
        </div>

        <nav class="nav-links">
          <a href="#access" class="nav-item" @click.prevent="scrollToSection('access')">双端入口</a>
          <a href="#features" class="nav-item" @click.prevent="scrollToSection('features')">核心特性</a>
          <a href="#showcase" class="nav-item" @click.prevent="scrollToSection('showcase')">真机预览</a>
          <a href="#compare" class="nav-item" @click.prevent="scrollToSection('compare')">能力对照</a>
        </nav>

        <div class="header-actions">
          <button type="button" class="header-download-btn" @click="handleDownload('primary')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            <span>下载 APK</span>
          </button>
        </div>
      </div>
    </header>

    <!-- 主 Hero 视觉区域 -->
    <main class="landing-main">
      <section class="hero-section">
        <div class="hero-pill">
          <span class="hero-sparkle">✦</span>
          <span>同一套后端 · 微信小程序与 Android 双端数据互通</span>
        </div>

        <h1 class="hero-title">
          课表装进微信，<br />
          也装进每一台 Android。
        </h1>

        <p class="hero-subtitle">
          「序时」是为大学生打造的极简课表工具：微信小程序免注册、即开即用；Android App 支持高校教务系统一键直连导入。Excel 智能解析、调课中心、AI 图片识别调课双端齐备，数据同一后端云端同步。
        </p>

        <div class="hero-cta-group">
          <button type="button" class="primary-cta-btn wechat-cta" @click="scrollToSection('access')">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
              <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
            </svg>
            <span>获取微信小程序</span>
          </button>

          <button type="button" class="secondary-cta-btn" @click="handleDownload('primary')">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
              <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
            </svg>
            <span>下载 Android APK</span>
          </button>
        </div>

        <div class="hero-specs">
          <span class="spec-item">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
            微信免注册即开即用
          </span>
          <span class="spec-dot">·</span>
          <span class="spec-item">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
            Android 8.0+ · 约 12MB
          </span>
          <span class="spec-dot">·</span>
          <span class="spec-item">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
            完全纯净无广告
          </span>
        </div>
      </section>

      <!-- 双端入口卡片 -->
      <section id="access" class="access-section">
        <div class="section-badge">双端入口</div>
        <h2 class="section-title">两种方式，即刻开始</h2>
        <p class="section-desc">同一账号体系下的两套体验，按你的习惯任选其一</p>

        <div class="access-grid">
          <!-- 微信小程序卡片 -->
          <div class="access-card miniapp-card">
            <div class="access-card-head">
              <img src="/app-icon.png" alt="序时小程序图标" class="access-avatar" />
              <div class="access-head-text">
                <h3 class="access-card-title">微信小程序</h3>
                <span class="access-card-sub">免安装 · 微信内即开即用</span>
              </div>
            </div>

            <ul class="access-feature-list">
              <li>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                微信静默登录，免注册免密码
              </li>
              <li>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                Excel 导入 + AI 解析、调课中心完整体验
              </li>
              <li>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                绑定微信 Agent，聊天窗口直接查课
              </li>
            </ul>

            <div class="wx-search-box">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"/>
                <line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <span class="wx-search-keyword">序时课表</span>
              <span class="wx-search-enter">进入</span>
            </div>

            <div class="access-steps">
              <span class="step-item"><i>1</i>打开微信</span>
              <span class="step-arrow">→</span>
              <span class="step-item"><i>2</i>搜索「序时课表」</span>
              <span class="step-arrow">→</span>
              <span class="step-item"><i>3</i>点击进入</span>
            </div>
          </div>

          <!-- Android 卡片 -->
          <div class="access-card android-card">
            <div class="access-card-head">
              <img src="/app-icon-light.png" alt="序时 Android 图标" class="access-avatar" />
              <div class="access-head-text">
                <h3 class="access-card-title">Android App</h3>
                <span class="access-card-sub">v{{ versionData.versionName }} · 安装包约 12MB</span>
              </div>
            </div>

            <ul class="access-feature-list">
              <li>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                强智教务系统一键直连导入
              </li>
              <li>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                视频壁纸、桌面小组件等原生体验
              </li>
              <li>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                应用内检查更新，持续迭代
              </li>
            </ul>

            <div class="android-actions">
              <button type="button" class="btn-apk-primary" @click="handleDownload('primary')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                <span>下载 APK</span>
              </button>
              <button type="button" class="btn-apk-qr" @click="showQrModal = true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="3" width="7" height="7"/>
                  <rect x="14" y="3" width="7" height="7"/>
                  <rect x="14" y="14" width="7" height="7"/>
                  <rect x="3" y="14" width="7" height="7"/>
                </svg>
                <span>扫码安装</span>
              </button>
            </div>

            <div v-if="androidChangelog.length" class="android-changelog">
              <div class="changelog-line">✨ v{{ versionData.versionName }} 更新</div>
              <div v-for="(item, idx) in androidChangelog" :key="idx" class="changelog-item">{{ item }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- 核心功能 Bento 网格 -->
      <section id="features" class="features-section">
        <div class="section-badge">核心特性</div>
        <h2 class="section-title">两端共享的完整课表体验</h2>
        <p class="section-desc">没有无意义的社交动态与冗余广告，专注于课表本身的高效与从容</p>

        <div class="bento-grid">
          <div v-for="feature in coreFeatures" :key="feature.title" class="bento-card">
            <div class="bento-top">
              <div class="bento-icon-box">
                <!-- 微信图标 -->
                <svg v-if="feature.icon === 'wechat'" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
                  <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
                </svg>
                <!-- 安卓图标 -->
                <svg v-else-if="feature.icon === 'android'" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
                  <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
                </svg>
                <!-- 文件图标 -->
                <svg v-else-if="feature.icon === 'file'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="8" y1="13" x2="16" y2="13"/>
                  <line x1="8" y1="17" x2="13" y2="17"/>
                </svg>
                <!-- 调课图标 -->
                <svg v-else-if="feature.icon === 'swap'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="17 1 21 5 17 9"/>
                  <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
                  <polyline points="7 23 3 19 7 15"/>
                  <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
                </svg>
                <!-- 网格图标 -->
                <svg v-else-if="feature.icon === 'grid'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2"/>
                  <path d="M3 9h18"/>
                  <path d="M9 21V9"/>
                </svg>
                <!-- 聊天图标 -->
                <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                  <line x1="8" y1="9" x2="16" y2="9"/>
                  <line x1="8" y1="13" x2="13" y2="13"/>
                </svg>
              </div>
              <span class="bento-tag" :class="`tag-${feature.tagType}`">{{ feature.tag }}</span>
            </div>
            <h3 class="bento-title">{{ feature.title }}</h3>
            <p class="bento-desc">{{ feature.desc }}</p>
          </div>
        </div>
      </section>

      <!-- Android 真机预览 -->
      <section id="showcase" class="showcase-section">
        <div class="section-badge">真机体验</div>
        <h2 class="section-title">Android 端 · 所见即所得的克制美学</h2>
        <p class="section-desc">每一处留白与卡片圆角均经精心推敲，拒绝单节碎卡片，清晰呈现全貌</p>

        <div class="mockup-tab-pills">
          <button
            type="button"
            class="tab-pill"
            :class="{ active: activeTab === 'regular' }"
            @click="activeTab = 'regular'"
          >
            <span class="tab-dot"></span>
            <span>常规周 · 2节连堂排版</span>
          </button>
          <button
            type="button"
            class="tab-pill"
            :class="{ active: activeTab === 'design' }"
            @click="activeTab = 'design'"
          >
            <span class="tab-dot"></span>
            <span>课程设计 · 4节连堂整块</span>
          </button>
          <button
            type="button"
            class="tab-pill"
            :class="{ active: activeTab === 'webview' }"
            @click="activeTab = 'webview'"
          >
            <span class="tab-dot"></span>
            <span>教务系统 · 极简原生直连</span>
          </button>
        </div>

        <div class="mockup-stage">
          <div class="phone-frame">
            <div class="phone-notch"></div>
            <div class="phone-screen">
              <img
                :src="currentScreenshot"
                :alt="activeTab"
                class="screen-img"
              />
            </div>
          </div>

          <div class="showcase-notes">
            <div v-if="activeTab === 'regular'" class="note-card">
              <div class="note-tag">大课统一连堂</div>
              <h3 class="note-title">标准 2 节连堂大卡片</h3>
              <p class="note-text">
                告别市面传统课表将连堂课切散为单节碎卡片的割裂感。统一规范展现为 <strong>【课程粗体全称】+【(括号教室)】+【授课教师】</strong>，一目了然。
              </p>
            </div>

            <div v-else-if="activeTab === 'design'" class="note-card">
              <div class="note-tag">实训专项布局</div>
              <h3 class="note-title">4 节连堂课程设计</h3>
              <p class="note-text">
                针对高校期末集中的课程设计、金工实习与大型实验，智能拼接 5-8 节全下午时段，跨越 4 节无缝连贯排布，界面大方利落。
              </p>
            </div>

            <div v-else class="note-card">
              <div class="note-tag">无感数据提取</div>
              <h3 class="note-title">极简原生直连 WebView</h3>
              <p class="note-text">
                专为<strong>长沙工业学院</strong>（及全国强智高校教务系统）定制，沉浸式极简顶栏，内置网络拦截与 DOM 解析，登录即自动抓取全学期课表。
              </p>
            </div>

            <div class="note-meta-list">
              <div class="meta-row">
                <span class="meta-label">适配学校</span>
                <span class="meta-val">长沙工业学院 & 全国高校强智系统</span>
              </div>
              <div class="meta-row">
                <span class="meta-label">解析引擎</span>
                <span class="meta-val">确定性矩阵规则 + AI 大模型兜底</span>
              </div>
              <div class="meta-row">
                <span class="meta-label">设计语言</span>
                <span class="meta-val">Liquid Glass 极简通透美学</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 双端能力对照表 -->
      <section id="compare" class="compare-section">
        <div class="section-badge">能力对照</div>
        <h2 class="section-title">微信小程序 vs Android</h2>
        <p class="section-desc">一套 FastAPI 后端同时服务双端，核心课表能力完全一致，差异仅在平台特性</p>

        <div class="compare-table-wrap">
          <table class="compare-table">
            <thead>
              <tr>
                <th class="col-name">能力</th>
                <th class="col-platform">
                  <span class="th-label">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
                      <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
                    </svg>
                    微信小程序
                  </span>
                </th>
                <th class="col-platform">
                  <span class="th-label">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
                      <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
                    </svg>
                    Android App
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in compareRows" :key="row.name">
                <td class="col-name">{{ row.name }}</td>
                <td>
                  <span v-if="row.miniapp === true" class="cell-yes">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                    支持
                  </span>
                  <span v-else-if="row.miniapp === false" class="cell-no">—</span>
                  <span v-else class="cell-text">{{ row.miniapp }}</span>
                </td>
                <td>
                  <span v-if="row.android === true" class="cell-yes">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                    支持
                  </span>
                  <span v-else-if="row.android === false" class="cell-no">—</span>
                  <span v-else class="cell-text">{{ row.android }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>

    <!-- 底部版权与声明 -->
    <footer class="landing-footer">
      <div class="footer-inner">
        <div class="footer-brand">
          <span class="footer-name">序时 · ClassSchedule</span>
          <span class="footer-slogan">专为大学生活打造的极简课表工具</span>
        </div>
        <div class="footer-copy">
          <span>© 2026 序时. 保留所有权利.</span>
          <span class="footer-dot">·</span>
          <span>纯净 · 开源 · 无广告</span>
        </div>
      </div>
    </footer>

    <!-- 手机扫码弹窗（Android APK） -->
    <div v-if="showQrModal" class="qr-modal-backdrop" @click="showQrModal = false">
      <div class="qr-modal-card" @click.stop>
        <button type="button" class="modal-close-btn" @click="showQrModal = false">✕</button>
        <h3 class="modal-title">扫码下载 Android 版</h3>
        <p class="modal-desc">请使用手机自带相机、浏览器或微信扫一扫：</p>
        <div class="modal-qr-box">
          <img :src="qrCodeUrl" alt="下载二维码" class="modal-qr-img" />
        </div>
        <div class="modal-footer-tip">版本 v{{ versionData.versionName }} · 约 12MB</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ====================================================
   序时双端宣传落地页样式系统 (Minimalist Styling)
   ==================================================== */
.landing-container {
  min-height: 100vh;
  background-color: #fafbfc;
  color: #0f172a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  overflow-x: hidden;
  position: relative;
  -webkit-font-smoothing: antialiased;
}

/* 顶部导航 */
.landing-header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(226, 232, 240, 0.75);
}

.header-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand-box {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon-img {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  object-fit: cover;
  display: block;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.16);
}

.brand-text {
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand-name {
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #0f172a;
}

.version-badge {
  font-size: 0.72rem;
  font-weight: 600;
  padding: 2px 7px;
  background: #f1f5f9;
  color: #475569;
  border-radius: 9999px;
  border: 1px solid #e2e8f0;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 26px;
}

.nav-item {
  font-size: 0.88rem;
  font-weight: 500;
  color: #64748b;
  text-decoration: none;
  transition: color 0.18s ease;
}

.nav-item:hover {
  color: #0f172a;
}

.header-download-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 15px;
  background: #0f172a;
  color: #ffffff;
  border: none;
  border-radius: 9999px;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.12);
}

.header-download-btn:hover {
  background: #1e293b;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18);
}

/* 主内容区 */
.landing-main {
  max-width: 1120px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}

.landing-main section {
  scroll-margin-top: 76px;
}

/* Hero */
.hero-section {
  text-align: center;
  padding: 40px 0 60px;
  max-width: 820px;
  margin: 0 auto;
}

.hero-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 9999px;
  font-size: 0.8rem;
  font-weight: 500;
  color: #475569;
  margin-bottom: 24px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
}

.hero-sparkle {
  color: #0284c7;
}

.hero-title {
  font-size: 2.75rem;
  line-height: 1.25;
  font-weight: 800;
  letter-spacing: -0.035em;
  color: #0f172a;
  margin-bottom: 20px;
}

.hero-subtitle {
  font-size: 1.08rem;
  line-height: 1.68;
  color: #475569;
  max-width: 640px;
  margin: 0 auto 36px;
}

.hero-cta-group {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.primary-cta-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 13px 28px;
  background: #0f172a;
  color: #ffffff;
  border: none;
  border-radius: 9999px;
  font-size: 0.98rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.22s ease;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.18);
}

.primary-cta-btn:hover {
  background: #1e293b;
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.24);
}

.primary-cta-btn.wechat-cta {
  background: #07c160;
  box-shadow: 0 6px 20px rgba(7, 193, 96, 0.28);
}

.primary-cta-btn.wechat-cta:hover {
  background: #06ad56;
  box-shadow: 0 8px 24px rgba(7, 193, 96, 0.34);
}

.secondary-cta-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: #ffffff;
  color: #334155;
  border: 1px solid #cbd5e1;
  border-radius: 9999px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.secondary-cta-btn:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.hero-specs {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 0.8rem;
  color: #64748b;
  flex-wrap: wrap;
}

.spec-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.spec-dot {
  color: #cbd5e1;
}

/* 通用段落标记 */
.section-badge {
  display: inline-block;
  padding: 2px 10px;
  background: #f1f5f9;
  color: #475569;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 10px;
}

.section-title {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.025em;
  color: #0f172a;
  margin-bottom: 10px;
}

.section-desc {
  font-size: 0.95rem;
  color: #64748b;
  margin-bottom: 36px;
}

/* 双端入口卡片 */
.access-section {
  padding: 40px 0 60px;
  text-align: center;
}

.access-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
  max-width: 920px;
  margin: 0 auto;
  text-align: left;
}

.access-card {
  border-radius: 24px;
  padding: 30px;
  display: flex;
  flex-direction: column;
  transition: all 0.22s ease;
}

.access-card:hover {
  transform: translateY(-3px);
}

.access-card-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
}

.access-avatar {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  object-fit: cover;
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.14);
}

.access-head-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.access-card-title {
  font-size: 1.3rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.access-card-sub {
  font-size: 0.82rem;
  color: #64748b;
}

.access-feature-list {
  list-style: none;
  margin: 0 0 20px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}

.access-feature-list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 0.9rem;
  line-height: 1.55;
  color: #334155;
}

.access-feature-list li svg {
  flex-shrink: 0;
  margin-top: 3px;
  color: #0284c7;
}

/* 微信小程序卡片 */
.miniapp-card {
  background: linear-gradient(160deg, #f0fdf4 0%, #ffffff 45%);
  border: 1px solid #bbf7d0;
  box-shadow: 0 4px 20px -6px rgba(7, 193, 96, 0.12);
}

.miniapp-card .access-feature-list li svg {
  color: #07c160;
}

.wx-search-box {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ededed;
  border-radius: 12px;
  padding: 12px 16px;
  color: #7a7a7a;
  margin-bottom: 14px;
}

.wx-search-keyword {
  font-size: 0.95rem;
  font-weight: 700;
  color: #111111;
  flex: 1;
}

.wx-search-enter {
  font-size: 0.8rem;
  font-weight: 600;
  color: #07c160;
  background: rgba(7, 193, 96, 0.1);
  padding: 3px 10px;
  border-radius: 9999px;
}

.access-steps {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.step-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: #475569;
}

.step-item i {
  font-style: normal;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #07c160;
  color: #ffffff;
  font-size: 0.68rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.step-arrow {
  color: #cbd5e1;
  font-size: 0.8rem;
}

/* Android 卡片 */
.android-card {
  background: #0f172a;
  color: #ffffff;
  box-shadow: 0 20px 48px -14px rgba(15, 23, 42, 0.4);
}

.android-card:hover {
  box-shadow: 0 26px 56px -14px rgba(15, 23, 42, 0.5);
}

.android-card .access-avatar {
  border-color: transparent;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
}

.android-card .access-card-title {
  color: #ffffff;
}

.android-card .access-card-sub {
  color: #94a3b8;
}

.android-card .access-feature-list li {
  color: #e2e8f0;
}

.android-card .access-feature-list li svg {
  color: #38bdf8;
}

.android-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.btn-apk-primary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 11px 22px;
  background: #ffffff;
  color: #0f172a;
  border: none;
  border-radius: 9999px;
  font-size: 0.92rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 14px rgba(255, 255, 255, 0.18);
}

.btn-apk-primary:hover {
  background: #f1f5f9;
  transform: translateY(-2px);
}

.btn-apk-qr {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 10px 18px;
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 9999px;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-apk-qr:hover {
  background: rgba(255, 255, 255, 0.16);
}

.android-changelog {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  padding: 14px 18px;
}

.changelog-line {
  font-size: 0.82rem;
  font-weight: 600;
  color: #cbd5e1;
  margin-bottom: 6px;
}

.changelog-item {
  font-size: 0.8rem;
  line-height: 1.6;
  color: #94a3b8;
}

.changelog-item::before {
  content: '·';
  margin-right: 6px;
  color: #38bdf8;
  font-weight: 800;
}

/* Bento 网格 */
.features-section {
  padding: 60px 0;
  text-align: center;
}

.bento-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  text-align: left;
}

.bento-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 22px;
  padding: 28px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.02);
  transition: all 0.22s ease;
}

.bento-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 26px rgba(0, 0, 0, 0.05);
  border-color: #cbd5e1;
}

.bento-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.bento-icon-box {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #f1f5f9;
  color: #0f172a;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bento-tag {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 9999px;
}

.bento-tag.tag-miniapp {
  background: rgba(7, 193, 96, 0.1);
  color: #07c160;
  border: 1px solid rgba(7, 193, 96, 0.2);
}

.bento-tag.tag-android {
  background: #f1f5f9;
  color: #0f172a;
  border: 1px solid #e2e8f0;
}

.bento-tag.tag-both {
  background: rgba(2, 132, 199, 0.08);
  color: #0284c7;
  border: 1px solid rgba(2, 132, 199, 0.18);
}

.bento-title {
  font-size: 1.12rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 10px;
}

.bento-desc {
  font-size: 0.88rem;
  line-height: 1.62;
  color: #64748b;
}

/* 真机展示区域 */
.showcase-section {
  padding: 50px 0 70px;
  text-align: center;
}

.mockup-tab-pills {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 9999px;
  margin-bottom: 40px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}

.tab-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 0.86rem;
  font-weight: 600;
  border-radius: 9999px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
  transition: background 0.2s ease;
}

.tab-pill.active {
  background: #0f172a;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.15);
}

.tab-pill.active .tab-dot {
  background: #38bdf8;
}

.mockup-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 60px;
  max-width: 960px;
  margin: 0 auto;
  text-align: left;
}

/* 手机壳模型 */
.phone-frame {
  width: 320px;
  height: 670px;
  background: #000000;
  border-radius: 46px;
  padding: 10px;
  box-shadow:
    0 24px 64px -12px rgba(15, 23, 42, 0.22),
    0 0 0 2px rgba(255, 255, 255, 0.15),
    inset 0 0 0 2px rgba(255, 255, 255, 0.2);
  position: relative;
  flex-shrink: 0;
}

.phone-notch {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  width: 90px;
  height: 22px;
  background: #000000;
  border-radius: 12px;
  z-index: 20;
}

.phone-screen {
  width: 100%;
  height: 100%;
  border-radius: 38px;
  overflow: hidden;
  background: #ffffff;
  position: relative;
}

.screen-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top center;
  display: block;
}

.showcase-notes {
  flex: 1;
  max-width: 440px;
}

.note-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  padding: 26px;
  box-shadow: 0 4px 20px -4px rgba(0, 0, 0, 0.04);
  margin-bottom: 24px;
}

.note-tag {
  font-size: 0.74rem;
  font-weight: 700;
  color: #0284c7;
  text-transform: uppercase;
  margin-bottom: 8px;
  letter-spacing: 0.02em;
}

.note-title {
  font-size: 1.35rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 12px;
}

.note-text {
  font-size: 0.92rem;
  line-height: 1.65;
  color: #475569;
}

.note-meta-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 16px 20px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.84rem;
  gap: 12px;
}

.meta-label {
  color: #64748b;
  font-weight: 500;
  flex-shrink: 0;
}

.meta-val {
  color: #0f172a;
  font-weight: 600;
  text-align: right;
}

/* 双端能力对照表 */
.compare-section {
  padding: 40px 0 70px;
  text-align: center;
}

.compare-table-wrap {
  max-width: 780px;
  margin: 0 auto;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 22px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
  text-align: left;
}

.compare-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}

.compare-table thead th {
  background: #f8fafc;
  padding: 14px 20px;
  font-size: 0.85rem;
  font-weight: 700;
  color: #0f172a;
  text-align: center;
  border-bottom: 1px solid #e2e8f0;
}

.compare-table thead th.col-name {
  text-align: left;
}

.compare-table thead th.col-platform {
  text-align: center;
}

.th-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.compare-table thead th.col-platform .th-label svg {
  color: #07c160;
}

.compare-table thead th.col-platform:last-of-type .th-label svg {
  color: #0f172a;
}

.compare-table tbody td {
  padding: 13px 20px;
  border-bottom: 1px solid #f1f5f9;
  text-align: center;
  color: #334155;
}

.compare-table tbody tr:last-child td {
  border-bottom: none;
}

.compare-table tbody tr:hover td {
  background: #fafcfe;
}

.compare-table td.col-name {
  text-align: left;
  font-weight: 600;
  color: #0f172a;
  width: 33.4%;
}

.cell-yes {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #07c160;
  font-weight: 600;
}

.cell-no {
  color: #cbd5e1;
}

.cell-text {
  font-size: 0.82rem;
  color: #64748b;
}

/* Footer */
.landing-footer {
  border-top: 1px solid #e2e8f0;
  padding: 30px 24px 40px;
  background: #ffffff;
}

.footer-inner {
  max-width: 1120px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}

.footer-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.footer-name {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}

.footer-slogan {
  font-size: 0.82rem;
  color: #64748b;
}

.footer-copy {
  font-size: 0.8rem;
  color: #94a3b8;
  display: flex;
  align-items: center;
  gap: 8px;
}

.footer-dot {
  color: #cbd5e1;
}

/* 扫码弹窗 */
.qr-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.qr-modal-card {
  background: #ffffff;
  border-radius: 24px;
  padding: 32px 28px;
  width: 320px;
  text-align: center;
  position: relative;
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.18);
}

.modal-close-btn {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: none;
  background: #f1f5f9;
  color: #475569;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
}

.modal-desc {
  font-size: 0.84rem;
  color: #64748b;
  margin-bottom: 18px;
}

.modal-qr-box {
  width: 200px;
  height: 200px;
  margin: 0 auto 16px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.modal-qr-img {
  width: 100%;
  height: 100%;
  display: block;
}

.modal-footer-tip {
  font-size: 0.78rem;
  color: #94a3b8;
}

/* 移动端响应式 */
@media (max-width: 860px) {
  .nav-links {
    display: none;
  }

  .hero-title {
    font-size: 2.1rem;
  }

  .access-grid {
    grid-template-columns: 1fr;
  }

  .bento-grid {
    grid-template-columns: 1fr;
  }

  .mockup-stage {
    flex-direction: column;
    align-items: center;
    gap: 36px;
  }

  .showcase-notes {
    max-width: 100%;
  }

  .compare-table-wrap {
    overflow-x: auto;
  }

  .compare-table {
    min-width: 560px;
  }

  .footer-inner {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
}

@media (max-width: 1080px) and (min-width: 861px) {
  .bento-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>

<style>
/* 全局平滑滚动（锚点导航） */
html {
  scroll-behavior: smooth;
}
</style>
