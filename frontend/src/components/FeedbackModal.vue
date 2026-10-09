<script setup>
import { ref, watch } from 'vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
});

const emit = defineEmits(['close', 'submit']);

const form = ref({
  description: '',
  contact: '',
});

watch(() => props.open, val => {
  if (val) {
    form.value = {
      description: '',
      contact: '',
    };
  }
});

function onSubmit() {
  if (form.value.description.trim().length < 5) return;
  emit('submit', {
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

      <label class="feedback-field">
        <span>问题描述 <b class="required">*</b></span>
        <textarea
          v-model="form.description"
          rows="4"
          required
          minlength="5"
          maxlength="1000"
          placeholder="请描述你遇到的问题、操作过程或改进建议"
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
        <button type="submit" class="primary uiverse-button" :disabled="submitting || form.description.trim().length < 5">
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
</style>
