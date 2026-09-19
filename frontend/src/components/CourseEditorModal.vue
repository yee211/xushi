<script setup>
import { days } from '../utils/schedule.js';

defineProps({
  open: { type: Boolean, default: false },
  form: { type: Object, required: true },
});

const emit = defineEmits(['close', 'save', 'delete']);
</script>

<template>
  <div v-if="open" class="backdrop nested-modal-backdrop" @click.self="emit('close')">
    <form class="modal course-editor-modal" @submit.prevent="emit('save')">
      <div class="modal-head">
        <div>
          <p>{{ form.id ? '调整课程' : '新建课程' }}</p>
          <h2>{{ form.id ? '编辑课程' : '添加到课表' }}</h2>
        </div>
        <button type="button" class="icon" @click="emit('close')">×</button>
      </div>
      <label>
        课程名称
        <input v-model="form.name" required maxlength="80" placeholder="例如：计算机网络">
      </label>
      <div class="fields">
        <label>
          教师
          <input v-model="form.teacher" maxlength="40" placeholder="选填">
        </label>
        <label>
          教室
          <input v-model="form.room" maxlength="40" placeholder="选填">
        </label>
      </div>
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
        上课周次
        <input v-model="form.weeks" placeholder="1-16，或 1,3,5">
      </label>
      <label>
        课程颜色
        <input v-model="form.color" class="color" type="color">
      </label>
      <div class="modal-actions">
        <button
          v-if="form.id"
          type="button"
          class="danger uiverse-button"
          @click="emit('delete')"
        >
          删除
        </button>
        <span></span>
        <button class="uiverse-button" type="button" @click="emit('close')">取消</button>
        <button class="primary uiverse-button" type="submit">保存</button>
      </div>
    </form>
  </div>
</template>
