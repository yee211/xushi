<script setup>
import { days } from '../utils/schedule.js';

defineProps({
  open: { type: Boolean, default: false },
  course: { type: Object, default: null },
  week: { type: Number, required: true },
  form: { type: Object, required: true },
  existing: { type: Boolean, default: false },
});

const emit = defineEmits(['close', 'save', 'cancel-adjustment']);
</script>

<template>
  <div v-if="open" class="backdrop nested-modal-backdrop" @click.self="emit('close')">
    <form class="modal" @submit.prevent="emit('save')">
      <div class="modal-head">
        <div>
          <p>第 {{ week }} 周临时安排</p>
          <h2>{{ course?.name }} · 调课</h2>
        </div>
        <button type="button" class="icon" @click="emit('close')">×</button>
      </div>
      <p class="adjustment-hint">只改变当前周，其他周仍按原课程时间上课。</p>
      <div class="fields three">
        <label>
          星期
          <select v-model="form.weekday">
            <option v-for="(day, i) in days" :key="day" :value="i + 1">{{ day }}</option>
          </select>
        </label>
        <label>
          开始
          <select v-model="form.start_section">
            <option v-for="n in 12" :key="n" :value="n">第{{ n }}节</option>
          </select>
        </label>
        <label>
          结束
          <select v-model="form.end_section">
            <option v-for="n in 12" :key="n" :value="n">第{{ n }}节</option>
          </select>
        </label>
      </div>
      <label>
        新教室
        <input v-model="form.room" maxlength="40" placeholder="可保持原教室">
      </label>
      <div class="modal-actions">
        <button v-if="existing" type="button" class="danger uiverse-button" @click="emit('cancel-adjustment')">撤销调课</button>
        <span></span>
        <button class="uiverse-button" type="button" @click="emit('close')">取消</button>
        <button class="primary uiverse-button" type="submit">保存调课</button>
      </div>
    </form>
  </div>
</template>
