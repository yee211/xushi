/**
 * 前端统一 API 客户端与凭据管理模块。
 */

const TOKEN_KEY = 'token';
const ACTIVE_SCHEDULE_KEY = 'active_schedule_id';
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

function apiUrl(path) {
  return `${API_BASE_URL}${path}`;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function getActiveScheduleId() {
  const id = localStorage.getItem(ACTIVE_SCHEDULE_KEY);
  return id ? Number(id) : null;
}

export function setActiveScheduleId(id) {
  if (id) {
    localStorage.setItem(ACTIVE_SCHEDULE_KEY, String(id));
  } else {
    localStorage.removeItem(ACTIVE_SCHEDULE_KEY);
  }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ACTIVE_SCHEDULE_KEY);
}

function offlineError(message) {
  const error = new Error(message);
  error.offline = true;
  return error;
}

export async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(apiUrl(url), { ...options, headers });
  } catch (error) {
    if (error?.name === 'TimeoutError' || error?.name === 'AbortError') {
      throw offlineError('请求超时，服务端可能仍在处理，请稍后刷新课表确认');
    }
    throw offlineError('网络连接失败，请检查网络后重试');
  }
  let body = {};
  try {
    body = await response.json();
  } catch {
    // 允许空响应或非 JSON
  }

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      window.dispatchEvent(new CustomEvent('auth:expired'));
    }
    if (response.status >= 500) {
      // 服务端暂不可达：与断网同走离线兜底（区别于鉴权失败）
      throw offlineError(body.detail || '服务暂不可用，请稍后重试');
    }
    throw new Error(body.detail || '请求失败');
  }

  return response.status === 204 ? null : body;
}

export const authApi = {
  async register(data) {
    return api('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  async login(data) {
    return api('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  async me() {
    return api('/api/me');
  },
};

export const schedulesApi = {
  async list() {
    return api('/api/schedules');
  },
  async update(id, data) {
    return api(`/api/schedules/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  async ensureAdjusted(id) {
    return api(`/api/schedules/${id}/adjusted`, { method: 'POST' });
  },
  async delete(id) {
    return api(`/api/schedules/${id}`, { method: 'DELETE' });
  },
};

export const coursesApi = {
  async add(data) {
    return api('/api/courses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  async update(id, data, source = 'manual', linkAdjustments = false) {
    const params = new URLSearchParams();
    if (source) params.set('source', source);
    if (linkAdjustments) params.set('link_adjustments', 'true');
    const query = params.toString() ? `?${params.toString()}` : '';
    return api(`/api/courses/${id}${query}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  async delete(id) {
    return api(`/api/courses/${id}`, { method: 'DELETE' });
  },
  async adjust(id, week, data) {
    return api(`/api/courses/${id}/adjustments/${week}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
  async cancelAdjustment(id, week) {
    return api(`/api/courses/${id}/adjustments/${week}`, { method: 'DELETE' });
  },
};

export const adjustmentsApi = {
  async parse(file, scheduleId) {
    const form = new FormData();
    form.append('file', file);
    form.append('schedule_id', String(scheduleId));
    const signal = typeof AbortSignal !== 'undefined' && AbortSignal.timeout
      ? AbortSignal.timeout(30000)
      : undefined;
    return api('/api/adjustments/parse', { method: 'POST', body: form, signal });
  },
  async apply(scheduleId, items) {
    return api('/api/adjustments/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schedule_id: scheduleId, items }),
    });
  },
  async getRecords(scheduleId) {
    return api(`/api/adjustments/records?schedule_id=${encodeURIComponent(scheduleId)}`);
  },
  async deleteRecord(recordId) {
    return api(`/api/adjustments/records/${encodeURIComponent(recordId)}`, { method: 'DELETE' });
  },
  async revokeRecord(recordId) {
    return api(`/api/adjustments/records/${encodeURIComponent(recordId)}/revoke`, { method: 'POST' });
  },
};

export const importerApi = {
  async importFile(formData) {
    const signal = typeof AbortSignal !== 'undefined' && AbortSignal.timeout
      ? AbortSignal.timeout(75000)
      : undefined;
    return api('/api/import', {
      method: 'POST',
      body: formData,
      signal,
    });
  },
  async importHtml(payload) {
    const signal = typeof AbortSignal !== 'undefined' && AbortSignal.timeout
      ? AbortSignal.timeout(75000)
      : undefined;
    return api('/api/import-html', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
  },
};

export const appApi = {
  async getVersion() {
    return api('/api/app/version');
  },
};

export const feedbackApi = {
  async submit(data) {
    return api('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },
};
