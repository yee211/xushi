<script setup>
defineProps({
  open: { type: Boolean, default: false },
});

const emit = defineEmits(['close', 'select-excel', 'select-academic']);
</script>

<template>
  <div v-if="open" class="backdrop" @click.self="emit('close')">
    <section class="modal import-source-modal">
      <div class="modal-head">
        <div>
          <p>导入课表</p>
          <h2>选择导入方式</h2>
        </div>
        <button type="button" class="icon" @click="emit('close')">×</button>
      </div>

      <div class="source-options">
        <!-- 选项 1: Excel 课表导入 -->
        <button
          type="button"
          class="source-card minimal-card"
          @click="emit('select-excel'); emit('close')"
        >
          <div class="source-card-icon excel-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10 9 9 9 8 9"/>
            </svg>
          </div>
          <div class="source-card-info">
            <div class="source-card-title-row">
              <span class="source-title">Excel 文件导入</span>
              <span class="source-tag">离线解析</span>
            </div>
            <p class="source-desc">支持 .xlsx / .xlsm / .xls 格式的课表，本地解析 + AI 兜底</p>
          </div>
          <span class="source-arrow">›</span>
        </button>

        <!-- 选项 2: 教务系统在线导入 -->
        <button
          type="button"
          class="source-card minimal-card highlight-academic"
          @click="emit('select-academic'); emit('close')"
        >
          <div class="source-card-icon academic-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
              <path d="M6 12v5c3 3 9 3 12 0v-5"/>
            </svg>
          </div>
          <div class="source-card-info">
            <div class="source-card-title-row">
              <span class="source-title">教务系统导入</span>
              <span class="source-tag academic-tag">实时同步</span>
            </div>
            <p class="source-desc">登录长沙工业学院教务网关，进入课表页一键提取导入</p>
          </div>
          <span class="source-arrow">›</span>
        </button>
      </div>

      <div class="modal-actions">
        <span></span>
        <button class="uiverse-button" type="button" @click="emit('close')">取消</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.import-source-modal {
  max-width: 440px;
}

.source-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 18px 0 20px 0;
}

.source-card {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 16px 14px;
  border-radius: 14px;
  text-align: left;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}

.source-card:hover {
  background: rgba(255, 255, 255, 0.09);
  border-color: rgba(255, 255, 255, 0.16);
  transform: translateY(-1px);
}

.source-card:active {
  transform: scale(0.98);
}

.highlight-academic {
  background: rgba(2, 132, 199, 0.07);
  border-color: rgba(2, 132, 199, 0.22);
}

.highlight-academic:hover {
  background: rgba(2, 132, 199, 0.12);
  border-color: rgba(2, 132, 199, 0.35);
}

.source-card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  flex-shrink: 0;
}

.excel-icon {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.academic-icon {
  background: rgba(2, 132, 199, 0.15);
  color: #0284c7;
}

.source-card-info {
  flex: 1;
  min-width: 0;
}

.source-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.source-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-color, #0f172a);
}

:root[data-bg="night"] .source-title {
  color: #f8fafc;
}

.source-tag {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.12);
  color: #64748b;
  font-weight: 500;
}

.academic-tag {
  background: rgba(2, 132, 199, 0.12);
  color: #0284c7;
}

:root[data-bg="night"] .academic-tag {
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.15);
}

.source-desc {
  font-size: 12px;
  line-height: 1.4;
  color: #64748b;
  margin: 0;
}

:root[data-bg="night"] .source-desc {
  color: #94a3b8;
}

.source-arrow {
  font-size: 20px;
  color: #94a3b8;
  opacity: 0.7;
  padding-right: 4px;
}
</style>
