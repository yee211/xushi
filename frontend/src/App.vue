<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import {
  adjustmentsApi,
  authApi,
  clearAuth,
  coursesApi,
  feedbackApi,
  getActiveScheduleId,
  getToken,
  importerApi,
  schedulesApi,
  setActiveScheduleId,
  setToken,
} from './api/index.js';
import {
  buildCourseColorMap,
  defaultEndDate,
  emptyCourse,
  findCurrentSchedule,
  formatWeeks,
  isScheduleActiveToday,
  parseWeeks,
  scheduleWeekCount,
  suggestSemesterDates,
  termWeek,
} from './utils/schedule.js';

import ScheduleToolbar from './components/ScheduleToolbar.vue';
import ScheduleGrid from './components/ScheduleGrid.vue';
import CoursePreviewModal from './components/CoursePreviewModal.vue';
import CourseEditorModal from './components/CourseEditorModal.vue';
import CourseAdjustmentModal from './components/CourseAdjustmentModal.vue';
import AdjustmentImportModal from './components/AdjustmentImportModal.vue';
import CourseMoveModal from './components/CourseMoveModal.vue';
import AdjustmentCenterModal from './components/AdjustmentCenterModal.vue';
import ImporterModal from './components/ImporterModal.vue';
import SemesterModal from './components/SemesterModal.vue';
import AuthModal from './components/AuthModal.vue';
import UpdateModal from './components/UpdateModal.vue';
import SplashScreen from './components/SplashScreen.vue';
import ConfirmModal from './components/ConfirmModal.vue';
import FeedbackModal from './components/FeedbackModal.vue';
import FloatingDock from './components/FloatingDock.vue';
import UserProfileView from './components/UserProfileView.vue';
import ImportSourceModal from './components/ImportSourceModal.vue';
import CourseCenterModal from './components/CourseCenterModal.vue';
import AppLandingPage from './components/AppLandingPage.vue';
import BgPickerModal from './components/BgPickerModal.vue';

import { registerPlugin } from '@capacitor/core';

const AcademicWebview = registerPlugin('AcademicWebview');
import {
  CURRENT_VERSION_NAME,
  checkAppUpdate,
  ignoreUpdateVersion,
  isNativePlatform,
  openDownloadUrl,
} from './utils/version.js';

// 通用确认模态弹窗状态（替代原生 window.confirm 浏览器弹窗）
const confirmState = ref({
  open: false,
  title: '操作确认',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  danger: true,
  resolve: null,
});

function confirmAction(message, options = {}) {
  return new Promise(resolve => {
    confirmState.value = {
      open: true,
      title: options.title || '操作确认',
      message,
      confirmText: options.confirmText || '确定',
      cancelText: options.cancelText || '取消',
      danger: options.danger ?? true,
      resolve,
    };
  });
}

function handleConfirmResult(result) {
  if (confirmState.value.resolve) {
    confirmState.value.resolve(result);
  }
  confirmState.value.open = false;
  confirmState.value.resolve = null;
}

// 检测运行环境：Android 原生 App vs 网页端宣传落地页
// 默认在普通网页浏览器中展示安卓 App 极简宣传落地页；在 Capacitor 原生宿主或带有 ?mode=app / ?preview=app 参数时运行课表管理功能
const isNative = ref(isNativePlatform());
const isDevPreview = typeof window !== 'undefined' && (
  new URLSearchParams(window.location.search).get('mode') === 'app' ||
  new URLSearchParams(window.location.search).get('preview') === 'app'
);
const showApp = ref(isNative.value || isDevPreview);

// 开屏状态（仅 Android 原生 App 启动时展示，网页端直接进入）
const showSplash = ref(isNative.value);
const splashReady = ref(false);

// 原生开屏层由 @capacitor/splash-screen 管理：内容就绪时淡出
async function hideNativeSplash() {
  if (!isNative.value) return;
  try {
    const { SplashScreen } = await import('@capacitor/splash-screen');
    await SplashScreen.hide({ fadeOutDuration: 400 });
  } catch {}
}

// 基础状态
const week = ref(1);
const currentWeek = ref(1);
const schedules = ref([]);
const schedule = ref(null);
const loading = ref(true);
const message = ref('');

// 应用更新状态
const updateModalOpen = ref(false);
const updateInfo = ref({});
// 未登录时不弹更新弹窗（避免与登录弹窗重叠），登录成功后再弹出
const pendingUpdateAfterLogin = ref(false);

// 用户认证状态
const user = ref(null);
const authMode = ref('login');
const authError = ref('');
const authLoading = ref(false);
const authForm = reactive({ email: '', username: '', password: '' });

// 弹窗状态
const previewOpen = ref(false);
const previewCourse = ref(null);

const editorOpen = ref(false);
const form = reactive(emptyCourse());
const adjustmentOpen = ref(false);
const adjustmentCourse = ref(null);
const adjustmentForm = reactive({ weekday: 1, start_section: 1, end_section: 2, room: '' });
const adjustmentImportOpen = ref(false);
const adjustmentImportLoading = ref(false);
const adjustmentImportApplying = ref(false);
const adjustmentImportFilename = ref('');
const adjustmentImportError = ref('');
const adjustmentImportItems = ref([]);
const moveModalOpen = ref(false);
const pendingMove = ref(null);
const moveSaving = ref(false);
const adjustmentCenterOpen = ref(false);
// 离线模式：接口不可达时展示本地缓存的课表（只读）
const offline = ref(false);
const courseCenterOpen = ref(false);
const changeLogs = ref([]);
const changeLogsLoading = ref(false);
const currentTab = ref('schedule');

const previewCourseLogs = computed(() => {
  if (!previewCourse.value?.id) return [];
  const cid = previewCourse.value.id;
  return changeLogs.value.filter(log => {
    if (log.course_id === cid) return true;
    if (Array.isArray(log.details) && log.details.some(d => d.course_id === cid)) return true;
    return false;
  });
});

const importerOpen = ref(false);
const importing = ref(false);
const importSetup = ref(false);
const importSource = ref('excel');
const importSourceOpen = ref(false);
const fileInputRef = ref(null);
const importFile = ref(null);
const importError = ref('');
const importEngine = ref('');
const importStartDate = ref('');
const importEndDate = ref('');
const importElapsed = ref(0);
let importTimer = null;

const semesterModalOpen = ref(false);
const semesterSaving = ref(false);

// 计算属性
const weekOptions = computed(() =>
  Array.from({ length: scheduleWeekCount(schedule.value) }, (_, index) => index + 1)
);

const courseColorMap = computed(() => buildCourseColorMap(schedule.value?.courses));

async function loadChangeLogs() {
  if (!schedule.value?.id) {
    changeLogs.value = [];
    return;
  }
  changeLogsLoading.value = true;
  try {
    changeLogs.value = await adjustmentsApi.getRecords(schedule.value.id);
  } catch (error) {
    console.error('Failed to load change logs:', error);
  } finally {
    changeLogsLoading.value = false;
  }
}

watch(() => schedule.value?.id, newId => {
  if (newId) loadChangeLogs();
});

watch(adjustmentCenterOpen, val => {
  if (val && schedule.value?.id) {
    loadChangeLogs();
  }
});

// 提示消息
function notify(text) {
  message.value = text;
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => {
    message.value = '';
  }, 2200);
}

// 登出
function logout() {
  clearAuth();
  localStorage.removeItem('cache_user');
  localStorage.removeItem('cache_schedules');
  user.value = null;
  schedule.value = null;
  schedules.value = [];
  offline.value = false;
  loading.value = false;
}

// 登录 / 注册提交
async function submitAuth() {
  authError.value = '';
  const isRegister = authMode.value === 'register';
  const email = authForm.email.trim();
  const username = authForm.username.trim();

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    authError.value = '请输入有效的邮箱地址';
    return;
  }
  if (isRegister && username.length < 2) {
    authError.value = '用户名至少需要 2 个字符';
    return;
  }
  if (authForm.password.length < 6) {
    authError.value = '密码至少需要 6 个字符';
    return;
  }

  authLoading.value = true;
  try {
    const payload = isRegister
      ? { email, username, password: authForm.password }
      : { email, password: authForm.password };
    const result = isRegister ? await authApi.register(payload) : await authApi.login(payload);

    setToken(result.token);
    user.value = result.user;
    authForm.password = '';
    await load();
    notify(isRegister ? '注册成功，欢迎加入' : '欢迎回来');
    // 登录前若已发现新版本，待登录弹窗关闭后再弹出更新
    if (pendingUpdateAfterLogin.value) {
      pendingUpdateAfterLogin.value = false;
      setTimeout(() => {
        updateModalOpen.value = true;
      }, 600);
    }
  } catch (error) {
    authError.value = error.message;
  } finally {
    authLoading.value = false;
  }
}

// 加载课表列表
// 离线横幅「重新连接」：回到在线态并强制刷新数据
async function retryOnline() {
  offline.value = false;
  loading.value = true;
  await load();
}

async function load(preferredId = null) {
  try {
    const list = await schedulesApi.list();
    schedules.value = list;

    // 联网加载成功：刷新本地缓存供断网时兜底（仅 Android 原生端启用离线模式）
    if (isNative.value) {
      try {
        localStorage.setItem('cache_schedules', JSON.stringify(list));
        offline.value = false;
      } catch {}
    }

    if (!list.length) {
      schedule.value = null;
      return;
    }

    let selected = null;
    if (preferredId) {
      selected = list.find(item => item.id === Number(preferredId));
    }

    if (!selected) {
      const activeSchedule = findCurrentSchedule(list);
      const savedId = getActiveScheduleId();
      const savedSchedule = list.find(item => item.id === savedId);

      // 若用户曾主动选择过某个学期（无论是否包含今天），优先保持用户的选择
      if (savedSchedule) {
        selected = savedSchedule;
      } else {
        selected = activeSchedule || list[0];
      }
    }

    schedule.value = selected || list[0] || null;

    if (schedule.value) {
      setActiveScheduleId(schedule.value.id);
    }
    const totalWeeks = scheduleWeekCount(schedule.value);
    currentWeek.value = termWeek(schedule.value?.start_date, totalWeeks, schedule.value);
    week.value = currentWeek.value;
  } catch (error) {
    // 断网 / 服务不可达：回退到本地缓存的课表，进入只读离线模式（仅 Android 原生端）
    if (isNative.value && error?.offline) {
      const cached = readLocalJson('cache_schedules');
      if (Array.isArray(cached) && cached.length) {
        offline.value = true;
        schedules.value = cached;
        const savedId = getActiveScheduleId();
        schedule.value = cached.find(item => item.id === savedId)
          || findCurrentSchedule(cached)
          || cached[0];
        const totalWeeks = scheduleWeekCount(schedule.value);
        currentWeek.value = termWeek(schedule.value?.start_date, totalWeeks, schedule.value);
        week.value = currentWeek.value;
        notify('当前离线，展示本地缓存的课表');
        return false;
      }
    }
    notify(error.message);
    return false;
  } finally {
    loading.value = false;
  }
  return true;
}

// 手动同步课表：从服务器拉取最新数据并更新本地缓存
async function syncSchedules(resolve) {
  const prevWeek = week.value;
  try {
    const ok = await load(schedule.value?.id);
    if (ok) {
      if (prevWeek > 0 && prevWeek <= weekOptions.value.length) {
        week.value = prevWeek;
      }
      notify('课表已同步到最新');
    }
  } catch (error) {
    notify(error.message || '同步失败，请稍后重试');
  } finally {
    if (typeof resolve === 'function') resolve();
  }
}

// 支持在原课表上就地直接修改，无需克隆派生调课版副本。
async function ensureEditableSchedule(courseId = null) {
  return {
    scheduleId: schedule.value?.id,
    courseId,
    courseMap: {},
    fromOriginal: false,
  };
}

// 切换当前课表
function selectSchedule(payload) {
  const targetId = typeof payload === 'object' && payload?.target ? Number(payload.target.value) : Number(payload);
  const found = schedules.value.find(item => item.id === targetId);
  if (!found) return;
  schedule.value = found;
  setActiveScheduleId(found.id);
  const totalWeeks = scheduleWeekCount(found);
  currentWeek.value = termWeek(found.start_date, totalWeeks, found);
  week.value = currentWeek.value;
}

// 删除课表
async function deleteSchedule() {
  const current = schedule.value;
  if (!current) return;
  const title = current.term || current.name || '当前课表';
  const ok = await confirmAction(`确认删除“${title}”？该课表中的全部课程也会被删除。`, {
    title: '删除课表',
    confirmText: '删除',
    danger: true,
  });
  if (!ok) return;
  try {
    await schedulesApi.delete(current.id);
    setActiveScheduleId(null);
    semesterModalOpen.value = false;
    await load(null);
    notify('课表已删除');
  } catch (error) {
    notify(error.message);
  }
}

// 学期设置
function openSemesterSettings() {
  semesterModalOpen.value = true;
}

async function saveSemesterSettings(payload) {
  if (!schedule.value) return;
  semesterSaving.value = true;
  try {
    const updated = await schedulesApi.update(schedule.value.id, payload);
    semesterModalOpen.value = false;
    notify('学期设置已保存');
    await load(updated.id);
  } catch (error) {
    notify(error.message);
  } finally {
    semesterSaving.value = false;
  }
}


function goCurrentWeek() {
  week.value = currentWeek.value;
}

function prevWeek() {
  if (week.value > 1) {
    week.value--;
  }
}

function nextWeek() {
  if (week.value < weekOptions.value.length) {
    week.value++;
  }
}

// 课程详情预览与编辑跳转
function openPreview(course) {
  previewCourse.value = course;
  previewOpen.value = true;
}

function editPreview(course) {
  previewOpen.value = false;
  openEditor(course);
}

function openAdjustment(course) {
  previewOpen.value = false;
  adjustmentCourse.value = course;
  Object.assign(adjustmentForm, {
    weekday: course.weekday,
    start_section: course.start_section,
    end_section: course.end_section,
    room: course.room || '',
  });
  adjustmentOpen.value = true;
}

async function saveAdjustment() {
  const payload = {
    week: week.value,
    weekday: +adjustmentForm.weekday,
    start_section: +adjustmentForm.start_section,
    end_section: +adjustmentForm.end_section,
    room: adjustmentForm.room.trim(),
  };
  if (payload.end_section < payload.start_section) {
    notify('结束节次不能早于开始节次');
    return;
  }
  try {
    const editable = await ensureEditableSchedule(adjustmentCourse.value.id);
    await coursesApi.adjust(editable.courseId, week.value, payload);
    adjustmentOpen.value = false;
    notify(`第 ${week.value} 周调课已保存`);
    await load(editable.scheduleId);
  } catch (error) {
    notify(error.message);
  }
}

async function cancelAdjustment() {
  const ok = await confirmAction(`确认撤销第 ${week.value} 周的调课？`, {
    title: '撤销调课',
    confirmText: '撤销',
    danger: true,
  });
  if (!ok) return;
  try {
    await coursesApi.cancelAdjustment(adjustmentCourse.value.id, week.value);
    adjustmentOpen.value = false;
    notify('调课已撤销');
    await load(schedule.value.id);
  } catch (error) {
    notify(error.message);
  }
}

async function uploadAdjustmentNotice(file) {
  if (!file || !schedule.value) return;
  adjustmentCenterOpen.value = false;
  adjustmentImportOpen.value = true;
  adjustmentImportLoading.value = true;
  adjustmentImportFilename.value = file.name;
  adjustmentImportError.value = '';
  adjustmentImportItems.value = [];
  try {
    const result = await adjustmentsApi.parse(file, schedule.value.id);
    adjustmentImportItems.value = result.items;
    if (!result.matched) adjustmentImportError.value = '识别成功，但没有记录能与当前课表可靠匹配';
  } catch (error) {
    adjustmentImportError.value = error.message;
  } finally {
    adjustmentImportLoading.value = false;
  }
}

async function revokeAdjustmentRecord(record) {
  const courseName = record.course_name || '课程';
  const ok = await confirmAction(`确认撤销“${courseName}”第 ${record.week} 周的调课？`, {
    title: '撤销调课',
    confirmText: '撤销',
    danger: true,
  });
  if (!ok) return;
  try {
    await coursesApi.cancelAdjustment(record.course_id, record.week);
    notify('调课记录已撤销');
    await load(schedule.value.id);
    await loadChangeLogs();
    if (previewCourse.value && previewCourse.value.id === record.course_id) {
      const refreshed = (schedule.value?.courses || []).find(c => c.id === record.course_id);
      if (refreshed) previewCourse.value = refreshed;
    }
  } catch (error) {
    notify(error.message);
  }
}

async function revokeBatchRecord(record) {
  if (!record || !record.id) return;
  const activeDetails = (record.details || []).filter(detail => detail && detail.can_revoke);
  const count = activeDetails.length || (record.details || []).length;
  const ok = await confirmAction(
    `确认一键撤销本次调课的全部改动（共 ${count} 条）？课表将恢复至调课前的原始状态。`,
    {
      title: '一键撤销调课',
      confirmText: '撤销全部',
      danger: true,
    }
  );
  if (!ok) return;
  try {
    const res = await adjustmentsApi.revokeRecord(record.id);
    notify(res.revoked ? `已一键撤销 ${res.revoked} 条调课` : '该记录调课已撤销');
    await load(schedule.value?.id);
    await loadChangeLogs();
  } catch (error) {
    notify(error.message);
  }
}

async function applyAdjustmentNotice() {
  const selected = adjustmentImportItems.value.filter(item => item.status === 'matched' && item.selected);
  if (!selected.length) return;
  adjustmentImportApplying.value = true;
  try {
    const editable = await ensureEditableSchedule();
    const items = selected.map(item => ({
      course_id: editable.courseMap?.[String(item.course_id)] || item.course_id,
      week: item.week,
      weekday: item.new_weekday,
      start_section: item.new_start_section,
      end_section: item.new_end_section,
      room: item.new_room,
    }));
    const result = await adjustmentsApi.apply(editable.scheduleId, items);
    adjustmentImportOpen.value = false;
    notify(`已应用 ${result.applied} 条调课`);
    await load(schedule.value.id);
    await loadChangeLogs();
  } catch (error) {
    adjustmentImportError.value = error.message;
  } finally {
    adjustmentImportApplying.value = false;
  }
}

function requestCourseMove(move) {
  pendingMove.value = move;
  moveModalOpen.value = true;
}

async function saveCourseMove(scope) {
  const move = pendingMove.value;
  if (!move) return;
  moveSaving.value = true;
  try {
    const editable = await ensureEditableSchedule(move.course.id);
    const effectiveCourseId = editable.courseId;
    const orig = move.course.original_course || move.course;
    if (scope === 'week') {
      // If moved back to original unadjusted position, cancel adjustment instead of creating redundant adjustment
      if (orig.weekday === move.weekday
          && orig.start_section === move.start_section
          && orig.end_section === move.end_section
          && (orig.room || '') === (move.course.room || '')) {
        if (move.course.adjusted_week) {
          await coursesApi.cancelAdjustment(effectiveCourseId, week.value);
          notify(`已移回第 ${week.value} 周原位置，自动取消调课`);
          moveModalOpen.value = false;
          await load(schedule.value.id);
          await loadChangeLogs();
          return;
        }
      }
      await coursesApi.adjust(effectiveCourseId, week.value, {
        week: week.value,
        weekday: move.weekday,
        start_section: move.start_section,
        end_section: move.end_section,
        room: move.course.room || '',
      });
    } else {
      const base = move.course.original_course || move.course;
      await coursesApi.update(effectiveCourseId, {
        schedule_id: editable.scheduleId,
        name: base.name,
        teacher: base.teacher || '',
        room: base.room || '',
        weekday: move.weekday,
        start_section: move.start_section,
        end_section: move.end_section,
        weeks: base.weeks || [],
        color: base.color,
      }, 'drag');
      if (move.course.adjusted_week) {
        try {
          await coursesApi.cancelAdjustment(effectiveCourseId, move.course.adjusted_week);
        } catch (_) {}
      }
    }
    moveModalOpen.value = false;
    notify(scope === 'week' ? `第 ${week.value} 周课程已调整` : '整学期课程时间已修改');
    await load(schedule.value.id);
    await loadChangeLogs();
  } catch (error) {
    notify(error.message);
  } finally {
    moveSaving.value = false;
  }
}

const editingAdjustedWeek = ref(null);

function openEditor(course) {
  editingAdjustedWeek.value = course?.adjusted_week || null;
  Object.assign(form, emptyCourse(), course || {});
  form.weeks = formatWeeks(course?.weeks) || '1-16';
  editorOpen.value = true;
}

// 保存课程
async function saveCourse() {
  const payload = {
    schedule_id: schedule.value.id,
    name: form.name.trim(),
    teacher: form.teacher.trim(),
    room: form.room.trim(),
    weekday: +form.weekday,
    start_section: +form.start_section,
    end_section: +form.end_section,
    weeks: parseWeeks(form.weeks),
    color: form.color,
  };
  if (payload.end_section < payload.start_section) {
    notify('结束节次不能早于开始节次');
    return;
  }
  try {
    const editable = await ensureEditableSchedule(form.id || null);
    payload.schedule_id = editable.scheduleId;
    if (form.id) {
      await coursesApi.update(editable.courseId, payload, 'manual', true);
      if (editingAdjustedWeek.value) {
        try {
          await coursesApi.cancelAdjustment(editable.courseId, editingAdjustedWeek.value);
        } catch (_) {}
        editingAdjustedWeek.value = null;
      }
    } else {
      await coursesApi.add(payload);
    }
    editorOpen.value = false;
    notify('课程已保存');
    await load();
    await loadChangeLogs();
  } catch (error) {
    notify(error.message);
  }
}

const feedbackOpen = ref(false);
const feedbackSubmitting = ref(false);

async function submitFeedback(payload) {
  feedbackSubmitting.value = true;
  try {
    const res = await feedbackApi.submit({
      ...payload,
      client_info: {
        platform: isNative.value ? 'Android' : 'Web',
        app_version: CURRENT_VERSION_NAME,
        user_agent: navigator.userAgent,
      },
    });
    notify(res.message || '感谢你的反馈！');
    feedbackOpen.value = false;
  } catch (error) {
    notify(error.message || '反馈提交失败，请稍后重试');
  } finally {
    feedbackSubmitting.value = false;
  }
}

async function deleteChangeLog(record) {
  const ok = await confirmAction('确认删除此条变更记录？', {
    title: '删除记录',
    confirmText: '删除',
    danger: true,
  });
  if (!ok) return;
  try {
    await adjustmentsApi.deleteRecord(record.id);
    notify('记录已删除');
    await loadChangeLogs();
  } catch (error) {
    notify(error.message);
  }
}

async function removeCourseAdjustment(course) {
  if (!course?.adjusted_week) return;
  const ok = await confirmAction(`确认取消《${course.name}》第 ${course.adjusted_week} 周的调课，恢复原排课？`, {
    title: '取消调课',
    confirmText: '确定取消',
    danger: true,
  });
  if (!ok) return;
  try {
    await coursesApi.cancelAdjustment(course.id, course.adjusted_week);
    notify('已取消调课，恢复原时间');
    await load(schedule.value.id);
    await loadChangeLogs();
    if (previewCourse.value && previewCourse.value.id === course.id) {
      const refreshed = (schedule.value?.courses || []).find(c => c.id === course.id);
      if (refreshed) previewCourse.value = refreshed;
    }
  } catch (error) {
    notify(error.message);
  }
}

async function restoreCourseRecord(record) {
  if (!record.course_id) return;
  const course = (schedule.value?.courses || []).find(c => c.id === record.course_id);
  if (!course) {
    notify('原课程已不存在');
    return;
  }
  const timeDiff = Array.isArray(record.details) ? record.details.find(d => d.field === 'time') : null;
  const roomDiff = Array.isArray(record.details) ? record.details.find(d => d.field === 'room') : null;
  if (!timeDiff && !roomDiff) {
    notify('未找到可恢复的变更项');
    return;
  }
  const ok = await confirmAction(`确认撤销改动，将《${course.name}》直接回滚至此记录修改前的状态？`, {
    title: '回滚改动',
    confirmText: '回滚',
    danger: true,
  });
  if (!ok) return;
  try {
    const orig = course.original_course || course;
    const targetWeekday = timeDiff?.old_weekday ? timeDiff.old_weekday : orig.weekday;
    const targetStart = timeDiff?.old_start_section ? timeDiff.old_start_section : orig.start_section;
    const targetEnd = timeDiff?.old_end_section ? timeDiff.old_end_section : orig.end_section;
    const targetRoom = roomDiff && roomDiff.old !== '未设置' ? roomDiff.old : (course.room || orig.room || '');

    const recordWeek = record.week || (Array.isArray(record.details) ? record.details[0]?.week : null);

    // If single-week move or adjustment
    // drag_move 同时用于整学期移动和单周调课；只有日志明确携带 week 才按单周恢复。
    if (recordWeek) {
      const w = recordWeek || week.value;
      // If target matches original unadjusted course, cancel adjustment completely
      if (targetWeekday === orig.weekday && targetStart === orig.start_section && targetEnd === orig.end_section && targetRoom === (orig.room || '')) {
        await coursesApi.cancelAdjustment(course.id, w);
      } else {
        await coursesApi.adjust(course.id, w, {
          week: w,
          weekday: targetWeekday,
          start_section: targetStart,
          end_section: targetEnd,
          room: targetRoom,
        });
      }
    } else {
      // All-weeks course update
      const payload = {
        schedule_id: schedule.value.id,
        name: course.name,
        teacher: course.teacher || '',
        room: targetRoom,
        weekday: targetWeekday,
        start_section: targetStart,
        end_section: targetEnd,
        weeks: orig.weeks || course.weeks || [],
        color: course.color,
      };
      await coursesApi.update(course.id, payload, 'manual');
    }

    // Clean up this record and all subsequent records for this course (chain rollback)
    const subsequentLogs = (changeLogs.value || []).filter(l => {
      const cid = l.course_id || (Array.isArray(l.details) ? l.details[0]?.course_id : null);
      return cid === course.id && l.id >= record.id;
    });
    for (const sub of subsequentLogs) {
      try {
        await adjustmentsApi.deleteRecord(sub.id);
      } catch (_) {}
    }

    notify('已成功撤销并回滚至该次修改前的状态');
    await load(schedule.value.id);
    await loadChangeLogs();
    if (previewCourse.value && previewCourse.value.id === course.id) {
      const refreshed = (schedule.value?.courses || []).find(c => c.id === course.id);
      if (refreshed) previewCourse.value = refreshed;
    }
  } catch (error) {
    notify(error.message);
  }
}

// 删除课程
async function removeCourse() {
  if (!form.id) return;
  const ok = await confirmAction('确认删除这门课程？', {
    title: '删除课程',
    confirmText: '删除',
    danger: true,
  });
  if (!ok) return;
  try {
    const editable = await ensureEditableSchedule(form.id);
    await coursesApi.delete(editable.courseId);
    editorOpen.value = false;
    notify('课程已删除');
    await load();
    await loadChangeLogs();
  } catch (error) {
    notify(error.message);
  }
}

// 上传与导入向导
function upload(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  importSource.value = 'excel';
  importerOpen.value = true;
  importing.value = false;
  importSetup.value = true;
  importFile.value = file;
  importError.value = '';
  importEngine.value = '';

  // 智能推测学期日期：优先看文件名是否含有学年学期标识（如 2025-2026-1 等）
  const suggestedFromName = suggestSemesterDates(file.name);
  if (suggestedFromName) {
    importStartDate.value = suggestedFromName.start;
    importEndDate.value = suggestedFromName.end;
  } else if (schedule.value && isScheduleActiveToday(schedule.value)) {
    importStartDate.value = schedule.value.start_date?.slice(0, 10) || '';
    importEndDate.value = schedule.value.end_date?.slice(0, 10) || defaultEndDate(importStartDate.value);
  } else {
    const currentYear = new Date().getFullYear();
    const currentSuggested = suggestSemesterDates(`${currentYear}-${currentYear + 1}-1`);
    importStartDate.value = currentSuggested?.start || '';
    importEndDate.value = currentSuggested?.end || defaultEndDate(importStartDate.value);
  }
}

async function startImport() {
  if (!importFile.value) return;
  if (!importStartDate.value || !importEndDate.value) {
    importError.value = '请先填写学期开始日期和结束日期';
    return;
  }
  if (importEndDate.value < importStartDate.value) {
    importError.value = '学期结束日期不能早于开始日期';
    return;
  }
  importSetup.value = false;
  importing.value = true;
  importError.value = '';
  importElapsed.value = 0;
  window.clearInterval(importTimer);
  importTimer = window.setInterval(() => { importElapsed.value += 1; }, 1000);
  const body = new FormData();
  body.append('file', importFile.value);
  body.append('start_date', importStartDate.value);
  body.append('end_date', importEndDate.value);

  try {
    const result = await importerApi.importFile(body);
    importEngine.value = result.engine || '';
    if (result.imported) {
      importerOpen.value = false;
      await load(result.schedule_id);
      notify(result.replaced ? `已覆盖当前学期，共 ${result.imported} 条课程安排` : `已导入 ${result.imported} 条课程安排`);
    }
  } catch (error) {
    importError.value = error.message;
    notify(error.message);
  } finally {
    importing.value = false;
    window.clearInterval(importTimer);
    importTimer = null;
  }
}

// 教务系统在线导入向导 (WebView 深度抓取)
async function openAcademicImport() {
  if (!isNative.value) {
    notify('教务系统在线导入需在安卓客户端中使用，请在手机端体验或使用 Excel 导入');
    return;
  }
  try {
    const res = await AcademicWebview.open({
      url: 'https://tls.ccsut.cn/admin/login',
      title: '长沙工业学院教务系统',
    });
    if (!res || res.cancelled) {
      return;
    }
    if (!res.data) {
      notify('未获取到课表内容，请确认已进入教务课表页面后再次点击');
      return;
    }
    await startHtmlImport(res.data);
  } catch (error) {
    notify('打开教务系统失败：' + (error.message || error));
  }
}

async function startHtmlImport(data) {
  importSource.value = 'academic';
  importFile.value = null;
  importSetup.value = false;
  importerOpen.value = true;
  importing.value = true;
  importError.value = '';
  importEngine.value = '';
  importElapsed.value = 0;
  window.clearInterval(importTimer);
  importTimer = window.setInterval(() => { importElapsed.value += 1; }, 1000);

  try {
    const result = await importerApi.importHtml({
      data,
      start_date: schedule.value?.start_date?.slice(0, 10) || '',
      end_date: schedule.value?.end_date?.slice(0, 10) || '',
    });
    importEngine.value = result.engine || '';
    if (result.imported) {
      importerOpen.value = false;
      await load(result.schedule_id);
      notify(result.replaced ? `已同步覆盖《${result.term}》，共 ${result.imported} 门课程` : `已从教务系统导入 ${result.imported} 门课程`);
    }
  } catch (error) {
    importError.value = error.message;
    notify(error.message);
  } finally {
    importing.value = false;
    window.clearInterval(importTimer);
    importTimer = null;
  }
}

// 自定义背景色板映射
const BG_COLORS = {
  default: '#FFFFFF',
  cream:   '#FAF8F5',
  stone:   '#F4F3F0',
  paper:   '#F9F6F0',
  lavender:'#F6F4FA',
  sky:     '#F0F5FA',
  mint:    '#F1F7F4',
  peach:   '#FAF3EE',
  rose:    '#FBF2F4',
  slate:   '#F1F3F5',
};

const savedCustomBg = localStorage.getItem('schedule_custom_bg') || 'default';
const customBg = ref(savedCustomBg);
const bgPickerOpen = ref(false);

function applyBg(id, hex = null) {
  customBg.value = id;
  localStorage.setItem('schedule_custom_bg', id);
  const color = hex || BG_COLORS[id] || '#FFFFFF';
  document.documentElement.style.setProperty('--minimal-bg-page', color);
  document.body.style.backgroundColor = color;
}


// 应用更新控制（仅在 Android 原生 App 内弹窗推送）
async function handleCheckUpdate(silent = false) {
  if (!isNative.value) {
    if (!silent) {
      notify('网页端已连接云端实时更新，刷新页面即可获取最新内容');
    }
    return;
  }
  try {
    const result = await checkAppUpdate(silent);
    if (result.hasUpdate) {
      updateInfo.value = result.updateInfo;
      if (user.value) {
        updateModalOpen.value = true;
      } else {
        pendingUpdateAfterLogin.value = true;
        if (!silent) {
          notify(`发现新版本 v${result.updateInfo?.versionName || ''}，登录后自动弹出更新`);
        }
      }
    } else if (!silent) {
      notify(`当前已是最新版本 (v${CURRENT_VERSION_NAME})`);
    }
  } catch (error) {
    if (!silent) {
      notify(error.message || '检查更新失败，请稍后重试');
    }
  }
}

function onConfirmUpdate(url) {
  const target = typeof url === 'string' && url ? url : updateInfo.value?.downloadUrl;
  if (target) {
    openDownloadUrl(target);
  }
}

function onIgnoreUpdate() {
  if (updateInfo.value?.versionCode) {
    ignoreUpdateVersion(updateInfo.value.versionCode);
  }
  updateModalOpen.value = false;
}

// 生命周期
// 本地缓存可能因写入中断而损坏：解析失败一律按无缓存处理，不让异常从 catch 处理链里逃逸
function readLocalJson(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || 'null');
  } catch {
    return null;
  }
}

onMounted(async () => {
  applyBg(customBg.value);

  if (!showApp.value) {
    // 网页端宣传页模式，无需拉取课表与登录状态（开屏层仅原生端存在）
    loading.value = false;
    return;
  }

  // 数据就绪后撤开屏（SplashScreen 组件 → 应用内容；原生层由 @capacitor/splash-screen 管理）
  const finishSplash = () => {
    splashReady.value = true;
    hideNativeSplash();
  };
  const splashFailsafe = setTimeout(finishSplash, 5000);

  window.addEventListener('auth:expired', logout);
  if (getToken()) {
    try {
      user.value = await authApi.me();
      if (isNative.value) {
        try {
          localStorage.setItem('cache_user', JSON.stringify(user.value));
        } catch {}
      }
      await load();
    } catch (error) {
      // 断网 / 服务不可达：用本地缓存的账号进入离线模式；仅真正鉴权失败才登出（仅 Android 原生端）
      const cachedUser = readLocalJson('cache_user');
      if (isNative.value && error?.offline && cachedUser) {
        user.value = cachedUser;
        offline.value = true;
        await load();
      } else {
        logout();
      }
    }
  } else {
    loading.value = false;
  }
  clearTimeout(splashFailsafe);
  finishSplash();
  // 更新检查放在登录态恢复之后，未登录时只记录不弹窗，避免与登录弹窗重叠
  if (isNative.value) {
    handleCheckUpdate(true);
  }
});

onUnmounted(() => {
  window.removeEventListener('auth:expired', logout);
  window.clearInterval(importTimer);
});
</script>

<template>
  <!-- 网页端默认展示“序时”官方极简宣传落地页 -->
  <AppLandingPage v-if="!showApp" />

  <!-- 原生 Android 客户端及调试模式呈现课表应用 -->
  <template v-else>
    <!-- 开屏封面（仅在 Android 原生 App 启动时展示，轻触或1秒后平滑进入） -->
    <Transition name="splash-fade">
      <SplashScreen v-if="isNative && showSplash" :ready="splashReady" :duration="0.6" @finish="showSplash = false" />
    </Transition>

  <div id="custom-bg-layer" style="display:none;position:fixed;inset:0;z-index:0;" aria-hidden="true"></div>
  <video
    class="video-wallpaper"
    src="/wallpaper.mp4"
    poster="/wallpaper-fallback.jpg"
    autoplay
    muted
    loop
    playsinline
    preload="metadata"
    aria-hidden="true"
  ></video>
  <div class="ambient-canvas" aria-hidden="true">
    <div class="blob blob-1"></div>
    <div class="blob blob-2"></div>
    <div class="blob blob-3"></div>
    <div class="blob blob-4"></div>
  </div>

  <main class="shell" v-if="user">
    <!-- 课表主视图 -->
    <div v-show="currentTab === 'schedule'" class="tab-view schedule-view">
      <!-- 离线模式提示：接口不可达时展示本地缓存 -->
      <Transition name="splash-fade">
        <div v-if="offline && user" class="offline-banner">
          <span class="offline-dot"></span>
          <span>离线模式 · 展示本地缓存的课表</span>
          <button class="offline-retry" @click="retryOnline">重新连接</button>
        </div>
      </Transition>
      <ScheduleToolbar
        :schedules="schedules"
        :schedule="schedule"
        :week="week"
        :current-week="currentWeek"
        :week-options="weekOptions"
        @update:week="week = $event"
        @select-schedule="selectSchedule"
        @go-current-week="goCurrentWeek"
        @open-semester-settings="openSemesterSettings"
        @open-adjustments="adjustmentCenterOpen = true"
        @open-course-center="courseCenterOpen = true"
        @sync-schedules="syncSchedules"
      />

      <ScheduleGrid
        :key="schedule?.id"
        :schedule="schedule"
        :week="week"
        :loading="loading"
        :color-map="courseColorMap"
        @preview-course="openPreview"
        @move-course="requestCourseMove"
        @move-conflict="notify('目标时段存在课程，不能移动到这里')"
        @prev-week="prevWeek"
        @next-week="nextWeek"
      />

      <!-- 课表网格 -->
    </div>

    <!-- 个人中心全屏视图 -->
    <div v-show="currentTab === 'profile'" class="tab-view profile-view">
      <UserProfileView
        :user="user"
        :schedule="schedule"
        :custom-bg="customBg"
        :app-version="CURRENT_VERSION_NAME"
        :is-native="isNative"
        @open-bg-picker="bgPickerOpen = true"
        @check-update="handleCheckUpdate(false)"
        @open-feedback="feedbackOpen = true"
        @logout="logout"
        @notify="notify"
      />
    </div>

    <!-- 极简双Tab悬浮底栏与操作中枢 (Floating Dock) -->
    <FloatingDock
      :active-tab="currentTab"
      :show-action="currentTab === 'schedule'"
      @update:active-tab="currentTab = $event"
      @open-profile="currentTab = 'profile'"
      @open-course-center="courseCenterOpen = true"
      @add-course="openEditor()"
      @upload="upload"
      @open-import="importSourceOpen = true"
      @open-adjustments="adjustmentCenterOpen = true"
      @delete-schedule="deleteSchedule"
    />

    <!-- 隐藏的 Excel 文件上传 input -->
    <input
      ref="fileInputRef"
      type="file"
      accept=".xlsx,.xlsm,.xls"
      class="hidden-file-input"
      style="display: none;"
      @change="upload"
    />
  </main>

  <!-- 导入方式选择弹窗 (Excel vs 教务系统) -->
  <ImportSourceModal
    :open="importSourceOpen"
    @close="importSourceOpen = false"
    @select-excel="fileInputRef?.click()"
    @select-academic="openAcademicImport"
  />

  <!-- 登录 / 注册模态弹窗 -->
  <AuthModal
    :open="!user"
    :auth-mode="authMode"
    :auth-form="authForm"
    :auth-error="authError"
    :auth-loading="authLoading"
    :app-version="CURRENT_VERSION_NAME"
    :is-native="isNative"
    @submit="submitAuth"
    @update:auth-mode="authMode = $event"
    @clear-error="authError = ''"
    @check-update="handleCheckUpdate(false)"
  />

  <!-- 课程预览模态弹窗 -->
  <CoursePreviewModal
    :open="previewOpen"
    :course="previewCourse"
    :color-map="courseColorMap"
    :records="previewCourseLogs"
    @close="previewOpen = false"
    @edit="editPreview"
    @adjust="openAdjustment"
    @restore="restoreCourseRecord"
    @revoke="revokeAdjustmentRecord"
    @delete="deleteChangeLog"
    @remove-adjustment="removeCourseAdjustment"
  />

  <!-- 课程编辑 / 新建模态弹窗 -->
  <CourseEditorModal
    :open="editorOpen"
    :form="form"
    @close="editorOpen = false"
    @save="saveCourse"
    @delete="removeCourse"
  />

  <CourseAdjustmentModal
    :open="adjustmentOpen"
    :course="adjustmentCourse"
    :week="week"
    :form="adjustmentForm"
    :existing="Boolean(adjustmentCourse?.adjusted_week)"
    @close="adjustmentOpen = false"
    @save="saveAdjustment"
    @cancel-adjustment="cancelAdjustment"
  />

  <AdjustmentImportModal
    :open="adjustmentImportOpen"
    :loading="adjustmentImportLoading"
    :applying="adjustmentImportApplying"
    :filename="adjustmentImportFilename"
    :error="adjustmentImportError"
    :items="adjustmentImportItems"
    @close="adjustmentImportOpen = false"
    @apply="applyAdjustmentNotice"
  />

  <AdjustmentCenterModal
    :open="adjustmentCenterOpen"
    :records="changeLogs"
    :loading="changeLogsLoading"
    @close="adjustmentCenterOpen = false"
    @image="uploadAdjustmentNotice"
    @revoke="revokeAdjustmentRecord"
    @revoke-batch="revokeBatchRecord"
    @restore="restoreCourseRecord"
    @delete="deleteChangeLog"
  />

  <!-- 课表中心模态弹窗 (显示导入的全部课程信息与学时统计) -->
  <CourseCenterModal
    :open="courseCenterOpen"
    :schedule="schedule"
    :week="week"
    :color-map="courseColorMap"
    @close="courseCenterOpen = false"
    @preview-course="openPreview"
    @edit-course="openEditor"
    @adjust-course="openAdjustment"
    @add-course="openEditor()"
    @import-course="importSourceOpen = true"
  />

  <CourseMoveModal
    :open="moveModalOpen"
    :move="pendingMove"
    :week="week"
    :saving="moveSaving"
    @close="moveModalOpen = false"
    @save-week="saveCourseMove('week')"
  />

  <!-- 课表导入向导模态弹窗 -->
  <ImporterModal
    :open="importerOpen"
    :importing="importing"
    :import-setup="importSetup"
    :import-source="importSource"
    :import-file="importFile"
    :import-start-date="importStartDate"
    :import-end-date="importEndDate"
    :import-error="importError"
    :import-engine="importEngine"
    :import-elapsed="importElapsed"
    @close="importerOpen = false"
    @update:import-start-date="importStartDate = $event"
    @update:import-end-date="importEndDate = $event"
    @start-import="startImport"
  />

  <!-- 学期与开学日期设置模态弹窗 -->
  <SemesterModal
    :open="semesterModalOpen"
    :schedule="schedule"
    :saving="semesterSaving"
    @close="semesterModalOpen = false"
    @save="saveSemesterSettings"
    @delete="deleteSchedule"
  />

  <!-- 版本升级提示模态弹窗（仅在 Android 原生 App 内展示推送） -->
  <UpdateModal
    v-if="isNative"
    :open="updateModalOpen"
    :update-info="updateInfo"
    :current-version="CURRENT_VERSION_NAME"
    @close="updateModalOpen = false"
    @ignore="onIgnoreUpdate"
    @confirm="onConfirmUpdate"
  />

  <!-- 通用确认模态弹窗（替代原生 window.confirm 浏览器弹窗） -->
  <ConfirmModal
    :open="confirmState.open"
    :title="confirmState.title"
    :message="confirmState.message"
    :confirm-text="confirmState.confirmText"
    :cancel-text="confirmState.cancelText"
    :danger="confirmState.danger"
    @confirm="handleConfirmResult(true)"
    @cancel="handleConfirmResult(false)"
  />

  <!-- 用户意见与反馈模态弹窗 -->
  <FeedbackModal
    :open="feedbackOpen"
    :submitting="feedbackSubmitting"
    @close="feedbackOpen = false"
    @submit="submitFeedback"
  />

  <!-- 自定义背景选择器 -->
  <BgPickerModal
    :open="bgPickerOpen"
    :current-bg="customBg"
    @close="bgPickerOpen = false"
    @apply="applyBg"
  />


  <Transition name="toast">
    <div v-if="message" class="toast" role="status" aria-live="polite">{{ message }}</div>
  </Transition>
  </template>
</template>

<style>
.splash-fade-leave-active {
  transition: opacity 0.45s cubic-bezier(0.4, 0, 0.2, 1), transform 0.45s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}
.splash-fade-leave-to {
  opacity: 0;
  transform: scale(1.06);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.term-select-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: 0 2px 8px rgba(50, 75, 110, 0.06), inset 0 1px 0.5px #fff;
  padding: 3px 12px;
  max-width: 100%;
}

.term-select-wrap select {
  max-width: min(360px, 60vw);
  padding: 2px 24px 2px 0;
  border: 0;
  outline: 0;
  appearance: none;
  background: transparent;
  color: #0f172a;
  font: inherit;
  font-size: 1.15rem;
  font-weight: 700;
  cursor: pointer;
}

.term-select-wrap select option {
  color: #0f172a;
  background: #ffffff;
}

.term-select-wrap i {
  position: absolute;
  right: 10px;
  top: 50%;
  color: #475569;
  font-style: normal;
  pointer-events: none;
  transform: translateY(-55%);
  font-weight: bold;
}

html[data-bg="night"] .term-select-wrap {
  background: rgba(15, 23, 42, 0.65);
  border-color: rgba(148, 163, 184, 0.32);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3), inset 0 1px 0.5px rgba(255, 255, 255, 0.15);
}

html[data-bg="night"] .term-select-wrap select {
  color: #f8fafc;
}

html[data-bg="night"] .term-select-wrap select option {
  color: #f8fafc;
  background: #0f172a;
}

html[data-bg="night"] .term-select-wrap i {
  color: #94a3b8;
}

.week-menu {
  position: relative;
  flex: 0 1 164px;
  min-width: 0;
  z-index: 15;
}

.week-trigger {
  width: 100%;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 14px;
  border-radius: var(--minimal-radius-pill);
  color: var(--minimal-text-primary);
  background: #FFFFFF;
  border: 1px solid var(--minimal-border);
  box-shadow: none;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.week-trigger:hover {
  background: var(--minimal-bg-surface);
}

.week-trigger span {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.week-trigger b {
  font-size: 0.88rem;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.week-trigger small {
  margin-top: 2px;
  color: var(--minimal-text-secondary);
  font-size: 0.66rem;
  line-height: 1.1;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.week-trigger i {
  font-style: normal;
  color: #64748b;
  font-size: 1.1rem;
  line-height: 1;
  transition: transform 0.22s ease;
}

.week-trigger i.open {
  transform: rotate(180deg);
}

.week-menu-panel {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  width: min(460px, calc(100vw - 40px));
  padding: 16px;
  border-radius: 22px;
  animation: menu-spring 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
  z-index: 30;
}

@keyframes menu-spring {
  from { opacity: 0; transform: scale(0.94) translateY(-8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}

.week-menu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: #0f172a;
  font-size: 0.88rem;
}

.week-menu-head button {
  border: 1px solid var(--minimal-border);
  border-radius: 10px;
  padding: 6px 12px;
  background: var(--minimal-bg-surface);
  color: var(--minimal-text-primary);
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.week-menu-head button:hover {
  background: var(--minimal-border);
}

.week-menu-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  max-height: min(62vh, 430px);
  overflow: auto;
  padding: 2px;
}

.week-option {
  min-width: 0;
  min-height: 68px;
  padding: 8px 6px;
  border: 1px solid rgba(255, 255, 255, 0.65);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.52);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  color: #1e293b;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(50, 75, 110, 0.05), inset 0 1px 0.5px #fff;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.week-option:hover {
  transform: translateY(-2px);
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 6px 14px rgba(50, 75, 110, 0.12), inset 0 1px 0.5px #fff;
}

.week-option b, .week-option small {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.week-option b {
  font-size: 0.84rem;
  line-height: 1.3;
}

.week-option small {
  margin-top: 4px;
  color: #64748b;
  font-size: 0.66rem;
}

.week-option.selected {
  border-color: #111827;
  background: #111827;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(17, 24, 39, 0.22);
}

.week-option.selected small {
  color: rgba(255, 255, 255, 0.7);
}

.reset-week {
  min-width: 76px;
  height: 42px;
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--minimal-text-primary);
  background: #FFFFFF;
  border: 1px solid var(--minimal-border);
  border-radius: var(--minimal-radius-pill);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  box-shadow: none;
  transition: all 0.15s ease;
}

.reset-week:hover {
  background: var(--minimal-bg-surface);
}

.reset-week.active {
  background: #111827 !important;
  color: #FFFFFF !important;
  border-color: #111827 !important;
  box-shadow: 0 2px 8px rgba(17, 24, 39, 0.15) !important;
}

html[data-bg="night"] .reset-week {
  background: #1e293b;
  border-color: var(--minimal-border);
  color: var(--minimal-text-primary);
}

html[data-bg="night"] .reset-week.active {
  background: #38bdf8 !important;
  color: #0b0f17 !important;
  border-color: #38bdf8 !important;
}


.preview-modal {
  width: min(440px, 100%);
}

.preview-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 18px 0 20px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.55);
}

.preview-details > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.88rem;
}

.preview-details span {
  color: #64748b;
  flex-shrink: 0;
}

.preview-details b {
  color: #0f172a;
  text-align: right;
  word-break: break-word;
}

.color-preview {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.color-preview i {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.8), 0 2px 4px rgba(0, 0, 0, 0.15);
}

.import-setup {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}

.import-file {
  margin: 0;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.45);
  color: #0f172a;
  font-size: 0.86rem;
  font-weight: 600;
  word-break: break-all;
}

.import-inline-error {
  margin: 0;
  color: #e11d48;
  font-size: 0.8rem;
}

.import-help {
  margin: 0;
  color: #64748b;
  font-size: 0.78rem;
  line-height: 1.5;
}

.auth-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 18px;
}

.auth-card {
  width: min(400px, 100%);
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  color: #0f172a;
  font-size: 1.05rem;
}

.auth-head h2 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.auth-head p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.85rem;
}

.auth-form label {
  display: block;
  margin: 16px 0 0;
  color: #475569;
  font-size: 0.82rem;
  font-weight: 500;
}

.auth-error {
  margin: 14px 0 0;
  color: #e11d48;
  font-size: 0.8rem;
}

.auth-submit {
  width: 100%;
  margin-top: 20px;
  padding: 13px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #ffffff !important;
  background: #0f172a !important;
  border-radius: 9999px !important;
  border: none !important;
}

.auth-submit:hover {
  background: #1e293b !important;
  color: #ffffff !important;
}

.auth-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.auth-switch {
  margin: 18px 0 0;
  text-align: center;
  color: #64748b;
  font-size: 0.84rem;
}

.auth-switch button {
  border: 0;
  background: none;
  padding: 0 2px;
  color: #0284c7;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
}

.auth-switch button:hover {
  text-decoration: underline;
}

.header-action.logout {
  padding: 12px 18px;
}

html[data-bg="night"] .week-trigger {
  color: #f8fafc;
}

html[data-bg="night"] .week-trigger small,
html[data-bg="night"] .week-trigger i {
  color: #94a3b8;
}

html[data-bg="night"] .week-menu-head b,
html[data-bg="night"] .preview-details b,
html[data-bg="night"] .import-file,
html[data-bg="night"] .auth-brand,
html[data-bg="night"] .auth-head h2 {
  color: #f8fafc;
}

html[data-bg="night"] .week-option {
  background: rgba(15, 23, 42, 0.45);
  border-color: rgba(148, 163, 184, 0.22);
  color: #f1f5f9;
}

html[data-bg="night"] .week-option:hover {
  background: rgba(30, 41, 59, 0.7);
}

html[data-bg="night"] .week-option.selected {
  border-color: #f1f5f9;
  background: #f1f5f9;
  color: #0f172a;
}

html[data-bg="night"] .preview-details,
html[data-bg="night"] .import-file {
  background: rgba(15, 23, 42, 0.42);
  border-color: rgba(148, 163, 184, 0.2);
}

html[data-bg="night"] .user-badge {
  color: #f1f5f9;
  background: rgba(15, 23, 42, 0.32);
  border-color: rgba(148, 163, 184, 0.25);
}

@media (max-width: 680px) {
  .term-picker {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    gap: 6px;
    box-sizing: border-box;
    min-width: 0;
  }
  .term-picker p {
    margin: 0;
    font-size: 0.72rem;
    color: #94a3b8;
    white-space: nowrap;
  }
  .term-select-wrap {
    padding: 2px 6px;
    max-width: calc(100vw - 90px);
    border-radius: 8px;
  }
  .term-select-wrap select {
    max-width: calc(100vw - 110px);
    font-size: 0.86rem;
    padding: 2px 16px 2px 2px;
  }
  .week-picker {
    width: 100%;
    gap: 3px;
    justify-content: space-between;
    box-sizing: border-box;
    min-width: 0;
  }
  .week-menu {
    flex: 1;
    min-width: 0;
    position: relative;
  }
  .week-trigger {
    height: 28px;
    padding: 2px 6px;
    border-radius: 20px;
    gap: 4px;
    box-sizing: border-box;
    width: 100%;
  }
  .week-trigger b {
    font-size: 0.74rem;
    line-height: 1.15;
  }
  .week-trigger small {
    font-size: 0.55rem;
    line-height: 1.1;
    letter-spacing: -0.2px;
  }
  .week-trigger i {
    font-size: 0.82rem;
  }

  .week-menu-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 5px;
  }
  .week-option {
    min-height: 42px;
    padding: 3px 2px;
    border-radius: 12px;
  }
  .week-option b {
    font-size: 0.72rem;
  }
  .week-option small {
    font-size: 0.52rem;
  }
  .reset-week {
    height: 28px;
    min-width: auto;
    padding: 0 7px;
    font-size: 0.70rem;
    border-radius: 20px;
    flex-shrink: 0;
    white-space: nowrap;
  }
  .week-nav {
    height: 28px;
    width: 26px;
    flex: 0 0 26px;
    border-radius: 20px;
    font-size: 0.88rem;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
}

@media (max-width: 360px) {
  .reset-week {
    padding: 0 5px;
    font-size: 0.66rem;
    letter-spacing: -0.2px;
  }
}

.splash-fade-leave-active {
  transition: opacity 0.4s cubic-bezier(0.25, 1, 0.5, 1), transform 0.4s cubic-bezier(0.25, 1, 0.5, 1);
}
.splash-fade-leave-to {
  opacity: 0;
  transform: scale(1.02);
}

/* 离线模式横幅 */
.offline-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 auto 10px;
  padding: 7px 14px;
  width: fit-content;
  border: 1px solid rgba(251, 191, 36, 0.35);
  border-radius: 999px;
  background: rgba(254, 243, 199, 0.85);
  color: #92400e;
  font-size: 12px;
  font-weight: 600;
}

.offline-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.18);
}

.offline-retry {
  margin-left: 2px;
  padding: 3px 10px;
  border: 0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  color: #92400e;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.offline-retry:active {
  transform: scale(0.96);
}
</style>
