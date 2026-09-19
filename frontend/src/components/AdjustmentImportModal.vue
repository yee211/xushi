<script setup>
import { computed } from 'vue';
import { days } from '../utils/schedule.js';

const props = defineProps({
  open: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  applying: { type: Boolean, default: false },
  filename: { type: String, default: '' },
  error: { type: String, default: '' },
  items: { type: Array, default: () => [] },
});
const emit = defineEmits(['close', 'apply']);
const selectedCount = computed(() => props.items.filter(item => item.status === 'matched' && item.selected).length);
function position(day, start, end, room) {
  return `${days[day - 1] || '未知'} ${start}-${end}节${room ? ` · ${room}` : ''}`;
}
</script>

<template>
  <div v-if="open" class="backdrop" @click.self="!loading && !applying && emit('close')">
    <section class="modal adjustment-import-modal">
      <div class="modal-head">
        <div><p>AI 批量识别</p><h2>调课通知</h2></div>
        <button type="button" class="icon" :disabled="loading || applying" @click="emit('close')">×</button>
      </div>
      <p class="adjustment-privacy">通知图片将发送至你配置的阿里云百炼模型解析，服务端不会保存原图。</p>
      <p v-if="filename" class="import-file">{{ filename }}</p>
      <div v-if="loading" class="adjustment-loading">正在识别并匹配当前课表…</div>
      <p v-else-if="error" class="import-inline-error">{{ error }}</p>
      <div v-else-if="items.length" class="adjustment-results">
        <label v-for="(item, index) in items" :key="index" class="adjustment-result" :class="item.status">
          <input v-if="item.status === 'matched'" v-model="item.selected" type="checkbox">
          <span v-else class="result-warning">!</span>
          <span class="result-content">
            <b>{{ item.matched_course_name || item.course_name }}</b>
            <small>第 {{ item.week }} 周 · {{ item.teacher || '教师未注明' }}</small>
            <span>{{ position(item.old_weekday, item.old_start_section, item.old_end_section, item.old_room) }}</span>
            <i>↓</i>
            <span>{{ position(item.new_weekday, item.new_start_section, item.new_end_section, item.new_room) }}</span>
            <em v-if="item.status !== 'matched'">{{ item.status === 'ambiguous' ? '匹配到多门课程，请手动调课' : '当前课表中未找到原课程' }}</em>
          </span>
        </label>
      </div>
      <div class="modal-actions">
        <span></span>
        <button class="uiverse-button" type="button" :disabled="loading || applying" @click="emit('close')">取消</button>
        <button class="primary uiverse-button" type="button" :disabled="!selectedCount || loading || applying" @click="emit('apply')">
          {{ applying ? '正在应用…' : `应用 ${selectedCount} 条` }}
        </button>
      </div>
    </section>
  </div>
</template>
