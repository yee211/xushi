<script setup>
import { ref } from 'vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  currentBg: { type: String, default: 'default' },
});

const emit = defineEmits(['close', 'apply']);

// 极简温润背景预设（与整体纯净极简风完美契合）
const PRESETS = [
  { id: 'default', label: '极简纯白', hex: '#FFFFFF' },
  { id: 'cream',   label: '温润米白', hex: '#FAF8F5' },
  { id: 'stone',   label: '中性暖灰', hex: '#F4F3F0' },
  { id: 'paper',   label: '轻古书页', hex: '#F9F6F0' },
  { id: 'lavender',label: '淡紫雅韵', hex: '#F6F4FA' },
  { id: 'sky',     label: '澄澈晴空', hex: '#F0F5FA' },
  { id: 'mint',    label: '清新薄荷', hex: '#F1F7F4' },
  { id: 'peach',   label: '柔暖杏桃', hex: '#FAF3EE' },
  { id: 'rose',    label: '山茶微粉', hex: '#FBF2F4' },
  { id: 'slate',   label: '静谧青灰', hex: '#F1F3F5' },
];

function selectPreset(id, hex) {
  emit('apply', id, hex);
  emit('close');
}
</script>

<template>
  <div v-if="open" class="backdrop nested-modal-backdrop bg-picker-backdrop" @click.self="emit('close')">
    <section class="modal bg-picker-modal" role="dialog" aria-modal="true" aria-labelledby="bg-picker-title">
      <!-- 头部 -->
      <div class="bg-picker-header">
        <div>
          <h3 id="bg-picker-title" class="bg-picker-title">自定义背景</h3>
          <p class="bg-picker-sub">选择整体界面的主色调风格</p>
        </div>
        <button type="button" class="bg-close-btn" aria-label="关闭" @click="emit('close')">×</button>
      </div>

      <!-- 预设色块网格 -->
      <div class="bg-presets-grid">
        <button
          v-for="p in PRESETS"
          :key="p.id"
          type="button"
          class="bg-preset-card"
          :class="{ 'is-selected': currentBg === p.id }"
          @click="selectPreset(p.id, p.hex)"
        >
          <div class="bg-swatch" :style="{ backgroundColor: p.hex }">
            <span v-if="currentBg === p.id" class="swatch-check">✓</span>
          </div>
          <span class="bg-preset-name">{{ p.label }}</span>
        </button>
      </div>

      <!-- 底部关闭按钮 -->
      <div class="bg-picker-actions">
        <button type="button" class="bg-cancel-btn" @click="emit('close')">完成</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.bg-picker-backdrop {
  z-index: 80 !important;
  background: rgba(15, 23, 42, 0.38) !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  padding: 16px !important;
}

.bg-picker-modal {
  width: min(420px, 92vw);
  max-height: min(80vh, 560px);
  background: #FFFFFF !important;
  border-radius: 24px;
  border: 1px solid var(--minimal-border, #E5E7EB);
  box-shadow: 0 20px 48px -8px rgba(15, 23, 42, 0.18);
  display: flex;
  flex-direction: column;
  padding: 20px;
  overflow: hidden;
  box-sizing: border-box;
}

.bg-picker-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.bg-picker-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--minimal-text-primary, #111827);
  margin: 0;
  letter-spacing: -0.01em;
}

.bg-picker-sub {
  font-size: 0.78rem;
  color: var(--minimal-text-secondary, #8A8F99);
  margin: 3px 0 0;
}

.bg-close-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: none;
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-secondary, #8A8F99);
  font-size: 1.15rem;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.bg-close-btn:hover {
  background: #E5E7EB;
  color: var(--minimal-text-primary, #111827);
}

/* 预设色块网格：5 列布局 */
.bg-presets-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px 8px;
  padding: 4px 2px 14px;
  overflow-y: auto;
}

@media (max-width: 380px) {
  .bg-presets-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

.bg-preset-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px;
  border-radius: 14px;
  transition: transform 0.15s ease;
}

.bg-preset-card:hover { transform: scale(1.05); }
.bg-preset-card:active { transform: scale(0.95); }

.bg-swatch {
  width: 46px;
  height: 46px;
  border-radius: 14px;
  border: 1.5px solid rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: all 0.15s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.bg-preset-card.is-selected .bg-swatch {
  border-color: #0f172a;
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.15);
}

.swatch-check {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}

.bg-preset-name {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--minimal-text-secondary, #8A8F99);
  text-align: center;
  white-space: nowrap;
}

.bg-preset-card.is-selected .bg-preset-name {
  color: var(--minimal-text-primary, #111827);
  font-weight: 700;
}

/* 底部操作 */
.bg-picker-actions {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--minimal-border, #E5E7EB);
  flex-shrink: 0;
}

.bg-cancel-btn {
  width: 100%;
  padding: 10px;
  border-radius: var(--minimal-radius-pill, 9999px);
  border: 1px solid var(--minimal-border, #E5E7EB);
  background: var(--minimal-bg-surface, #F3F4F6);
  color: var(--minimal-text-primary, #111827);
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.bg-cancel-btn:hover {
  background: #E5E7EB;
}
</style>
