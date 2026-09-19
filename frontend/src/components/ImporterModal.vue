<script setup>
defineProps({
  open: { type: Boolean, default: false },
  importing: { type: Boolean, default: false },
  importSetup: { type: Boolean, default: false },
  importSource: { type: String, default: 'excel' },
  importFile: { type: Object, default: null },
  importStartDate: { type: String, default: '' },
  importEndDate: { type: String, default: '' },
  importError: { type: String, default: '' },
  importEngine: { type: String, default: '' },
  importElapsed: { type: Number, default: 0 },
});

const emit = defineEmits([
  'close',
  'update:importStartDate',
  'update:importEndDate',
  'start-import',
]);
</script>

<template>
  <div v-if="open" class="backdrop" @click.self="emit('close')">
    <section class="modal">
      <div class="modal-head">
        <div>
          <p>{{ importSource === 'academic' ? '教务系统导入' : '导入课表' }}</p>
          <h2>{{ importing ? '正在识别' : importSetup ? '设置学期日期' : '确认识别结果' }}</h2>
        </div>
        <button type="button" class="icon" @click="emit('close')">×</button>
      </div>

      <div v-if="importing" class="scanner">
        <i></i>
        <span>
          {{
            importSource === 'academic'
              ? (importElapsed < 3 ? '正在提取教务网页表格…' : importElapsed < 25 ? `正在智能识别课程… ${importElapsed} 秒` : 'AI 正在处理复杂课程表…')
              : (importElapsed < 5 ? '正在安全读取工作簿…' : importElapsed < 45 ? `正在识别课程信息… ${importElapsed} 秒` : 'AI 响应较慢，正在准备本地解析兜底…')
          }}
        </span>
      </div>

      <div v-else-if="importSetup" class="import-setup">
        <p class="import-file">已选择：{{ importFile?.name }}</p>
        <div class="fields">
          <label>
            学期开始日期
            <input
              :value="importStartDate"
              type="date"
              required
              @input="emit('update:importStartDate', $event.target.value)"
            >
          </label>
          <label>
            学期结束日期
            <input
              :value="importEndDate"
              type="date"
              required
              @input="emit('update:importEndDate', $event.target.value)"
            >
          </label>
        </div>
        <p v-if="importError" class="import-inline-error">{{ importError }}</p>
        <p class="import-help">
          仅支持 Excel 课表（.xlsx / .xlsm / .xls），优先由 AI 解析课程明细，失败时自动回退本地解析。系统会根据开始日期和结束日期，自动推算每周日期；课表上方会显示当前周每天的日期。
        </p>
        <div class="modal-actions">
          <span></span>
          <button class="uiverse-button" type="button" @click="emit('close')">取消</button>
          <button type="button" class="primary uiverse-button" @click="emit('start-import')">开始识别</button>
        </div>
      </div>

      <div v-else-if="importError" class="empty error">{{ importError }}</div>

      <div v-else class="empty">
        <p>{{ importSource === 'academic' ? '未能从教务系统页面中识别出课程，请确认已进入个人课表页面。' : '未能从该 Excel 中识别出课程，请确认文件包含课程明细表。' }}</p>
        <small v-if="importEngine">解析引擎：{{ importEngine }}</small>
      </div>
    </section>
  </div>
</template>
