<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import ConfirmModal from './ConfirmModal.vue';
import { useConfirmation } from '../composables/useConfirmation.js';
import { academicApi } from '../api/index.js';
import { formatWeeks } from '../utils/schedule.js';

const props = defineProps({ open: Boolean });
const emit = defineEmits(['close', 'synced']);
const keyword = ref('');
const bound = ref(null);
const lastSyncedAt = ref(null);
const students = ref([]);
const selected = ref(null);
const terms = ref([]);
const term = ref('');
const result = ref(null);
const busy = ref(false);
const error = ref('');
const notice = ref('');
const { confirmState, confirmAction, handleConfirmResult } = useConfirmation();
watch(() => props.open, open => { if (!open) handleConfirmResult(false); });
const searched = ref(false);
const backups = ref([]);
const recoveryExpanded = ref(false);
let revision = 0;
let pollTimer;
const syncStatus = ref('');
const stopPolling = () => { clearTimeout(pollTimer); syncStatus.value = ''; };
onBeforeUnmount(() => { ++revision; stopPolling(); });

async function followTask(task, current) {
  if (current !== revision || !props.open) return;
  if (task.state === 'succeeded') {
    if (localStorage.getItem('academicPendingTaskId') === task.id) localStorage.removeItem('academicPendingTaskId');
    busy.value = false;
    syncStatus.value = '';
    result.value = task.result;
    lastSyncedAt.value = task.result.last_synced_at;
    emit('synced', task.result);
    return;
  }
  if (task.state === 'failed') {
    if (localStorage.getItem('academicPendingTaskId') === task.id) localStorage.removeItem('academicPendingTaskId');
    busy.value = false;
    syncStatus.value = '';
    error.value = task.error || '同步失败，原课表已保留';
    return;
  }
  localStorage.setItem('academicPendingTaskId', task.id);
  busy.value = true;
  syncStatus.value = task.state === 'running' ? '正在从学校同步课表…' : '已加入同步队列，等待处理…';
  pollTimer = setTimeout(async () => {
    try { await followTask(await academicApi.task(task.id), current); }
    catch (e) {
      if (current === revision) { busy.value = false; syncStatus.value = ''; error.value = '暂时无法查看同步进度。任务可能仍在进行，请稍后重新打开查看。'; }
    }
  }, 1500);
}

watch(() => props.open, async (open) => {
  const current = ++revision;
  stopPolling();
  if (!open) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  selected.value = null;
  result.value = null;
  students.value = [];
  searched.value = false;
  try {
    const [saved, recovery] = await Promise.all([
      academicApi.binding(),
      academicApi.backups().catch(e => ({ backups: [], error: '恢复记录暂不可用：' + e.message })),
    ]);
    if (current !== revision) return;
    bound.value = saved.student;
    backups.value = recovery.backups || [];
    if (recovery.error) error.value = recovery.error;
    lastSyncedAt.value = saved.last_synced_at;
    if (bound.value) {
      selected.value = bound.value;
      const latest = await academicApi.latestTask();
      if (current !== revision) return;
      if (latest.task && (['queued', 'running'].includes(latest.task.state) || localStorage.getItem('academicPendingTaskId') === latest.task.id)) {
        await followTask(latest.task, current);
      } else if (latest.task?.state === 'failed') {
        error.value = latest.task.error;
      }
      await loadTerms(bound.value, current);
      return;
    }
  } catch (e) { if (current === revision) error.value = e.message; }
  finally { if (current === revision && !syncStatus.value) busy.value = false; }
}, { immediate: true });

async function search() {
  const current = ++revision;
  busy.value = true;
  error.value = '';
  notice.value = '';
  selected.value = null;
  result.value = null;
  students.value = [];
  searched.value = false;
  try {
    const data = await academicApi.students({ q: keyword.value.trim() });
    if (current !== revision) return;
    students.value = data.students || [];
    searched.value = true;
    if (data.truncated) notice.value = "找到的学生较多，请补充姓名或班级，方便找到自己。";
    if (data.stale) notice.value = "学校暂时无法连接，先为你显示已保存的学生信息。";
  } catch (e) { if (current === revision) error.value = e.message; }
  finally { if (current === revision && !syncStatus.value) busy.value = false; }
}

async function restoreBackup(backup) {
  if (busy.value || confirmState.value.open) return;
  const accepted = await confirmAction('将恢复所选时间保存的课表，替换当前全部课表和调课。\n当前内容会先备份，可再次恢复。学校自动同步仍会继续更新课表。', { title: '恢复这份课表？', confirmText: '恢复课表', cancelText: '暂不恢复', danger: true });
  if (!accepted || !props.open || busy.value) return;
  const current = ++revision;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const data = await academicApi.restore(backup.id);
    if (current === revision) emit('synced', data);
  } catch (e) { if (current === revision) error.value = e.message; }
  finally { if (current === revision) busy.value = false; }
}

function choose(student) {
  selected.value = student;
  error.value = '';
  notice.value = '';
}

async function loadTerms(student, current) {
  const data = await academicApi.terms(student.id);
  if (current !== revision) return;
  terms.value = data.terms || [];
  term.value = terms.value.includes(student.default_term) ? student.default_term : terms.value[0];
}

async function bindSelected() {
  if (!selected.value || busy.value) return;
  const current = ++revision;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const data = await academicApi.bind(selected.value.id);
    if (current !== revision) return;
    bound.value = data.student;
    selected.value = data.student;
    await loadTerms(bound.value, current);
  } catch (e) { if (current === revision) error.value = e.message; }
  finally { if (current === revision && !syncStatus.value) busy.value = false; }
}

async function unbind() {
  if (busy.value || confirmState.value.open) return;
  const accepted = await confirmAction('解除后不再自动同步学校课表，已同步的课表会保留。\n你可以随时重新绑定或选择其他学校身份。', { title: '解除学校绑定？', confirmText: '解除绑定', cancelText: '保留绑定', danger: true });
  if (!accepted || !props.open || busy.value) return;
  const current = ++revision;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    await academicApi.unbind();
    if (current !== revision) return;
    bound.value = null;
    selected.value = null;
    result.value = null;
    students.value = [];
    searched.value = false;
    terms.value = [];
  } catch (e) { if (current === revision) error.value = e.message; }
  finally { if (current === revision && !syncStatus.value) busy.value = false; }
}

async function query(refresh = false) {
  if (busy.value || confirmState.value.open || !term.value) return;
  const chosenTerm = term.value;
  const accepted = await confirmAction(`将同步 ${chosenTerm} 的学校课表。\n同步成功后只保留这份课表，其他课表和个人调课会被替换。当前内容会先备份，同步失败时保留原课表。`, { title: '更新为学校课表？', confirmText: '同步课表', cancelText: '暂不同步', danger: true });
  if (!accepted || !props.open || busy.value) return;
  const current = ++revision;
  busy.value = true;
  error.value = '';
  notice.value = '';
  result.value = null;
  try {
    const data = await academicApi.sync(chosenTerm, refresh);
    if (current !== revision) return;
    await followTask(data, current);
  } catch (e) { if (current === revision) error.value = e.message; }
  finally { if (current === revision && !syncStatus.value) busy.value = false; }
}
const weekdays = ['','周一','周二','周三','周四','周五','周六','周日'];
</script>

<template>
  <ConfirmModal :open="confirmState.open" :title="confirmState.title" :message="confirmState.message" :confirm-text="confirmState.confirmText" :cancel-text="confirmState.cancelText" :danger="confirmState.danger" @confirm="handleConfirmResult(true)" @cancel="handleConfirmResult(false)" />
  <Teleport to="body">
    <div v-if="open" class="academic-overlay" @click.self="emit('close')" @keydown.esc="emit('close')">
      <section class="academic-panel" role="dialog" aria-modal="true" aria-labelledby="academic-title">
        <header><div><h2 id="academic-title">学校身份绑定</h2><p>选择自己的姓名和班级，绑定后可同步学校课表。</p></div><button type="button" aria-label="关闭" @click="emit('close')">×</button></header>
        <div v-if="bound" class="academic-term">
          <span><b>{{ bound.name }}</b> · {{ bound.grade }}级 · {{ bound.major_name }} · {{ bound.class_name }}</span>
          <span class="academic-meta">最近同步：{{ lastSyncedAt ? new Date(lastSyncedAt).toLocaleString() : '尚未同步' }}</span>
          <button type="button" :disabled="busy" @click="unbind">解除绑定／更换身份</button>
        </div>
        <form v-else @submit.prevent="search">
          <label class="academic-search-label">搜索学校身份
            <input v-model="keyword" type="text" inputmode="text" lang="zh-CN" maxlength="80" autocomplete="off" placeholder="如：张三、计算机、24计科7班、25" :disabled="busy">
          </label>
          <button type="submit" :disabled="busy || !keyword.trim()">搜索</button>
          <p class="academic-meta">输入姓名、专业、班级或年级，可只输入部分文字，如“计科”或“24”。</p>
        </form>
        <p v-if="notice" class="academic-meta" role="status">{{ notice }}</p>
        <p v-if="error" class="academic-error" role="alert">{{ error }}</p>
        <p v-if="busy" role="status">{{ syncStatus || '正在处理，请稍候…' }}</p>
        <div v-if="!bound && students.length" class="academic-students">
          <button v-for="s in students" :key="s.id" type="button" :disabled="busy" :class="{ selected: selected?.id === s.id }" @click="choose(s)">
            <div class="student-item-header">
              <b>{{ s.name }}</b>
              <span v-if="s.grade" class="student-grade-tag">{{ s.grade }}级</span>
            </div>
            <span>{{ s.major_name }} · {{ s.class_name }} · {{ s.student_number_display }}</span>
          </button>
        </div>
        <p v-else-if="!bound && searched && !busy">没有找到匹配学生，请检查姓名、班级和年级。</p>
        <div v-if="!bound && selected" class="academic-term">
          <span>待绑定：{{ selected.grade }}级 · {{ selected.major_name }} · {{ selected.class_name }} · {{ selected.name }}</span>
          <button type="button" :disabled="busy" @click="bindSelected">确认绑定</button>
        </div>
        <div v-if="bound && terms.length" class="academic-term">
          <span>{{ selected?.name || bound?.name }} · {{ selected?.class_name || bound?.class_name }}</span>
          <select v-model="term" :disabled="busy" aria-label="学期" @change="result = null"><option v-for="t in terms" :key="t">{{ t }}</option></select>
          <button type="button" :disabled="busy" @click="query()">同步学校课表</button>
          <p class="academic-meta">同步成功后只保留最新学校课表，其他学期、导入课表和个人调课将被覆盖；覆盖前自动保留最近 5 次恢复记录，同步失败时保留原课表。</p>
          <button v-if="result" type="button" :disabled="busy" @click="query(true)">重新同步</button>
        </div>
        <div v-if="backups.length" class="academic-term">
          <button type="button" :aria-expanded="recoveryExpanded" @click="recoveryExpanded = !recoveryExpanded">恢复之前的课表</button>
          <div v-if="recoveryExpanded">
            <p class="academic-meta">恢复同步前的课表（恢复后，后续自动同步仍会更新学校课表）</p>
            <button v-for="backup in backups" :key="backup.id" type="button" :disabled="busy" @click="restoreBackup(backup)">恢复 {{ new Date(backup.created_at).toLocaleString('zh-CN') }} · {{ backup.schedule_count }} 份课表</button>
          </div>
        </div>
        <div v-if="result">
          <p class="academic-meta">课表更新时间： {{ new Date(result.fetched_at).toLocaleString('zh-CN') }}</p>
          <p v-if="result.stale" class="academic-error">刷新失败，正在显示上次完整课表：{{ result.refresh_error?.message }}</p>
          <p v-for="warning in result.warnings" :key="warning" class="academic-error">{{ warning }}</p>
          <div v-if="result.courses" class="academic-table"><table><thead><tr><th>课程</th><th>时间</th><th>周次</th><th>教师／教室</th></tr></thead>
            <tbody><tr v-for="(c, i) in result.courses" :key="i"><td>{{ c.name }}</td><td>{{ weekdays[c.weekday] }} {{ c.start_section }}–{{ c.end_section }}节</td><td>{{ formatWeeks(c.weeks) }}</td><td>{{ c.teacher }}<br>{{ c.room }}</td></tr></tbody>
          </table></div>
          <p v-if="result.courses && !result.courses.length">该学期未查到课程安排。</p>
          <p v-for="note in result.notes" :key="note" class="academic-meta">{{ note }}</p>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.academic-overlay{box-sizing:border-box;position:fixed;inset:0;z-index:1800;background:#17233466;display:flex;align-items:center;justify-content:center;padding:16px}
.academic-panel{box-sizing:border-box;background:var(--minimal-bg-page,#fff);color:#263743;border-radius:24px;padding:24px;width:min(800px,100%);max-height:90dvh;overflow:auto;box-shadow:0 20px 60px #0002}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}h2{margin:0;font-size:23px}header p{margin:6px 0;color:#667786}button,input,select{font:inherit;border:1px solid #d5dde4;border-radius:10px;padding:9px 12px;background:#fff;color:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}form{display:flex;gap:10px;align-items:end;flex-wrap:wrap}label{display:flex;flex-direction:column;gap:6px;font-size:13px}input{width:170px}.academic-search-label{flex:1;min-width:220px}.academic-search-label input{width:100%;box-sizing:border-box}select{max-width:200px}.academic-error{color:#a44236}.academic-meta{color:#687b88;font-size:13px}

/* 学生列表滚动容器：支持向下滚动查看更多学生，防重名遮挡与显示不全 */
.academic-students {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior: contain;
  margin-top: 18px;
  padding-right: 4px;
}
.academic-students button {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #d5dde4;
  transition: all 0.15s ease;
}
.student-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.student-grade-tag {
  font-size: 11px;
  background: #e2e8f0;
  color: #334155;
  padding: 1px 6px;
  border-radius: 9999px;
  font-weight: 600;
}
.academic-students span {
  font-size: 12px;
  color: #687b88;
  word-break: break-all;
}
.selected {
  border-color: #0284c7 !important;
  background: #eff6ff !important;
  box-shadow: 0 0 0 1px #0284c7;
}

.academic-term{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:20px}.academic-table{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:12px 8px;border-bottom:1px solid #e2e8ed}th{white-space:nowrap}td:nth-child(2){min-width:90px}td:nth-child(3){min-width:100px}header button{font-size:22px;border:0}
</style>
