const $ = id => document.getElementById(id)
const state = { token: sessionStorage.getItem('admin_token') || '', page: 'overview', feedback: [], usersPage: 1, usersQuery: '' }
const labels = { pending: '待处理', processing: '处理中', resolved: '已解决', closed: '已关闭' }
const weekdays = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']
const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]))
const timeText = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'

function toast(message) { const el = $('toast'); el.textContent = message; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 1800) }
function logout() { state.token = ''; sessionStorage.removeItem('admin_token'); $('appView').classList.add('hidden'); $('loginView').classList.remove('hidden') }
async function api(path, options = {}) {
  const response = await fetch(`/api/admin${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}), ...(options.headers || {}) } })
  const data = response.status === 204 ? null : await response.json().catch(() => ({}))
  if (response.status === 401 && path !== '/login') { logout(); throw new Error('管理登录已过期') }
  if (!response.ok) throw new Error((data.detail?.message || (typeof data.detail === 'string' ? data.detail : '请求失败')))
  return data
}

function stat(label, value, suffix = '') { return `<div class="glass stat"><small>${label}</small><strong>${esc(value)}${suffix}</strong></div>` }
async function loadOverview() {
  $('overviewPage').innerHTML = '<div class="empty">正在读取运行数据…</div>'
  const data = await api('/overview'); const t = data.totals, m = data.traffic
  $('overviewPage').innerHTML = `<div class="stats">${stat('累计用户',t.users)}${stat('24h 活跃',t.active_users)}${stat('课表总数',t.schedules)}${stat('待处理反馈',t.open_feedback)}</div><div class="grid-2"><div class="glass panel"><h2>最近 24 小时</h2><div class="metric-row"><span>API 请求</span><b>${m.requests}</b></div><div class="metric-row"><span>错误率</span><b class="${Number(m.error_rate)>1?'bad':'good'}">${m.error_rate}%</b></div><div class="metric-row"><span>平均响应</span><b>${m.avg_ms} ms</b></div><div class="metric-row"><span>P95 响应</span><b>${m.p95_ms} ms</b></div></div><div class="glass panel"><h2>服务概况</h2><div class="metric-row"><span>助手绑定</span><b>${t.agent_bindings}</b></div><div class="metric-row"><span>待处理</span><b>${data.feedback.pending||0}</b></div><div class="metric-row"><span>处理中</span><b>${data.feedback.processing||0}</b></div><div class="metric-row"><span>已解决</span><b>${data.feedback.resolved||0}</b></div></div></div>`
}

async function loadFeedback() {
  const params = new URLSearchParams({ status: $('feedbackStatus').value, category: $('feedbackCategory').value, search: $('feedbackSearch').value.trim() })
  state.feedback = await api(`/feedback?${params}`)
  $('feedbackList').innerHTML = state.feedback.length ? state.feedback.map(item => `<article class="glass feedback-card" data-id="${item.id}"><div class="feedback-head"><span class="feedback-no">${esc(item.feedback_no)}</span><span class="tag ${item.status}">${labels[item.status]||item.status}</span></div><p>${esc(item.description)}</p><div class="meta">${esc(item.category_label)} · ${timeText(item.created_at)}${item.schedule_term?' · '+esc(item.schedule_term):''}</div></article>`).join('') : '<div class="glass empty">没有符合条件的反馈</div>'
}
function openFeedback(id) {
  const item = state.feedback.find(row => row.id === Number(id)); if (!item) return
  const client = item.client_info || {}
  $('feedbackDetail').innerHTML = `<p class="eyebrow">${esc(item.feedback_no)}</p><h2>${esc(item.category_label)}反馈</h2><p class="meta">提交于 ${timeText(item.created_at)}${item.schedule_term?' · '+esc(item.schedule_term):''}</p><div class="detail-desc">${esc(item.description)}</div><div class="metric-row"><span>联系邮箱</span><b>${esc(item.contact||'未填写')}</b></div><div class="metric-row"><span>客户端</span><b>${esc([client.platform,client.system,client.wechat_version].filter(Boolean).join(' / ')||'未记录')}</b></div><label>内部处理备注<textarea id="detailNote" rows="5" maxlength="1000">${esc(item.admin_note||'')}</textarea></label><div class="dialog-actions"><select id="detailStatus"><option value="pending">待处理</option><option value="processing">处理中</option><option value="resolved">已解决</option><option value="closed">已关闭</option></select><button id="saveFeedback" type="button" class="save">保存处理结果</button></div>`
  $('detailStatus').value = item.status; $('saveFeedback').onclick = () => saveFeedback(item.id); $('feedbackDialog').showModal()
}
async function saveFeedback(id) {
  await api(`/feedback/${id}`, { method: 'PATCH', body: JSON.stringify({ status: $('detailStatus').value, admin_note: $('detailNote').value }) })
  $('feedbackDialog').close(); await loadFeedback(); toast('反馈状态已保存')
}

async function loadTraffic() {
  $('trafficPage').innerHTML = '<div class="empty">正在汇总流量…</div>'
  const data = await api('/traffic?hours=24'); const max = Math.max(1, ...data.timeline.map(x => Number(x.requests)))
  const bars = data.timeline.map(x => { const h=Math.max(5,Number(x.requests)/max*100), e=Number(x.requests)?Number(x.errors)/Number(x.requests)*100:0; return `<i class="bar" style="height:${h}%;--error:${e}%" title="${timeText(x.bucket)} · ${x.requests} 次"></i>` }).join('')
  const paths = data.paths.map(x => `<div class="path-row"><span>${esc(x.path)}</span><b>${x.requests} 次 · ${x.avg_ms} ms</b></div>`).join('') || '<div class="empty">暂无请求数据</div>'
  const errors = data.recent_errors.map(x => `<div class="path-row"><span><b class="bad">${x.status}</b> ${esc(x.method)} ${esc(x.path)}</span><small>${timeText(x.created_at)}</small></div>`).join('') || '<div class="empty">最近 24 小时没有接口错误</div>'
  $('trafficPage').innerHTML = `<div class="glass panel"><h2>24 小时请求趋势 <small class="meta">蓝色为请求，红色为错误占比</small></h2><div class="bars">${bars||'<div class="empty">暂无请求数据</div>'}</div></div><div class="grid-2"><div class="glass panel"><h2>访问最多的接口</h2>${paths}</div><div class="glass panel"><h2>最近错误</h2>${errors}</div></div>`
}

async function loadLlm() {
  $('llmConfigList').innerHTML = '<div class="empty">正在加载模型配置…</div>'
  const list = await api('/llm-configs')
  const scopeDesc = {
    schedule_import: '解析用户上传的 Excel 课表，输出结构化课程 JSON。长上下文，单次响应需输出全表。',
    adjustment_vision: '识别教务处或班群调课通知截图，配对提取调整前与调整后课程。多模态视觉模型。',
    agent: '课表助手主模型，负责理解用户意图、规划查课逻辑并提取时间参数。高频低延迟。',
    polish: '口语化润色模板回答与友好闲聊，语气亲切温和。需极短延迟与严格接地校验。'
  }
  $('llmConfigList').innerHTML = list.map(item => {
    const isDb = item.source === 'database'
    const keyPlaceholder = item.api_key_configured ? `不填写使用默认配置 (${esc(item.api_key_hint)})` : '不填写使用默认配置'
    return `<article class="glass llm-card" data-scope="${esc(item.scope)}">
      <div class="llm-card-header">
        <div>
          <h3>${esc(item.label)} <code class="scope-badge">${esc(item.scope)}</code></h3>
          <p class="meta">${esc(scopeDesc[item.scope] || '')}</p>
        </div>
        <span class="tag ${isDb ? 'processing' : 'closed'}">${isDb ? '自定义配置' : '系统默认'}</span>
      </div>
      <form class="llm-form" onsubmit="event.preventDefault()">
        <label>接口地址 (Base URL)
          <input name="base_url" value="${esc(item.base_url || '')}" placeholder="https://api.openai.com/v1" required>
        </label>
        <label>模型名称 (Model)
          <input name="model" value="${esc(item.model || '')}" placeholder="例如 qwen-plus 或 gpt-4o-mini" required>
        </label>
        <label>API Key <small class="meta">（不填写默认配置）</small>
          <input name="api_key" type="password" placeholder="${keyPlaceholder}" autocomplete="off">
        </label>
        ${isDb && item.api_key_configured ? `<label class="checkbox-row"><input type="checkbox" name="clear_api_key"> <span>清除自定义 Key（恢复默认）</span></label>` : ''}
        <div class="form-grid-3">
          <label>超时时间 (秒)
            <input name="timeout_seconds" type="number" step="1" min="2" max="120" value="${esc(item.timeout_seconds)}">
          </label>
          <label>最大 Token (Max Tokens)
            <input name="max_tokens" type="number" step="10" min="50" max="16000" value="${esc(item.max_tokens)}">
          </label>
          <label class="checkbox-label">
            <span>启用思考模型 (Thinking)</span>
            <input name="enable_thinking" type="checkbox" ${item.enable_thinking ? 'checked' : ''}>
          </label>
        </div>
        <div class="llm-test-result" id="testResult_${esc(item.scope)}"></div>
        <div class="llm-actions">
          <button type="button" class="ghost btn-test" onclick="testLlm('${esc(item.scope)}')">测试连接</button>
          <button type="button" class="save btn-save" onclick="saveLlm('${esc(item.scope)}')">保存配置</button>
          ${isDb ? `<button type="button" class="ghost btn-reset" onclick="resetLlm('${esc(item.scope)}')">恢复默认</button>` : ''}
        </div>
      </form>
    </article>`
  }).join('')
}

async function testLlm(scope) {
  const card = document.querySelector(`.llm-card[data-scope="${scope}"]`)
  const resultEl = $(`testResult_${scope}`)
  if (!card || !resultEl) return
  const form = card.querySelector('form')
  const baseUrl = form.base_url.value.trim()
  const model = form.model.value.trim()
  const apiKey = form.api_key.value.trim() || undefined
  const enableThinking = form.enable_thinking.checked
  const timeoutSeconds = parseFloat(form.timeout_seconds.value) || 10
  resultEl.className = 'llm-test-result loading'
  resultEl.textContent = '正在发起测试连接…'
  try {
    const res = await api(`/llm-configs/${scope}/test`, {
      method: 'POST',
      body: JSON.stringify({ base_url: baseUrl, model, api_key: apiKey, enable_thinking: enableThinking, timeout_seconds: timeoutSeconds })
    })
    if (res.ok) {
      resultEl.className = 'llm-test-result good'
      resultEl.textContent = `✓ 连通成功！模型响应正常，耗时 ${res.latency_ms} ms`
    } else {
      resultEl.className = 'llm-test-result bad'
      resultEl.textContent = `✗ 连通失败：${res.error || '未知错误'}`
    }
  } catch (error) {
    resultEl.className = 'llm-test-result bad'
    resultEl.textContent = `✗ 测试请求异常：${error.message}`
  }
}

async function saveLlm(scope) {
  const card = document.querySelector(`.llm-card[data-scope="${scope}"]`)
  if (!card) return
  const form = card.querySelector('form')
  const baseUrl = form.base_url.value.trim()
  const model = form.model.value.trim()
  const apiKey = form.api_key.value.trim()
  const clearApiKey = form.clear_api_key ? form.clear_api_key.checked : false
  const timeoutSeconds = parseFloat(form.timeout_seconds.value) || 30
  const maxTokens = parseInt(form.max_tokens.value, 10) || 1000
  const enableThinking = form.enable_thinking.checked
  if (!baseUrl) { toast('请填写接口地址'); return }
  if (!model) { toast('请填写模型名称'); return }
  try {
    await api(`/llm-configs/${scope}`, {
      method: 'PUT',
      body: JSON.stringify({
        base_url: baseUrl,
        model: model,
        api_key: apiKey || null,
        clear_api_key: clearApiKey,
        timeout_seconds: timeoutSeconds,
        max_tokens: maxTokens,
        enable_thinking: enableThinking
      })
    })
    toast('大模型配置已保存并生效')
    await loadLlm()
  } catch (error) {
    toast(error.message)
  }
}

async function resetLlm(scope) {
  if (!confirm('确定将该模型配置恢复为系统环境变量默认值吗？')) return
  try {
    await api(`/llm-configs/${scope}`, { method: 'DELETE' })
    toast('已恢复为系统默认配置')
    await loadLlm()
  } catch (error) {
    toast(error.message)
  }
}

async function loadAdmins() {
  $('adminsList').innerHTML = '<div class="empty">正在加载管理员列表…</div>'
  const list = await api('/admins')
  const myUser = sessionStorage.getItem('admin_user') || ''
  $('adminsList').innerHTML = list.map(item => {
    const isMe = item.username === myUser
    const canDelete = !item.is_system_root && !isMe
    return `<article class="glass stat admin-card">
      <div class="admin-card-header">
        <span class="admin-username">${esc(item.username)}</span>
        <span class="tag ${item.role === 'superadmin' ? 'processing' : 'closed'}">${item.role === 'superadmin' ? '超级管理员' : '普通管理员'}</span>
      </div>
      <div class="meta mt-8">创建人：${esc(item.created_by || '系统')}</div>
      <div class="meta">创建时间：${timeText(item.created_at)}</div>
      <div class="admin-tags-row">
        ${item.is_system_root ? '<span class="tag pending">环境变量根账号</span>' : ''}
        ${isMe ? '<span class="tag good">当前登录账号</span>' : ''}
      </div>
      ${canDelete ? `<button type="button" class="danger-btn" onclick="deleteAdmin(${item.id}, '${esc(item.username)}')">删除账号</button>` : ''}
    </article>`
  }).join('')
}

async function deleteAdmin(id, username) {
  if (!confirm(`确定要移除管理员账号「${username}」吗？`)) return
  try {
    await api(`/admins/${id}`, { method: 'DELETE' })
    toast(`管理员 ${username} 已移除`)
    await loadAdmins()
  } catch (error) {
    toast(error.message)
  }
}

async function loadUsers(page = 1) {
  state.usersPage = page
  $('usersList').innerHTML = '<div class="empty">正在加载用户列表…</div>'
  $('usersPagination').innerHTML = ''
  const limit = 20
  const offset = (page - 1) * limit
  const query = state.usersQuery || ''
  try {
    const data = await api(`/users?query=${encodeURIComponent(query)}&limit=${limit}&offset=${offset}`)
    const items = data.items || []
    if (!items.length) {
      $('usersList').innerHTML = '<div class="glass empty" style="grid-column:1/-1;">未检索到符合条件的用户或课表（支持输入用户ID、邮箱、用户名、微信OpenID、课表名或课程名）</div>'
      return
    }
    $('usersList').innerHTML = items.map(user => {
      const providers = (user.providers || []).map(p => `<span class="provider-badge ${esc(p)}">${esc(p)}</span>`).join('')
      const displayName = user.username || user.nickname || (user.openid ? '微信用户 ' + user.openid.slice(-6) : '用户 #' + user.id)
      return `<article class="glass user-card" onclick="openUserDetail(${user.id})">
        <div class="user-card-head">
          <span class="user-uid">UID: ${user.id}</span>
          <span class="tag ${user.schedule_count > 0 ? 'good' : 'closed'}">${user.schedule_count} 张课表</span>
        </div>
        <div class="user-name">${esc(displayName)}</div>
        <div class="meta user-email">邮箱：${esc(user.email || '未绑定')}</div>
        ${user.openid ? `<div class="meta user-openid">OpenID：<code>${esc(user.openid)}</code></div>` : ''}
        <div class="user-providers">${providers || '<span class="meta">无关联三方身份</span>'}</div>
        <div class="meta user-time">注册时间：${timeText(user.created_at)}</div>
      </article>`
    }).join('')

    const total = data.total || 0
    const totalPages = Math.ceil(total / limit)
    if (totalPages > 1) {
      let pagerHtml = `<span class="meta">共 ${total} 位用户，第 ${page}/${totalPages} 页</span>`
      if (page > 1) {
        pagerHtml += `<button type="button" class="ghost" onclick="loadUsers(${page - 1})">上一页</button>`
      }
      if (page < totalPages) {
        pagerHtml += `<button type="button" class="ghost" onclick="loadUsers(${page + 1})">下一页</button>`
      }
      $('usersPagination').innerHTML = pagerHtml
    }
  } catch (error) {
    $('usersList').innerHTML = `<div class="empty bad" style="grid-column:1/-1;">读取用户失败: ${esc(error.message)}</div>`
  }
}

async function openUserDetail(userId) {
  $('userDetailContent').innerHTML = '<div class="empty">正在获取用户详情…</div>'
  $('userDetailDialog').showModal()
  try {
    const data = await api(`/users/${userId}/detail`)
    const u = data.user
    const identities = data.identities || []
    const schedules = data.schedules || []
    const bots = data.bots || data.agent_bindings || []
    const displayName = u.username || u.nickname || (u.openid ? '微信用户 ' + u.openid.slice(-6) : '用户 #' + u.id)

    const hasWechat = identities.some(i => i.provider === 'wechat') || Boolean(u.openid)
    const idCards = identities.map(i => `
      <div class="metric-row">
        <span><span class="provider-badge ${esc(i.provider)}">${esc(i.provider)}</span> 标识: <code>${esc(i.provider_user_id)}</code></span>
        <small>${timeText(i.created_at)}</small>
      </div>
    `).join('') || '<div class="meta" style="padding:8px 0;">无三方关联身份</div>'

    const botRows = bots.map(b => `
      <div class="metric-row">
        <span><b>${esc(b.provider)}</b> (${esc(b.account_id)})</span>
        <span class="tag ${b.status === 'active' || b.status === 'online' ? 'good' : 'bad'}">${esc(b.status)}</span>
      </div>
    `).join('') || '<div class="meta" style="padding:8px 0;">未绑定任何机器人通道</div>'

    const schedCards = schedules.map(s => `
      <div class="schedule-card">
        <div class="schedule-info">
          <div class="schedule-title">${esc(s.name)} ${s.is_active ? '<span class="tag good">当前主课表</span>' : ''}</div>
          <div class="meta mt-8">学期: ${esc(s.term || s.semester || '-')} · 起始日: ${esc(s.start_date || '-')} · ${s.course_count ?? '-'} 门课程</div>
        </div>
        <button type="button" class="save schedule-inspect-btn" onclick="viewScheduleCourses(${userId}, ${s.id})">透视课程清单</button>
      </div>
    `).join('') || '<div class="empty">该用户尚未创建任何课表</div>'

    $('userDetailContent').innerHTML = `
      <p class="eyebrow">USER PROFILE · UID ${u.id}</p>
      <div class="dialog-title-row">
        <h2>${esc(displayName)}</h2>
        ${hasWechat ? `<button type="button" class="danger-btn" onclick="unbindWechat(${u.id})">解绑微信 (解除账号锁定)</button>` : ''}
      </div>
      <div class="metric-row"><span>用户 ID</span><b>${u.id}</b></div>
      <div class="metric-row"><span>用户名</span><b>${esc(u.username || '未设置')}</b></div>
      <div class="metric-row"><span>绑定邮箱</span><b>${esc(u.email || '未绑定')}</b></div>
      <div class="metric-row"><span>微信 OpenID</span><b><code>${esc(u.openid || '未绑定')}</code></b></div>
      <div class="metric-row"><span>注册时间</span><b>${timeText(u.created_at)}</b></div>
      <div class="metric-row"><span>最近活跃</span><b>${timeText(u.last_login_at || u.updated_at)}</b></div>

      <h3 class="dialog-section-title">三方身份绑定 (${identities.length})</h3>
      ${idCards}

      <h3 class="dialog-section-title">微信/企微助手绑定 (${bots.length})</h3>
      ${botRows}

      <h3 class="dialog-section-title">用户课表数据 (${schedules.length})</h3>
      ${schedCards}
    `
  } catch (error) {
    $('userDetailContent').innerHTML = `<div class="empty bad">读取用户详情失败: ${esc(error.message)}</div>`
  }
}

async function unbindWechat(userId) {
  if (!confirm(`确定要解除 UID: ${userId} 的微信关联吗？\n解绑后该微信可绑定新账号，且原微信登录会话将立即失效。`)) return
  try {
    const res = await api(`/users/${userId}/unbind-wechat`, { method: 'POST' })
    toast(res.message || '微信已成功解绑')
    await openUserDetail(userId)
    await loadUsers(state.usersPage)
  } catch (error) {
    toast(error.message)
  }
}

async function viewScheduleCourses(userId, scheduleId) {
  $('coursesContent').innerHTML = '<div class="empty">正在透视课表课程…</div>'
  $('coursesDialog').showModal()
  try {
    const data = await api(`/users/${userId}/schedules/${scheduleId}/courses`)
    const sched = data.schedule
    const courses = data.courses || []

    const rows = courses.map((c, idx) => {
      const color = c.color || '#3b82f6'
      const wDay = weekdays[c.weekday] || `周${c.weekday}`
      const sec = c.start_section === c.end_section ? `第${c.start_section}节` : `第${c.start_section}-${c.end_section}节`
      const weeksStr = (c.weeks || []).join(',')
      return `<tr>
        <td>${idx + 1}</td>
        <td><span class="color-dot" style="background:${esc(color)};"></span><b>${esc(c.name)}</b></td>
        <td>${esc(c.teacher || '-')}</td>
        <td>${esc(c.room || '-')}</td>
        <td><span class="tag">${wDay}</span></td>
        <td>${sec}</td>
        <td><small class="meta">${esc(weeksStr)} 周</small></td>
      </tr>`
    }).join('')

    $('coursesContent').innerHTML = `
      <p class="eyebrow">SCHEDULE INSPECT</p>
      <div class="courses-dialog-head">
        <h2>${esc(sched.name)} <small class="meta">(${esc(sched.semester || '无学期')})</small></h2>
        <span class="meta">共 ${courses.length} 门课程明细 · 用户 UID: ${userId}</span>
      </div>
      <div class="courses-table-container">
        <table class="courses-table">
          <thead>
            <tr><th>#</th><th>课程名称</th><th>教师</th><th>教室地点</th><th>星期</th><th>节次</th><th>周次分布</th></tr>
          </thead>
          <tbody>
            ${rows || '<tr><td colspan="7" class="empty">当前课表下无课程记录</td></tr>'}
          </tbody>
        </table>
      </div>
    `
  } catch (error) {
    $('coursesContent').innerHTML = `<div class="empty bad">读取课程失败: ${esc(error.message)}</div>`
  }
}

async function loadSystemStatus() {
  const data = await api('/system/status')
  const r = data.redis || {}
  const connected = !!r.connected
  $('redisConnected').textContent = connected ? '正常运行 (Connected)' : '未连接 (内存降级模式)'
  $('redisConnected').className = connected ? 'good' : 'bad'
  $('redisStatusTag').textContent = connected ? '正常' : '降级'
  $('redisStatusTag').className = `tag ${connected ? 'good' : 'bad'}`
  $('redisVersion').textContent = r.version || '-'
  $('redisMemory').textContent = r.used_memory_human || '-'
  $('redisClients').textContent = r.connected_clients ?? '-'
  $('redisTotalKeys').textContent = r.total_keys ?? '-'
  $('redisUptime').textContent = r.uptime_days ? `${r.uptime_days} 天` : '-'
  $('sysServerTime').textContent = timeText(data.server_time)

  const bots = data.bots || []
  if (!bots.length) {
    $('botsList').innerHTML = '<div class="meta" style="padding:10px 0;">暂无接入的渠道账号</div>'
  } else {
    $('botsList').innerHTML = bots.map(b => `
      <div class="metric-row">
        <span><b>${esc(b.provider)}</b> (${esc(b.account_id)})</span>
        <span class="tag ${b.status === 'active' || b.status === 'online' ? 'good' : 'bad'}">${esc(b.status)}</span>
      </div>
    `).join('')
  }
}

async function clearRateLimit() {
  const input = $('ratelimitKeyInput')
  const key = input.value.trim()
  if (!key) {
    toast('请输入要解封的 IP 或 Key')
    return
  }
  if (!confirm(`确定要清除匹配「${key}」的限流计数吗？`)) return
  try {
    const res = await api('/system/redis/clear-ratelimit', {
      method: 'POST',
      body: JSON.stringify({ key })
    })
    toast(`已成功清除 ${res.deleted_count} 个限流键`)
    input.value = ''
  } catch (error) {
    toast(error.message)
  }
}

async function clearUserSession() {
  const input = $('sessionUserIdInput')
  const userId = parseInt(input.value.trim(), 10)
  if (!userId || userId <= 0) {
    toast('请输入合法的用户 ID')
    return
  }
  if (!confirm(`确定清除 UID: ${userId} 的所有 Redis 会话缓存吗？`)) return
  try {
    const res = await api('/system/redis/clear-session', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId })
    })
    toast(`已清除 ${res.cleared_count} 个会话缓存，用户需重新鉴权`)
    input.value = ''
  } catch (error) {
    toast(error.message)
  }
}

async function loadPage() {
  try {
    if (state.page === 'overview') await loadOverview()
    else if (state.page === 'users') await loadUsers(state.usersPage)
    else if (state.page === 'feedback') await loadFeedback()
    else if (state.page === 'traffic') await loadTraffic()
    else if (state.page === 'llm') await loadLlm()
    else if (state.page === 'system') await loadSystemStatus()
    else if (state.page === 'academic') await loadAcademicConnection()
    else if (state.page === 'academicSync') await loadAcademicSync()
    else if (state.page === 'admins') await loadAdmins()
  } catch (error) { toast(error.message) }
}
function switchPage(page) {
  state.page = page
  document.querySelectorAll('.nav').forEach(x => x.classList.toggle('active', x.dataset.page === page))
  document.querySelectorAll('.page').forEach(x => x.classList.add('hidden'))
  $(`${page}Page`).classList.remove('hidden')
  $('pageTitle').textContent = {
    academic: '学校教务连接',
    academicSync: '课表同步',
    overview: '运行概览',
    users: '用户与课表管理',
    feedback: '用户反馈',
    traffic: '流量监控',
    llm: '大模型配置',
    system: '系统运维与缓存',
    admins: '管理员管理'
  }[page] || '管理后台'
  loadPage()
}

$('loginForm').onsubmit = async event => {
  event.preventDefault(); $('loginError').textContent=''
  try {
    const data = await api('/login', { method: 'POST', body: JSON.stringify({ username: $('username').value, password: $('password').value }) })
    state.token = data.token
    sessionStorage.setItem('admin_token', data.token)
    sessionStorage.setItem('admin_user', data.username)
    $('loginView').classList.add('hidden'); $('appView').classList.remove('hidden'); loadPage()
  } catch(error) { $('loginError').textContent = error.message }
}

$('addAdminForm').onsubmit = async event => {
  event.preventDefault(); $('addAdminError').textContent = ''
  try {
    await api('/admins', {
      method: 'POST',
      body: JSON.stringify({
        username: $('newAdminUser').value.trim(),
        password: $('newAdminPass').value,
        role: $('newAdminRole').value
      })
    })
    $('adminDialog').close()
    $('newAdminUser').value = ''
    $('newAdminPass').value = ''
    toast('管理员创建成功')
    if (state.page === 'admins') await loadAdmins()
  } catch (error) {
    $('addAdminError').textContent = error.message
  }
}

$('openAddAdmin').onclick = () => { $('addAdminError').textContent = ''; $('adminDialog').showModal() }
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>switchPage(button.dataset.page))
$('logout').onclick=logout
$('refresh').onclick=loadPage
$('feedbackList').onclick=e=>{const card=e.target.closest('[data-id]');if(card)openFeedback(card.dataset.id)}
let searchTimer; $('feedbackSearch').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadFeedback,300)}
$('feedbackStatus').onchange=loadFeedback
$('feedbackCategory').onchange=loadFeedback

let userSearchTimer
if ($('userSearch')) {
  $('userSearch').oninput = () => {
    clearTimeout(userSearchTimer)
    userSearchTimer = setTimeout(() => {
      state.usersQuery = $('userSearch').value.trim()
      loadUsers(1)
    }, 300)
  }
  $('userSearch').onkeydown = e => {
    if (e.key === 'Enter') {
      e.preventDefault()
      clearTimeout(userSearchTimer)
      state.usersQuery = $('userSearch').value.trim()
      loadUsers(1)
    }
  }
}
if ($('userSearchForm')) {
  $('userSearchForm').onsubmit = e => {
    e.preventDefault()
    clearTimeout(userSearchTimer)
    state.usersQuery = $('userSearch').value.trim()
    loadUsers(1)
  }
}
$('btnSearchUser').onclick = () => {
  clearTimeout(userSearchTimer)
  state.usersQuery = $('userSearch').value.trim()
  loadUsers(1)
}
$('btnResetUser').onclick = () => {
  clearTimeout(userSearchTimer)
  $('userSearch').value = ''
  state.usersQuery = ''
  loadUsers(1)
}

$('ratelimitSubmitBtn').onclick = clearRateLimit
$('sessionSubmitBtn').onclick = clearUserSession

if(state.token){$('loginView').classList.add('hidden');$('appView').classList.remove('hidden');loadPage()}



let academicLoginTimer

function syncSummary(sync) {
  const counts = sync.counts || {}
  const paused = sync.pause_until && new Date(sync.pause_until) > new Date()
  return `课表同步：排队 ${counts.queued || 0} · 执行 ${counts.running || 0} · 成功 ${counts.succeeded || 0} · 失败 ${counts.failed || 0}。每天北京时间 00:00 发起；${paused ? '学校连接失效，等待管理员恢复。' : '依次处理，失败保留原课表。'}`
}

async function loadAcademicConnection() {
  clearTimeout(academicLoginTimer)
  const target = $('academicPage')
  target.innerHTML = '<div class="empty">正在检查教务连接…</div>'
  const [data, login] = await Promise.all([api('/academic/connection'), api('/academic/login/status')])
  const browser = data.browser || { state: 'not_started' }
  const labels = { connected: '浏览器会话可用', needs_login: '需要管理员重新登录', error: '浏览器检查失败', not_started: '会话维护进程未启动' }
  target.innerHTML = `<div class="glass panel academic-card">
    <div class="academic-header">
      <h2>连接学校账号</h2>
      <span class="tag ${login.saved ? 'good' : 'closed'}">${login.saved ? '已存凭据' : '未配置'}</span>
    </div>
    <div class="academic-status-box">
      <p id="schoolLoginStatus" class="academic-status-text">${esc(login.message)}</p>
      <p id="schoolCredentialsSummary" class="meta">${login.saved ? '手机号已加密保存 · ' + esc(login.account || '') : '保存学校绑定手机号后发起验证码登录。'}</p>
    </div>
    <form id="schoolCredentialsForm" class="academic-form">
      <div class="form-row-2">
        <label>学校绑定手机号<input id="schoolAccount" type="tel" autocomplete="tel" inputmode="numeric" pattern="1[0-9]{10}" maxlength="11" required value="${esc(login.account || '')}" placeholder="11 位手机号"></label>
      </div>
      <button class="save academic-btn-save" type="submit">保存手机号</button>
    </form>
    <div class="academic-actions-bar">
      <button id="schoolLoginStart" class="btn-primary" ${!login.saved || login.running ? 'disabled' : ''}>发起后台自动维护</button>
      <button id="schoolLoginVisible" class="btn-primary" ${login.running ? 'disabled' : ''} style="background:linear-gradient(135deg, #2563eb, #1d4ed8);">🖥️ 弹出可视浏览器登录（人工/扫码）</button>
      <button id="schoolLoginStop" class="btn-warning" ${!login.running ? 'disabled' : ''}>停止维护</button>
      <button id="schoolDeleteCredentials" class="btn-danger" ${!login.saved || login.running ? 'disabled' : ''}>删除手机号</button>
    </div>
    <div id="schoolCodePanel" class="school-code-box" ${['ready_for_code', 'waiting_code'].includes(login.state) ? '' : 'hidden'}>
      <div class="code-header">
        <span class="code-tip">学校要求安全验证码</span>
        <button id="schoolSendCode" class="ghost btn-code-send">获取验证码</button>
      </div>
      <form id="schoolCodeForm" class="code-form">
        <input id="schoolCode" type="text" autocomplete="one-time-code" maxlength="32" placeholder="收到验证码后输入">
        <button type="submit" class="save">提交验证码并登录</button>
      </form>
    </div>
    <p id="schoolLoginError" class="error"></p><div id="schoolDiagnostic" hidden><p class="meta">学校登录页面（输入内容已隐藏）</p><img id="schoolDiagnosticImage" style="max-width:100%;border-radius:12px" alt="学校当前登录页面"></div>
    <p class="meta school-notice">💡 <b>推荐方式</b>：点击「🖥️ 弹出可视浏览器登录」，可在桌面直接弹出 Chrome 窗口。请选择「验证码登录」，输入学校绑定手机号和短信验证码，再点击「统一认证登录」进入教务系统。登录成功后系统会自动捕获并同步会话！</p>
  </div>
  <details class="glass panel academic-advanced-panel">
    <summary class="advanced-summary">高级设置：手动配置 Cookie 与会话</summary>
    <div class="advanced-content">
      <h2>长沙工业学院教务连接</h2>
      <div class="metric-row"><span>会话状态</span><b>${esc(labels[browser.state] || browser.state)}${browser.checked_at ? ' · 最近检查 ' + esc(new Date(browser.checked_at).toLocaleString('zh-CN')) : ''}</b></div>
      <div class="metric-row"><span>年级信息</span><b>${data.connected ? '已连接 · 年级 ' + esc(data.grades.join('、')) : esc(data.message)}</b></div>
      <p class="meta mt-10">由超级管理员维护学校登录会话。普通用户使用序时账号查询课表，学校会话不会返回给用户。</p>
      <form id="academicConnectionForm" class="cookie-form mt-14">
        <label>教务 Cookie<input id="academicCookie" type="password" autocomplete="off" required maxlength="16000" placeholder="从已登录学校网页的请求头复制 Cookie"></label>
        <label>User-Agent<input id="academicAgent" maxlength="500" placeholder="对应浏览器 User-Agent" value="Mozilla/5.0"></label>
        <p class="meta mt-8">保存前验证连接；会话加密保存，过期后重新配置。更改 ADMIN_SESSION_SECRET 后需重新配置。</p>
        <button class="save mt-12" type="submit">验证并保存连接</button>
        <p id="academicConnectionError" class="error"></p>
      </form>
    </div>
  </details>`
  let latest = login
  let diagnosticUrl = null
  let diagnosticState = null
  async function refreshLogin() {
    clearTimeout(academicLoginTimer)
    if (state.page !== 'academic') return
    try {
      latest = await api('/academic/login/status')
      if (state.page !== 'academic' || !$('schoolLoginStatus')) return
      const previousState = $('schoolLoginStatus').dataset.state
      $('schoolLoginStatus').dataset.state = latest.state
      $('schoolLoginStatus').style.color = latest.state === 'connected' ? '#16804a' : ''
      if (latest.state === 'connected' && previousState !== 'connected') toast('学校账号连接成功，自动维护已启动')
      if (latest.diagnostic && diagnosticState !== latest.state) {
        diagnosticState = latest.state
        const response = await fetch('/api/admin/academic/login/diagnostic', { headers: { Authorization: 'Bearer ' + state.token } })
        if (response.ok && $('schoolDiagnosticImage')) {
          if (diagnosticUrl) URL.revokeObjectURL(diagnosticUrl)
          diagnosticUrl = URL.createObjectURL(await response.blob())
          $('schoolDiagnosticImage').src = diagnosticUrl
          $('schoolDiagnostic').hidden = false
        }
      }
      $('schoolLoginStatus').textContent = latest.message + (latest.page_host ? ' · 当前页面：' + latest.page_host : '') + (latest.checked_at ? ' · ' + new Date(latest.checked_at).toLocaleString('zh-CN') : '')
      $('schoolCredentialsSummary').textContent = latest.saved ? '手机号已加密保存 · ' + (latest.account || '') : '保存学校绑定手机号后发起验证码登录。'
      $('schoolCodeForm').querySelector('button').disabled = latest.state !== 'waiting_code'
      $('schoolCodePanel').hidden = !['ready_for_code', 'waiting_code', 'processing', 'submitting', 'continuing'].includes(latest.state)
      $('schoolLoginStart').disabled = !latest.saved || latest.running
      if ($('schoolLoginVisible')) $('schoolLoginVisible').disabled = latest.running
      $('schoolLoginStop').disabled = !latest.running
      $('schoolDeleteCredentials').disabled = !latest.saved || latest.running
      $('schoolCredentialsForm').querySelector('button').disabled = latest.running
      $('schoolSendCode').disabled = latest.state !== 'ready_for_code' && latest.state !== 'waiting_code'
    } catch (e) { if ($('schoolLoginError')) $('schoolLoginError').textContent = e.message }
    if (state.page === 'academic') academicLoginTimer = setTimeout(refreshLogin, 2000)
  }
  async function loginAction(path, options) {
    $('schoolLoginError').textContent = ''
    try { await api('/academic/login/' + path, options); await refreshLogin() }
    catch (e) { $('schoolLoginError').textContent = e.message }
  }
  $('schoolCredentialsForm').onsubmit = async event => {
    event.preventDefault()
    const account = $('schoolAccount').value.trim()
    await loginAction('credentials', { method: 'PUT', body: JSON.stringify({ account }) })
  }
  $('schoolLoginStart').onclick = () => loginAction('start', { method: 'POST' })
  if ($('schoolLoginVisible')) {
    $('schoolLoginVisible').onclick = async () => {
      await loginAction('start?visible=true', { method: 'POST' })
      toast('已在桌面弹出浏览器窗口，请在窗口中登录')
    }
  }
  $('schoolLoginStop').onclick = () => loginAction('command', { method: 'POST', body: JSON.stringify({ job_id: latest.job_id, action: 'stop' }) })
  $('schoolDeleteCredentials').onclick = () => loginAction('credentials', { method: 'DELETE' })
  $('schoolSendCode').onclick = () => loginAction('command', { method: 'POST', body: JSON.stringify({ job_id: latest.job_id, action: 'send_code' }) })
  $('schoolCodeForm').onsubmit = async event => {
    event.preventDefault()
    const code = $('schoolCode').value
    $('schoolCode').value = ''
    await loginAction('command', { method: 'POST', body: JSON.stringify({ job_id: latest.job_id, action: 'submit_code', code }) })
  }
  await refreshLogin()
  $('academicConnectionForm').onsubmit = async event => {
    event.preventDefault()
    const button = event.target.querySelector('button')
    button.disabled = true
    try {
      await api('/academic/connection', { method: 'PUT', body: JSON.stringify({ cookie: $('academicCookie').value, user_agent: $('academicAgent').value || 'Mozilla/5.0' }) })
      $('academicCookie').value = ''
      toast('教务连接已保存')
      await loadAcademicConnection()
    } catch (e) { $('academicConnectionError').textContent = e.message }
    finally { button.disabled = false }
  }
}


let academicSyncTimer
let academicSyncRevision = 0
async function loadAcademicSync() {
  clearTimeout(academicSyncTimer)
  const current = ++academicSyncRevision
  const target = $('academicSyncPage')
  target.innerHTML = `<div class="glass panel"><h2>课表同步</h2><p class="meta">每天北京时间 00:00 自动发起。主动同步会为全部已绑定账号刷新课表，已有任务的账号自动跳过。</p><p class="meta">同步成功后只留一份学校课表，覆盖导入内容和个人修改；失败保留原课表。</p><button id="startAllSchoolSync" class="save">立即同步全部已绑定账号</button><p id="allSchoolSyncMessage" role="status" class="meta"></p><p id="allSchoolSyncError" role="alert" class="error"></p></div><div id="allSchoolSyncStats"></div><div class="glass panel"><h2>最近 30 个任务</h2><div id="allSchoolSyncJobs"></div></div>`
  target.insertAdjacentHTML('afterbegin', `<div class="glass panel"><h2>学生目录</h2><p class="meta">完整名单同步成功后，身份搜索直接查询本地目录。刷新失败保留原名单；首次同步前使用学校实时搜索。</p><button id="refreshStudentDirectory" class="save">刷新完整学生名单</button><p id="studentDirectoryStatus" role="status" class="meta"></p><p id="studentDirectoryError" role="alert" class="error"></p></div>`)
  $('refreshStudentDirectory').onclick = async () => {
    $('refreshStudentDirectory').disabled = true
    try { await api('/academic/directory/refresh', { method: 'POST' }); await refreshSync() }
    catch (e) { if (current === academicSyncRevision && state.page === 'academicSync') { $('studentDirectoryError').textContent = e.message; $('refreshStudentDirectory').disabled = false } }
  }
  async function refreshSync() {
    if (state.page !== 'academicSync' || current !== academicSyncRevision) return
    try {
      const [data, directory] = await Promise.all([api('/academic/sync/status'), api('/academic/directory/status')])
      if (state.page !== 'academicSync' || current !== academicSyncRevision) return
      const directoryStates = { idle: '尚未同步', queued: '等待同步', running: '正在同步', succeeded: '同步成功', failed: '同步失败' }
      $('studentDirectoryStatus').textContent = `${directoryStates[directory.state] || directory.state} · 已保存 ${directory.student_count} 人 · 班级进度 ${directory.classes_done}/${directory.classes_total} · 最近成功：${timeText(directory.synced_at)}`
      $('studentDirectoryError').textContent = directory.error || ''
      $('refreshStudentDirectory').disabled = ['queued', 'running'].includes(directory.state)
      const counts = data.counts || {}
      $('allSchoolSyncStats').innerHTML = `<div class="stats">${stat('已绑定账号', data.bound_count)}${stat('排队', counts.queued || 0)}${stat('执行中', counts.running || 0)}${stat('成功（近 30 天）', counts.succeeded || 0)}${stat('失败（近 30 天）', counts.failed || 0)}</div><p class="meta">${esc(syncSummary(data))} 最近自动批次：${esc(data.last_daily_run?.run_date || '尚未生成')}</p>`
      const states = { queued: '排队中', running: '同步中', succeeded: '成功', failed: '失败' }
      const sources = { daily: '零点自动', manual: '用户发起', admin: '后台主动' }
      $('allSchoolSyncJobs').innerHTML = (data.recent || []).map(job => `<div class="path-row"><span><b>${esc(states[job.state] || job.state)}</b> · 用户 ${esc(job.user_id)} · ${esc(job.term)} · ${esc(sources[job.source] || job.source)}${job.error ? '<br><small class="bad">' + esc(job.error) + '</small>' : ''}</span><small>尝试 ${esc(job.attempts)} 次 · ${timeText(job.updated_at)}</small></div>`).join('') || '<div class="empty">暂无同步任务</div>'
    } catch (e) { if (current === academicSyncRevision && state.page === 'academicSync') $('allSchoolSyncError').textContent = e.message }
    if (state.page === 'academicSync' && current === academicSyncRevision) academicSyncTimer = setTimeout(refreshSync, 3000)
  }
  $('startAllSchoolSync').onclick = async () => {
    const button = $('startAllSchoolSync')
    button.disabled = true
    $('allSchoolSyncError').textContent = ''
    try {
      const result = await api('/academic/sync/start', { method: 'POST' })
      if (state.page !== 'academicSync' || current !== academicSyncRevision) return
      $('allSchoolSyncMessage').textContent = `已加入 ${result.enqueued} 个任务，跳过 ${result.skipped} 个已有任务或缺少学期的账号。任务依次处理，可离开此页面。`
      clearTimeout(academicSyncTimer)
      await refreshSync()
    } catch (e) { if (current === academicSyncRevision && state.page === 'academicSync') $('allSchoolSyncError').textContent = e.message }
    finally { if (current === academicSyncRevision) button.disabled = false }
  }
  await refreshSync()
}
