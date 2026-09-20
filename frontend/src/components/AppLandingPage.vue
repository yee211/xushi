<script setup>
import { computed, onMounted, ref } from 'vue';
import { appApi } from '../api/index.js';
import { CURRENT_VERSION_CODE, CURRENT_VERSION_NAME } from '../utils/version.js';

// 默认兜底版本信息
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
const modalType = ref('wechat'); // 'wechat' | 'android'
const copySuccess = ref(false);

const qrCodeUrl = computed(() => {
  const url = encodeURIComponent(versionData.value.downloadUrl);
  return `https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=${url}`;
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
    // 降级使用静态配置
  }
}

function openModal(type) {
  modalType.value = type;
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
      setTimeout(() => { copySuccess.value = false; }, 2000);
    }
  } catch {}
}

onMounted(() => {
  fetchVersion();
});
</script>

<template>
  <div class="landing-page">
    <!-- 顶部极简导航 -->
    <header class="landing-header">
      <div class="header-content">
        <div class="brand">
          <img src="/app-icon.png" alt="序时 Logo" class="brand-logo" />
          <div class="brand-info">
            <span class="brand-title">序时</span>
            <span class="brand-tag">极简智能课表</span>
          </div>
        </div>
        <div class="header-links">
          <button class="nav-btn btn-ghost" @click="openModal('wechat')">微信小程序</button>
          <button class="nav-btn btn-primary" @click="openModal('android')">获取 Android 版</button>
        </div>
      </div>
    </header>

    <!-- 主体内容 -->
    <main class="landing-body">
      <!-- Hero 区域 -->
      <section class="hero-section">
        <div class="hero-badge">
          <span class="sparkle">✦</span>
          <span>一套后端驱动 · 微信小程序与 Android 双端互通</span>
        </div>
        <h1 class="hero-heading">
          课表装进微信，<br />
          也装进每一台 Android。
        </h1>
        <p class="hero-description">
          序时是为大学生打造的纯粹课表工具。微信小程序免安装即开即用，Android 原生端支持高校教务一键直连。
          全周作息一目了然，智能排版告别繁杂。
        </p>

        <div class="hero-buttons">
          <button class="cta-button cta-wechat" @click="openModal('wechat')">
            <svg class="icon" viewBox="0 0 24 24" fill="currentColor">
              <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
              <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
            </svg>
            <span>使用微信小程序</span>
          </button>
          <button class="cta-button cta-android" @click="handleDownload('primary')">
            <svg class="icon" viewBox="0 0 24 24" fill="currentColor">
              <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
              <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
            </svg>
            <span>下载 Android APK (v{{ versionData.versionName }})</span>
          </button>
        </div>
      </section>

      <!-- 双端极简入口卡片 -->
      <section class="platforms-section">
        <div class="platform-grid">
          <!-- 微信小程序卡片 -->
          <div class="platform-card wechat-theme">
            <div class="card-header">
              <div class="icon-avatar wx-avatar">
                <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
                  <path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89 1.08 3.56 2.78 4.66l-.7 2.1 2.45-1.23c.86.24 1.78.37 2.74.37h.36a6.08 6.08 0 0 1-.25-1.73c0-3.31 3.02-6 6.74-6 .24 0 .47.01.7.03C16.22 5.75 13.14 4 9.5 4zM7.3 8.6a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8zm4.4 0a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8z"/>
                  <path d="M22 14.17c0-2.74-2.69-4.96-6-4.96s-6 2.22-6 4.96 2.69 4.96 6 4.96c.72 0 1.42-.1 2.06-.29l2.24 1.12-.66-1.99A4.62 4.62 0 0 0 22 14.17zm-8.06-.58a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64zm4.12 0a.82.82 0 1 1 0-1.64.82.82 0 0 1 0 1.64z"/>
                </svg>
              </div>
              <div class="card-titles">
                <span class="badge-mini wx-badge">微信生态</span>
                <h3>微信小程序</h3>
                <p>免安装 · 微信内即开即用</p>
              </div>
            </div>

            <ul class="feature-bullets">
              <li>
                <span class="bullet-dot wx-dot"></span>
                <span><strong>静默登录</strong>：无需注册与密码，微信账号直接关联</span>
              </li>
              <li>
                <span class="bullet-dot wx-dot"></span>
                <span><strong>聊天查课</strong>：微信内向智能 Agent 随口提问日程</span>
              </li>
              <li>
                <span class="bullet-dot wx-dot"></span>
                <span><strong>云端互通</strong>：与 Android 端共享同一份课表数据</span>
              </li>
            </ul>

            <div class="card-action">
              <button class="btn-card-action btn-wx" @click="openModal('wechat')">
                <span>扫码或搜索使用</span>
                <span class="arrow">→</span>
              </button>
            </div>
          </div>

          <!-- Android 原生客户端卡片 -->
          <div class="platform-card android-theme">
            <div class="card-header">
              <div class="icon-avatar android-avatar">
                <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
                  <path d="M17 6h-2V5h1.37c.24-.62.32-1.3.13-2.02A2.73 2.73 0 0 0 14.86 1c-.83 0-1.55.37-2.06.94A2.73 2.73 0 0 0 10.74 1 2.73 2.73 0 0 0 8.1 2.98c-.19.72-.11 1.4.13 2.02H7c-.55 0-1 .45-1 1v3h12V7c0-.55-.45-1-1-1zM10.74 4.25c-.69 0-1.25-.56-1.25-1.25S10.05 1.75 10.74 1.75s1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm2.52 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/>
                  <path d="M6 11v10.5c0 .83.67 1.5 1.5 1.5h2c.28 0 .5-.22.5-.5V19h2v3.5c0 .28.22.5.5.5h2c.83 0 1.5-.67 1.5-1.5V11H6zM3.5 10c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-5c0-.83-.67-1.5-1.5-1.5zm17 0c-.83 0-1.5.67-1.5 1.5v5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-5c0-.83-.67-1.5-1.5-1.5z"/>
                </svg>
              </div>
              <div class="card-titles">
                <span class="badge-mini android-badge">v{{ versionData.versionName }} · 约 12MB</span>
                <h3>Android 原生客户端</h3>
                <p>原生体验 · 高校教务直连导入</p>
              </div>
            </div>

            <ul class="feature-bullets">
              <li>
                <span class="bullet-dot android-dot"></span>
                <span><strong>教务直连</strong>：内置原生 WebView 一键导入强智等教务</span>
              </li>
              <li>
                <span class="bullet-dot android-dot"></span>
                <span><strong>优雅排版</strong>：2 节连堂与 4 节大课自动合并，拒绝碎卡片</span>
              </li>
              <li>
                <span class="bullet-dot android-dot"></span>
                <span><strong>个性壁纸</strong>：沉浸式视频动态壁纸与离线缓存支持</span>
              </li>
            </ul>

            <div class="card-action double-action">
              <button class="btn-card-action btn-android" @click="handleDownload('primary')">
                <span>直接下载 APK</span>
                <span class="arrow">↓</span>
              </button>
              <button class="btn-card-sub" @click="openModal('android')">
                <span>扫码下载</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- 核心亮点微网格（4个极简卡片） -->
      <section class="features-section">
        <h2 class="section-title">核心特性 · 专为课表打造</h2>
        <div class="bento-grid">
          <div class="bento-item">
            <div class="bento-icon">🏫</div>
            <h4>教务系统直连</h4>
            <p>原生 WebView 登录高校教务系统，请求拦截毫秒级捕获课表，告别手动导出与复杂抓包。</p>
          </div>
          <div class="bento-item">
            <div class="bento-icon">🔄</div>
            <h4>智能调课中心</h4>
            <p>上传调课通知截图，AI 自动提取调整前后周次、节次与地点，一键批量确认与变更追溯。</p>
          </div>
          <div class="bento-item">
            <div class="bento-icon">💬</div>
            <h4>微信 Agent 问课</h4>
            <p>在微信聊天窗口直接提问“明天有什么课”，智能 Agent 意图识别，随时随地秒级应答。</p>
          </div>
          <div class="bento-item">
            <div class="bento-icon">📊</div>
            <h4>Excel 语义解析</h4>
            <p>支持多格式课表文件导入，确定性规则结合大模型语义智能兜底，非标表格轻松搞定。</p>
          </div>
        </div>
      </section>
    </main>

    <!-- 极简页脚 -->
    <footer class="landing-footer">
      <div class="footer-inner">
        <p>序时 (XuShi) · 极简多端大学课表</p>
        <div class="footer-links">
          <a href="/admin" target="_blank">管理后台</a>
          <span class="sep">·</span>
          <a href="https://api.tanzeng.xyz/downloads/%E5%BA%8F%E6%97%B6_v2.4.7.apk" target="_blank">APK 直链</a>
          <span class="sep">·</span>
          <span>纯粹无广告</span>
        </div>
      </div>
    </footer>

    <!-- 极简扫码弹窗 -->
    <div v-if="showModal" class="modal-backdrop" @click="showModal = false">
      <div class="modal-container" @click.stop>
        <button class="modal-close" @click="showModal = false">✕</button>

        <!-- 微信小程序弹窗 -->
        <template v-if="modalType === 'wechat'">
          <div class="modal-header">
            <div class="modal-icon-badge wx-badge">微信</div>
            <h3>微信小程序</h3>
            <p>免安装 · 微信内即开即用</p>
          </div>
          <div class="modal-content">
            <div class="wx-search-hint">
              <span class="hint-label">方式 1 · 微信搜索</span>
              <div class="search-box">
                <span>🔍 搜索 <strong>序时课表</strong></span>
              </div>
            </div>
            <div class="divider-text">或</div>
            <div class="wx-search-hint">
              <span class="hint-label">方式 2 · 扫码直达</span>
              <p class="sub-hint">打开微信「扫一扫」快速体验</p>
              <div class="qr-placeholder wx-qr-card">
                <img src="/app-icon.png" alt="序时" class="miniapp-avatar" />
                <span class="miniapp-name">序时课表</span>
                <span class="miniapp-sub">微信小程序</span>
              </div>
            </div>
          </div>
        </template>

        <!-- Android 下载弹窗 -->
        <template v-else>
          <div class="modal-header">
            <div class="modal-icon-badge android-badge">APK</div>
            <h3>下载 Android 版</h3>
            <p>版本 v{{ versionData.versionName }} · 约 12MB</p>
          </div>
          <div class="modal-content">
            <div class="qr-box">
              <img :src="qrCodeUrl" alt="下载二维码" class="qr-image" />
              <p class="qr-tip">使用手机浏览器或相机扫描二维码下载</p>
            </div>
            <div class="modal-actions">
              <button class="btn-modal-primary" @click="handleDownload('primary')">直接下载 APK</button>
              <button class="btn-modal-ghost" @click="copyLink">
                {{ copySuccess ? '已复制链接！' : '复制下载链接' }}
              </button>
            </div>
            <div v-if="versionData.changelog?.length" class="modal-changelog">
              <span class="changelog-title">最近更新：</span>
              <ul>
                <li v-for="(log, i) in versionData.changelog.slice(0, 3)" :key="i">{{ log }}</li>
              </ul>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 样式设计：高对比度、纯粹克制、现代科技感 */
.landing-page {
  min-height: 100vh;
  background-color: #0b0f19;
  background-image: 
    radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.12) 0px, transparent 50%),
    radial-gradient(at 100% 100%, rgba(139, 92, 246, 0.1) 0px, transparent 50%);
  color: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
  display: flex;
  flex-direction: column;
}

/* 顶部导航 */
.landing-header {
  position: sticky;
  top: 0;
  z-index: 40;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  background: rgba(11, 15, 25, 0.8);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.header-content {
  max-width: 1080px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-logo {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
}
.brand-info {
  display: flex;
  flex-direction: column;
}
.brand-title {
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #fff;
}
.brand-tag {
  font-size: 0.72rem;
  color: #94a3b8;
}
.header-links {
  display: flex;
  align-items: center;
  gap: 10px;
}
.nav-btn {
  padding: 7px 16px;
  border-radius: 999px;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}
.btn-ghost {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
}
.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
}
.btn-primary {
  background: #3b82f6;
  color: #fff;
}
.btn-primary:hover {
  background: #2563eb;
  transform: translateY(-1px);
}

/* 主内容 */
.landing-body {
  flex: 1;
  max-width: 1080px;
  width: 100%;
  margin: 0 auto;
  padding: 50px 24px 70px;
  box-sizing: border-box;
}

/* Hero */
.hero-section {
  text-align: center;
  padding: 20px 0 50px;
}
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.25);
  padding: 5px 14px;
  border-radius: 999px;
  font-size: 0.82rem;
  color: #60a5fa;
  margin-bottom: 24px;
}
.sparkle {
  color: #93c5fd;
}
.hero-heading {
  font-size: 2.75rem;
  line-height: 1.25;
  font-weight: 800;
  letter-spacing: -0.03em;
  margin: 0 0 20px;
  background: linear-gradient(180deg, #ffffff 0%, #cbd5e1 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero-description {
  max-width: 620px;
  margin: 0 auto 36px;
  font-size: 1.05rem;
  line-height: 1.65;
  color: #94a3b8;
}
.hero-buttons {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  flex-wrap: wrap;
}
.cta-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 13px 26px;
  border-radius: 12px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}
.cta-button .icon {
  width: 18px;
  height: 18px;
}
.cta-wechat {
  background: #07c160;
  color: #ffffff;
}
.cta-wechat:hover {
  background: #06ad56;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(7, 193, 96, 0.3);
}
.cta-android {
  background: #2563eb;
  color: #ffffff;
}
.cta-android:hover {
  background: #1d4ed8;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(37, 99, 235, 0.3);
}

/* 双端卡片区 */
.platforms-section {
  margin-bottom: 60px;
}
.platform-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}
.platform-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  padding: 32px;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
}
.platform-card:hover {
  border-color: rgba(255, 255, 255, 0.18);
  transform: translateY(-3px);
  background: rgba(255, 255, 255, 0.05);
}
.card-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
}
.icon-avatar {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.wx-avatar {
  background: rgba(7, 193, 96, 0.15);
  color: #07c160;
}
.android-avatar {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}
.card-titles {
  display: flex;
  flex-direction: column;
}
.badge-mini {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  margin-bottom: 6px;
  width: fit-content;
}
.wx-badge {
  background: rgba(7, 193, 96, 0.2);
  color: #4ade80;
}
.android-badge {
  background: rgba(59, 130, 246, 0.2);
  color: #93c5fd;
}
.card-titles h3 {
  font-size: 1.35rem;
  font-weight: 700;
  margin: 0 0 4px;
  color: #fff;
}
.card-titles p {
  font-size: 0.88rem;
  color: #94a3b8;
  margin: 0;
}
.feature-bullets {
  list-style: none;
  padding: 0;
  margin: 0 0 32px;
  flex: 1;
}
.feature-bullets li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.92rem;
  color: #cbd5e1;
  margin-bottom: 12px;
}
.bullet-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.wx-dot { background: #07c160; }
.android-dot { background: #3b82f6; }

.card-action {
  margin-top: auto;
}
.double-action {
  display: flex;
  gap: 10px;
}
.btn-card-action {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 18px;
  border-radius: 10px;
  font-size: 0.92rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}
.btn-wx {
  background: rgba(7, 193, 96, 0.15);
  color: #4ade80;
  border: 1px solid rgba(7, 193, 96, 0.3);
}
.btn-wx:hover {
  background: #07c160;
  color: #fff;
}
.btn-android {
  background: #2563eb;
  color: #fff;
}
.btn-android:hover {
  background: #1d4ed8;
}
.btn-card-sub {
  padding: 12px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
  border: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 0.92rem;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-card-sub:hover {
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
}

/* 核心特性卡片 */
.features-section {
  padding-top: 20px;
}
.section-title {
  text-align: center;
  font-size: 1.45rem;
  font-weight: 700;
  margin: 0 0 32px;
  color: #e2e8f0;
}
.bento-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}
.bento-item {
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  padding: 22px 18px;
  transition: all 0.2s ease;
}
.bento-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.12);
}
.bento-icon {
  font-size: 1.6rem;
  margin-bottom: 12px;
}
.bento-item h4 {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0 0 8px;
  color: #fff;
}
.bento-item p {
  font-size: 0.82rem;
  line-height: 1.55;
  color: #94a3b8;
  margin: 0;
}

/* 页脚 */
.landing-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 28px 24px;
  margin-top: auto;
}
.footer-inner {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.84rem;
  color: #64748b;
  flex-wrap: wrap;
  gap: 12px;
}
.footer-inner p {
  margin: 0;
}
.footer-links {
  display: flex;
  align-items: center;
  gap: 10px;
}
.footer-links a {
  color: #94a3b8;
  text-decoration: none;
  transition: color 0.2s;
}
.footer-links a:hover {
  color: #3b82f6;
}
.sep {
  color: #475569;
}

/* 弹窗 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(10px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 16px;
}
.modal-container {
  background: #151b28;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 20px;
  width: 100%;
  max-width: 380px;
  padding: 28px;
  position: relative;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
  box-sizing: border-box;
}
.modal-close {
  position: absolute;
  top: 18px;
  right: 18px;
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 4px;
}
.modal-close:hover {
  color: #fff;
}
.modal-header {
  text-align: center;
  margin-bottom: 24px;
}
.modal-icon-badge {
  display: inline-block;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
  margin-bottom: 10px;
}
.modal-header h3 {
  font-size: 1.3rem;
  font-weight: 700;
  margin: 0 0 4px;
  color: #fff;
}
.modal-header p {
  font-size: 0.85rem;
  color: #94a3b8;
  margin: 0;
}
.modal-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.wx-search-hint {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hint-label {
  font-size: 0.8rem;
  color: #94a3b8;
  font-weight: 600;
}
.search-box {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 12px;
  border-radius: 10px;
  text-align: center;
  font-size: 0.95rem;
  color: #e2e8f0;
}
.divider-text {
  text-align: center;
  color: #475569;
  font-size: 0.8rem;
  position: relative;
}
.divider-text::before,
.divider-text::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 40%;
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
}
.divider-text::before { left: 0; }
.divider-text::after { right: 0; }

.sub-hint {
  font-size: 0.82rem;
  color: #64748b;
  margin: 0 0 4px;
  text-align: center;
}
.wx-qr-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 18px;
  border-radius: 12px;
  background: rgba(7, 193, 96, 0.06);
  border: 1px solid rgba(7, 193, 96, 0.2);
}
.miniapp-avatar {
  width: 54px;
  height: 54px;
  border-radius: 14px;
  margin-bottom: 8px;
}
.miniapp-name {
  font-weight: 700;
  font-size: 1rem;
  color: #fff;
}
.miniapp-sub {
  font-size: 0.75rem;
  color: #4ade80;
}

.qr-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.qr-image {
  width: 170px;
  height: 170px;
  border-radius: 12px;
  background: #fff;
  padding: 8px;
}
.qr-tip {
  font-size: 0.8rem;
  color: #94a3b8;
  margin: 0;
  text-align: center;
}
.modal-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 6px;
}
.btn-modal-primary {
  background: #2563eb;
  color: #fff;
  padding: 11px;
  border-radius: 10px;
  font-weight: 600;
  font-size: 0.9rem;
  border: none;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-modal-primary:hover {
  background: #1d4ed8;
}
.btn-modal-ghost {
  background: rgba(255, 255, 255, 0.06);
  color: #cbd5e1;
  padding: 10px;
  border-radius: 10px;
  font-size: 0.85rem;
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
}
.btn-modal-ghost:hover {
  background: rgba(255, 255, 255, 0.12);
}
.modal-changelog {
  font-size: 0.78rem;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.03);
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.changelog-title {
  font-weight: 600;
  color: #cbd5e1;
}
.modal-changelog ul {
  margin: 4px 0 0;
  padding-left: 18px;
}
.modal-changelog li {
  margin-bottom: 2px;
}

/* 响应式适配 */
@media (max-width: 840px) {
  .hero-heading {
    font-size: 2.1rem;
  }
  .platform-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .bento-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 520px) {
  .landing-body {
    padding: 30px 16px 50px;
  }
  .header-content {
    padding: 12px 16px;
  }
  .hero-heading {
    font-size: 1.75rem;
  }
  .hero-description {
    font-size: 0.92rem;
  }
  .hero-buttons {
    flex-direction: column;
    width: 100%;
  }
  .cta-button {
    width: 100%;
    justify-content: center;
  }
  .bento-grid {
    grid-template-columns: 1fr;
  }
  .platform-card {
    padding: 22px 18px;
  }
  .footer-inner {
    flex-direction: column;
    text-align: center;
    gap: 8px;
  }
}
</style>
