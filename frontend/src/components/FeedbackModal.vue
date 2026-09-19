<script setup>
import { ref, watch } from 'vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
});

const emit = defineEmits(['close', 'submit']);

const categories = [
  { id: 'import', label: '课表导入', desc: 'Excel导入识别异常' },
  { id: 'schedule', label: '课程显示', desc: '课程/周次显示错误' },
  { id: 'adjustment', label: '调课相关', desc: '通知识别/调课改动' },
  { id: 'other', label: '其他建议', desc: '功能建议/界面吐槽' },
];

const form = ref({
  category: 'import',
  description: '',
  contact: '',
});

watch(() => props.open, val => {
  if (val) {
    form.value = {
      category: 'import',
      description: '',
      contact: '',
    };
  }
});

function onSubmit() {
  if (!form.value.description.trim()) return;
  emit('submit', {
    category: form.value.category,
    description: form.value.description.trim(),
    contact: form.value.contact.trim(),
  });
}
</script>

<template>
  <div v-if="open" class="backdrop" @click.self="!submitting && emit('close')">
    <form class="modal feedback-modal glass" @submit.prevent="onSubmit">
      <div class="modal-head">
        <div>
          <p>问题与建议</p>
          <h2>反馈中心</h2>
        </div>
        <button type="button" class="icon" :disabled="submitting" @click="emit('close')">×</button>
      </div>

      <div class="feedback-categories">
        <label
          v-for="cat in categories"
          :key="cat.id"
          class="category-option"
          :class="{ active: form.category === cat.id }"
        >
          <input
            v-model="form.category"
            type="radio"
            name="feedback-cat"
            :value="cat.id"
            class="sr-only"
          >
          <b>{{ cat.label }}</b>
          <small>{{ cat.desc }}</small>
        </label>
      </div>

      <label class="feedback-field">
        <span>问题或建议描述 <b class="required">*</b></span>
        <textarea
          v-model="form.description"
          rows="4"
          required
          maxlength="1000"
          placeholder="请详细描述你遇到的问题或改进建议，例如：导入某学校课表时提示格式错误…"
        ></textarea>
      </label>

      <label class="feedback-field">
        <span>联系方式 <small class="text-muted">(选填，便于向你同步处理进展)</small></span>
        <input
          v-model="form.contact"
          type="text"
          maxlength="80"
          placeholder="QQ / 微信 / 邮箱"
        >
      </label>

      <div class="modal-actions">
        <button type="button" class="uiverse-button" :disabled="submitting" @click="emit('close')">取消</button>
        <span></span>
        <button type="submit" class="primary uiverse-button" :disabled="submitting || !form.description.trim()">
          {{ submitting ? '正在提交…' : '提交反馈' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.feedback-modal {
  max-width: 480px;
}
.feedback-categories {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin: 12px 0 16px;
}
.category-option {
  display: flex;
  flex-direction: column;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.2s ease;
}
html[data-bg="night"] .category-option {
  background: rgba(30, 41, 59, 0.45);
  border-color: rgba(255, 255, 255, 0.1);
}
.category-option b {
  font-size: 0.9rem;
  color: #1e293b;
}
html[data-bg="night"] .category-option b {
  color: #f1f5f9;
}
.category-option small {
  font-size: 0.74rem;
  color: #64748b;
  margin-top: 2px;
}
.category-option.active {
  background: rgba(14, 165, 233, 0.12);
  border-color: rgba(14, 165, 233, 0.45);
}
.category-option.active b {
  color: #0284c7;
}
html[data-bg="night"] .category-option.active {
  background: rgba(14, 165, 233, 0.2);
  border-color: rgba(56, 189, 248, 0.5);
}
html[data-bg="night"] .category-option.active b {
  color: #38bdf8;
}
.feedback-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.feedback-field span {
  font-size: 0.84rem;
  font-weight: 600;
  color: #334155;
}
html[data-bg="night"] .feedback-field span {
  color: #cbd5e1;
}
.required {
  color: #e11d48;
}
.feedback-field textarea,
.feedback-field input {
  width: 100%;
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 0.88rem;
  box-sizing: border-box;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}
</style>
