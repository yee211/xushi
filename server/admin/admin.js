const $ = id => document.getElementById(id)
const state = { token: sessionStorage.getItem('admin_token') || '', page: 'overview', feedback: [], usersPage: 1, usersQuery: '', showUnbound: false }
const labels = { pending: '待处理', processing: '处理中', resolved: '已解决', closed: '已关闭' }
const weekdays = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']
const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]))
const timeText = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
const modules = {
  workspace: { title: '工作台', description: '关注系统运行情况与用户反馈', tabs: [['overview', '运行概览']] },
  users: { title: '用户管理', description: '查找用户、检查课表并跟进反馈', tabs: [['users', '用户列表'], ['feedback', '用户反馈']] },
  academic: { title: '教务管理', description: '维护学校连接、学生目录与课表同步', tabs: [['academic', '学校连接'], ['directory', '学生目录'], ['academicSync', '课表同步']] },
  ai: { title: 'AI 管理', description: '配置各业务场景的模型与接口', tabs: [['llm', '模型配置']] },
  system: { title: '系统管理', description: '检查服务与流量，管理运维操作和后台账号', tabs: [['system', '服务与缓存'], ['traffic', '流量与错误'], ['admins', '管理员账号']] }
}
const pageModule = page => Object.keys(modules).find(key => modules[key].tabs.some(tab => tab[0] === page))
function saveLocation() {
  const params = new URLSearchParams({ page: state.page })
  if (state.usersQuery) params.set('query', state.usersQuery)
  if (state.usersPage > 1) params.set('usersPage', state.usersPage)
  if (state.showUnbound) params.set('unbound', '1')
  if ($('feedbackSearch').value) params.set('search', $('feedbackSearch').value)
  if ($('feedbackStatus').value) params.set('status', $('feedbackStatus').value)
  if ($('feedbackCategory').value) params.set('category', $('feedbackCategory').value)
  history.replaceState(null, '', '#' + params.toString())
}
function restoreLocation() {
  const params = new URLSearchParams(location.hash.slice(1))
  state.usersQuery = params.get('query') || ''
  state.usersPage = Math.max(1, Number(params.get('usersPage')) || 1)
  state.showUnbound = params.get('unbound') === '1'
  $('userSearch').value = state.usersQuery
  $('showUnbound').checked = state.showUnbound
  $('feedbackSearch').value = params.get('search') || ''
  $('feedbackStatus').value = params.get('status') || ''
  $('feedbackCategory').value = params.get('category') || ''
  switchPage(pageModule(params.get('page')) ? params.get('page') : 'overview')
}

let toastTimer
function toast(message) { clearTimeout(toastTimer); const el = $('toast'); el.textContent = message; el.classList.add('show'); toastTimer = setTimeout(() => el.classList.remove('show'), 3500) }
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
  const hiddenNote = t.unbound_users > 0 ? `<div class="meta" style="margin-top:6px;">另有 ${t.unbound_users} 位仅微信静默登录的用户未计入（未绑定任何身份）</div>` : ''
  $('overviewPage').innerHTML = `<div class="stats">${stat('绑定用户',t.users)}${stat('24h 活跃',t.active_users)}${stat('课表总数',t.schedules)}${stat('待处理反馈',t.open_feedback)}</div>${hiddenNote}<div class="grid-2"><div class="glass panel"><h2>最近 24 小时</h2><div class="metric-row"><span>API 请求</span><b>${m.requests}</b></div><div class="metric-row"><span>错误率</span><b class="${Number(m.error_rate)>1?'bad':'good'}">${m.error_rate}%</b></div><div class="metric-row"><span>平均响应</span><b>${m.avg_ms} ms</b></div><div class="metric-row"><span>P95 响应</span><b>${m.p95_ms} ms</b></div></div><div class="glass panel"><h2>服务概况</h2><div class="metric-row"><span>助手绑定</span><b>${t.agent_bindings}</b></div><div class="metric-row"><span>待处理</span><b>${data.feedback.pending||0}</b></div><div class="metric-row"><span>处理中</span><b>${data.feedback.processing||0}</b></div><div class="metric-row"><span>已解决</span><b>${data.feedback.resolved||0}</b></div></div></div>`
}

async function loadFeedback() {
  saveLocation()
  const params = new URLSearchParams({ status: $('feedbackStatus').value, category: $('feedbackCategory').value, search: $('feedbackSearch').value.trim() })
  state.feedback = await api(`/feedback?${params}`)
  $('feedbackList').innerHTML = state.feedback.length ? `<table class="management-table"><thead><tr><th>反馈编号</th><th>反馈内容</th><th>类型</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead><tbody>${state.feedback.map(item => `<tr><td>${esc(item.feedback_no)}</td><td class="description-cell"><span>${esc(item.description)}</span><small class="cell-secondary">${esc(item.contact || '未留联系方式')}</small></td><td>${esc(item.category_label)}</td><td><span class="tag ${esc(item.status)}">${esc(labels[item.status] || item.status)}</span></td><td>${timeText(item.created_at)}</td><td><button type="button" class="ghost" data-id="${item.id}">处理反馈</button></td></tr>`).join('')}</tbody></table>` : '<div class="glass empty">没有符合条件的反馈</div>'
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
  const [data, agent] = await Promise.all([
    api('/traffic?hours=24'),
    api('/agent-stats?hours=24').catch(() => null)
  ])
  const max = Math.max(1, ...data.timeline.map(x => Number(x.requests)))
  const bars = data.timeline.map(x => { const h=Math.max(5,Number(x.requests)/max*100), e=Number(x.requests)?Number(x.errors)/Number(x.requests)*100:0; return `<i class="bar" style="height:${h}%;--error:${e}%" title="${timeText(x.bucket)} · ${x.requests} 次"></i>` }).join('')
  const paths = data.paths.map(x => `<div class="path-row"><span>${esc(x.path)}</span><b>${x.requests} 次 · ${x.avg_ms} ms</b></div>`).join('') || '<div class="empty">暂无请求数据</div>'
  const errors = data.recent_errors.map(x => `<div class="path-row"><span><b class="bad">${x.status}</b> ${esc(x.method)} ${esc(x.path)}</span><small>${timeText(x.created_at)}</small></div>`).join('') || '<div class="empty">最近 24 小时没有接口错误</div>'
  const t = agent && agent.totals
  let agentPanel = '<div class="glass panel"><h2>助手运行（近 24 小时）</h2><div class="empty">暂无助手运行数据</div></div>'
  if (t && Number(t.turns) > 0) {
    const pct = n => Math.round(Number(n) * 100 / Number(t.turns)) + '%'
    const prompt = Number(t.prompt_tokens), cached = Number(t.cached_tokens)
    const cacheHit = prompt > 0 ? Math.round(cached * 100 / prompt) + '%' : '-'
    const outcomeTags = (agent.outcomes || []).slice(0, 8).map(o =>
      `<span class="tag ${o.outcome === 'ok' ? 'closed' : 'bad'}">${esc(o.path)}/${esc(o.outcome)} ×${o.count}</span>`).join(' ')
    agentPanel = `<div class="glass panel"><h2>助手运行（近 24 小时） <small class="meta">LLM 直答 ${pct(t.llm_turns)} · 规则兜底 ${pct(t.fallback_turns)}</small></h2>
      <div class="metric-row"><span>处理消息</span><b>${t.turns} 轮（模型调用 ${t.llm_calls} 次）</b></div>
      <div class="metric-row"><span>异常轮次</span><b class="${Number(t.abnormal) > 0 ? 'bad' : 'good'}">${t.abnormal}</b></div>
      <div class="metric-row"><span>耗时</span><b>平均 ${t.avg_ms} ms · P95 ${t.p95_ms} ms</b></div>
      <div class="metric-row"><span>Token 消耗</span><b>输入 ${t.prompt_tokens} · 输出 ${t.completion_tokens}（前缀缓存命中 ${cacheHit}）</b></div>
      <div class="path-row"><span>${outcomeTags || '-'}</span></div></div>`
  }
  $('trafficPage').innerHTML = `<div class="glass panel"><h2>24 小时请求趋势 <small class="meta">蓝色为请求，红色为错误占比</small></h2><div class="bars">${bars||'<div class="empty">暂无请求数据</div>'}</div></div>${agentPanel}<div class="grid-2"><div class="glass panel"><h2>访问最多的接口</h2>${paths}</div><div class="glass panel"><h2>最近错误</h2>${errors}</div></div>`
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

let usersLoadRevision = 0
async function loadUsers(page = 1) {
  const revision = ++usersLoadRevision
  state.usersPage = page
  saveLocation()
  $('usersList').innerHTML = '<div class="empty">正在加载用户列表…</div>'
  $('usersPagination').innerHTML = ''
  const limit = 20
  const offset = (page - 1) * limit
  const query = state.usersQuery || ''
  try {
    const unboundParam = state.showUnbound ? '&include_unbound=true' : ''
    const data = await api(`/users?query=${encodeURIComponent(query)}&limit=${limit}&offset=${offset}${unboundParam}`)
    if (revision !== usersLoadRevision) return
    const items = data.items || []
    const hiddenNote = !state.showUnbound && data.unbound_total > 0
      ? `已隐藏 ${data.unbound_total} 位仅微信静默登录、未绑定任何身份的用户（勾选“显示未绑定”可查看）` : ''
    if (!items.length) {
      $('usersList').innerHTML = `<div class="glass empty" style="grid-column:1/-1;">${hiddenNote || '未检索到符合条件的用户（支持输入用户ID、邮箱、用户名、微信OpenID、课表名或课程名）'}</div>`
      $('usersPagination').innerHTML = hiddenNote ? `<span class="meta">${hiddenNote}</span>` : ''
      return
    }
    const rows = items.map(user => {
      const providers = (user.providers || []).map(p => `<span class="provider-badge ${esc(p)}">${esc(p)}</span>`).join('')
      const academic = user.student_name ? `<span class="tag good" title="教务绑定：${esc(user.student_name)}">教务</span>` : ''
      const bindingCell = providers || academic
        ? `${providers}${academic}` : '<span class="meta">未绑定</span>'
      const displayName = user.username || (user.openid ? '微信用户 ' + user.openid.slice(-6) : '用户 #' + user.id)
      return `<tr><td><b>${esc(displayName)}</b><small class="cell-secondary">UID ${user.id}</small></td><td>${esc(user.email || '未绑定')}</td><td>${bindingCell}</td><td><span class="tag ${user.schedule_count > 0 ? 'good' : 'closed'}">${user.schedule_count} 张</span></td><td>${timeText(user.created_at)}</td><td><button type="button" class="ghost" onclick="openUserDetail(${user.id})">查看详情</button></td></tr>`
    }).join('')
    $('usersList').innerHTML = `<table class="management-table"><thead><tr><th>用户</th><th>邮箱</th><th>绑定身份</th><th>课表</th><th>注册时间</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>`

    const total = data.total || 0
    const totalPages = Math.max(1, Math.ceil(total / limit))
    if (total > 0) {
      let pagerHtml = `<span class="meta">共 ${total} 位用户，第 ${page}/${totalPages} 页${hiddenNote ? ' · ' + hiddenNote : ''}</span>`
      if (page > 1) {
        pagerHtml += `<button type="button" class="ghost" onclick="loadUsers(${page - 1})">上一页</button>`
      }
      if (page < totalPages) {
        pagerHtml += `<button type="button" class="ghost" onclick="loadUsers(${page + 1})">下一页</button>`
      }
      $('usersPagination').innerHTML = pagerHtml
    }
  } catch (error) {
    if (revision !== usersLoadRevision) return
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
    const bots = data.bots || []
    const academic = data.academic
    const displayName = u.username || (u.openid ? '微信用户 ' + u.openid.slice(-6) : '用户 #' + u.id)

    const hasWechat = identities.some(i => i.provider === 'wechat') || Boolean(u.openid)
    const idCards = identities.map(i => `
      <div class="metric-row">
        <span><span class="provider-badge ${esc(i.provider)}">${esc(i.provider)}</span> 标识: <code>${esc(i.provider_user_id)}</code></span>
        <small>${timeText(i.last_seen_at)}</small>
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
          <div class="schedule-title">${esc(s.name)} ${s.variant_type === 'adjusted' ? '<span class="tag good">调课版</span>' : ''}</div>
          <div class="meta mt-8">学期: ${esc(s.term || '-')} · 起始日: ${esc(s.start_date || '-')} · ${s.course_count ?? '-'} 门课程</div>
        </div>
        <button type="button" class="save schedule-inspect-btn" onclick="viewScheduleCourses(${userId}, ${s.id})">透视课程清单</button>
      </div>
    `).join('') || '<div class="empty">该用户尚未创建任何课表</div>'

    const academicBlock = academic ? `
      <h3 class="dialog-section-title">教务学生绑定</h3>
      <div class="metric-row"><span>学生姓名</span><b>${esc(academic.student_name || '-')}</b></div>
      <div class="metric-row"><span>学号</span><b><code>${esc(academic.student_id || '-')}</code></b></div>
      <div class="metric-row"><span>最近同步</span><b>${timeText(academic.last_synced_at)}${academic.last_synced_term ? ' · ' + esc(academic.last_synced_term) : ''}</b></div>
    ` : ''

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
      <div class="metric-row"><span>最近活跃</span><b>${timeText(u.last_login_at)}</b></div>

      <h3 class="dialog-section-title">三方身份绑定 (${identities.length})</h3>
      ${idCards}

      ${academicBlock}
      <h3 class="dialog-section-title">微信助手绑定 (${bots.length})</h3>
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
        <h2>${esc(sched.name)} <small class="meta">(${esc(sched.term || '无学期')})</small></h2>
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

  const auditActions = {
    'feedback.update': '更新反馈', 'llm_config.update': '修改模型配置', 'llm_config.reset': '重置模型配置',
    'admin.create': '创建管理员', 'admin.delete': '删除管理员', 'user.unbind_wechat': '解绑用户微信',
    'ratelimit.clear': '清除限流', 'session_cache.clear': '清除会话缓存'
  }
  try {
    const audits = await api('/audit?limit=30')
    $('auditList').innerHTML = audits.length ? audits.map(a => `
      <div class="metric-row">
        <span>${esc(auditActions[a.action] || a.action)} · <b>${esc(a.admin_name)}</b> → <code>${esc(a.target_type)}:${esc(a.target_id)}</code></span>
        <small>${timeText(a.created_at)}</small>
      </div>
    `).join('') : '<div class="meta" style="padding:8px 0;">暂无管理操作记录</div>'
  } catch {
    $('auditList').innerHTML = '<div class="meta" style="padding:8px 0;">操作记录读取失败</div>'
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

let pageLoadRevision = 0
async function loadPage() {
  const revision = ++pageLoadRevision
  $('pageError').classList.add('hidden')
  $('refresh').disabled = true
  $('refresh').textContent = '刷新中…'
  $('refreshStatus').textContent = '正在读取数据'
  try {
    if (state.page === 'overview') await loadOverview()
    else if (state.page === 'directory') await loadDirectory()
    else if (state.page === 'users') await loadUsers(state.usersPage)
    else if (state.page === 'feedback') await loadFeedback()
    else if (state.page === 'traffic') await loadTraffic()
    else if (state.page === 'llm') await loadLlm()
    else if (state.page === 'system') await loadSystemStatus()
    else if (state.page === 'academic') await loadAcademicConnection()
    else if (state.page === 'academicSync') await loadAcademicSync()
    else if (state.page === 'admins') await loadAdmins()
  } catch (error) {
    if (revision === pageLoadRevision && state.token) {
      $('pageErrorText').textContent = '数据加载失败：' + error.message
      $('pageError').classList.remove('hidden')
      $('refreshStatus').textContent = '刷新失败'
    }
  } finally {
    if (revision === pageLoadRevision) {
      $('refresh').disabled = false
      $('refresh').textContent = '刷新数据'
      if ($('pageError').classList.contains('hidden')) $('refreshStatus').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false })
    }
  }
}
function switchPage(page) {
  if (!$(`${page}Page`)) return
  clearTimeout(academicLoginTimer)
  clearTimeout(academicSyncTimer)
  clearTimeout(directoryTimer)
  state.page = page
  saveLocation()
  const moduleKey = pageModule(page)
  const module = modules[moduleKey]
  document.querySelectorAll('.nav').forEach(x => {
    x.classList.toggle('active', x.dataset.module === moduleKey)
    x.setAttribute('aria-current', x.dataset.module === moduleKey ? 'page' : 'false')
  })
  $('moduleTabs').innerHTML = module.tabs.map(([key, title]) => `<button type="button" class="module-tab ${page === key ? 'active' : ''}" data-page="${key}" aria-current="${page === key ? 'page' : 'false'}">${title}</button>`).join('')
  $('pageDescription').textContent = module.description
  document.querySelectorAll('.page').forEach(x => x.classList.add('hidden'))
  $(`${page}Page`).classList.remove('hidden')
  $('pageTitle').textContent = {
    academic: '学校教务连接',
    academicSync: '课表同步',
    overview: '运行概览',
    users: '用户列表',
    feedback: '用户反馈',
    traffic: '流量监控',
    llm: '大模型配置',
    system: '系统运维与缓存',
    admins: '管理员管理'
  }[page] || module.tabs.find(tab => tab[0] === page)[1]
  $('pageTitle').textContent = module.title
  loadPage()
}

$('loginForm').onsubmit = async event => {
  event.preventDefault(); $('loginError').textContent=''
  const button = event.target.querySelector('button[type="submit"]')
  if (button.disabled) return
  button.disabled = true
  button.textContent = '正在登录…'
  try {
    const data = await api('/login', { method: 'POST', body: JSON.stringify({ username: $('username').value, password: $('password').value }) })
    state.token = data.token
    sessionStorage.setItem('admin_token', data.token)
    sessionStorage.setItem('admin_user', data.username)
    $('loginView').classList.add('hidden'); $('appView').classList.remove('hidden'); restoreLocation()
  } catch(error) { $('loginError').textContent = error.message }
  finally { button.disabled = false; button.textContent = '安全登录' }
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
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>switchPage(modules[button.dataset.module].tabs[0][0]))
$('moduleTabs').onclick = event => { const button = event.target.closest('[data-page]'); if (button) switchPage(button.dataset.page) }
window.addEventListener('hashchange', () => { if (state.token) restoreLocation() })
$('logout').onclick=logout
$('refresh').onclick=loadPage
$('retryPage').onclick=loadPage
$('feedbackList').onclick=e=>{const card=e.target.closest('[data-id]');if(card)openFeedback(card.dataset.id)}
$('feedbackList').onkeydown = event => {
  if (event.key !== 'Enter' && event.key !== ' ') return
  const card = event.target.closest('[data-id]')
  if (card) { event.preventDefault(); openFeedback(card.dataset.id) }
}
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
if ($('showUnbound')) {
  $('showUnbound').onchange = () => {
    state.showUnbound = $('showUnbound').checked
    loadUsers(1)
  }
}
if ($('btnCleanupUsers')) {
  $('btnCleanupUsers').onclick = async () => {
    if (!confirm('确定立即清理过期的未绑定用户吗？\n仅删除超过保留期未活跃、且无任何绑定/课表/反馈的微信静默登录用户。')) return
    try {
      const res = await api('/users/cleanup-unbound', { method: 'POST' })
      toast(`已清理 ${res.deleted_count} 位未绑定用户（保留期 ${res.retention_days} 天）`)
      loadUsers(1)
    } catch (error) { toast(error.message) }
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

// Defer startup until polling state below has been initialized.
window.addEventListener('DOMContentLoaded', () => { if(state.token){$('loginView').classList.add('hidden');$('appView').classList.remove('hidden');restoreLocation()} })



let academicLoginTimer

let directoryTimer
let directoryRevision = 0
async function loadDirectory() {
  clearTimeout(directoryTimer)
  const revision = ++directoryRevision
  $('directoryPage').innerHTML = '<div class="glass panel"><h2>学生目录同步</h2><p class="meta">完整名单用于本地身份搜索。刷新失败保留原名单；首次同步前使用学校实时搜索。</p><div id="directoryMetrics"></div><p id="directoryError" class="error" role="alert"></p><button id="directoryRefresh" class="save">刷新完整学生名单</button></div>'
  async function refreshDirectory() {
    const data = await api('/academic/directory/status')
    if (state.page !== 'directory' || revision !== directoryRevision) return
    const labels = { idle: '尚未同步', queued: '等待同步', running: '正在同步', succeeded: '同步成功', failed: '同步失败' }
    $('directoryMetrics').innerHTML = `<div class="metric-row"><span>同步状态</span><b>${esc(labels[data.state] || data.state)}</b></div><div class="metric-row"><span>已保存学生</span><b>${esc(data.student_count)} 人</b></div><div class="metric-row"><span>班级进度</span><b>${esc(data.classes_done)} / ${esc(data.classes_total)}</b></div><div class="metric-row"><span>最近成功</span><b>${timeText(data.synced_at)}</b></div>`
    $('directoryError').textContent = data.error || ''
    const running = ['queued', 'running'].includes(data.state)
    $('directoryRefresh').disabled = running
    if (running) directoryTimer = setTimeout(() => refreshDirectory().catch(error => { if (state.page === 'directory') $('directoryError').textContent = error.message }), 3000)
  }
  $('directoryRefresh').onclick = async () => {
    $('directoryRefresh').disabled = true
    $('directoryError').textContent = ''
    try { await api('/academic/directory/refresh', { method: 'POST' }); await refreshDirectory() }
    catch (error) { if (state.page === 'directory' && revision === directoryRevision) { $('directoryError').textContent = error.message; $('directoryRefresh').disabled = false } }
  }
  await refreshDirectory()
}

function syncSummary(sync) {
  const counts = sync.counts || {}
  const paused = sync.pause_until && new Date(sync.pause_until) > new Date()
  return `课表同步：排队 ${counts.queued || 0} · 执行 ${counts.running || 0} · 成功 ${counts.succeeded || 0} · 失败 ${counts.failed || 0}。每天北京时间 00:00 发起；${paused ? '学校连接失效，等待管理员恢复。' : '依次处理，失败保留原课表。'}`
}

async function loadAcademicConnection() {
  clearTimeout(academicLoginTimer)
  const target = $('academicPage')
  target.innerHTML = '<div class="empty">正在检查教务连接…</div>'
  const [data, login, mail] = await Promise.all([api('/academic/connection'), api('/academic/login/status'), api('/academic/mail')])
  const browser = data.browser || { state: 'not_started' }
  const labels = { connected: '浏览器会话可用', needs_login: '需要管理员重新登录', error: '浏览器检查失败', not_started: '会话维护进程未启动' }
  target.innerHTML = `<div class="glass panel academic-card">
    <div class="academic-header">
      <h2>连接学校账号</h2>
      <span class="tag ${login.saved ? 'good' : 'closed'}">${login.saved ? '已存凭据' : '未配置'}</span>
    </div>
    <div class="academic-status-box">
      <span id="schoolMaintenanceTag" class="tag">检查维护状态</span>
      <p id="schoolLoginStatus" class="academic-status-text">${esc(login.message)}</p>
      <p id="schoolMaintenanceSummary" class="meta"></p>
      <p id="schoolCredentialsSummary" class="meta">${login.saved ? '手机号已加密保存 · ' + esc(login.account || '') : '保存学校绑定手机号后发起验证码登录。'}</p>
    </div>
    <form id="schoolCredentialsForm" class="academic-form">
      <div class="form-row-2">
        <label>学校绑定手机号<input id="schoolAccount" type="tel" autocomplete="tel" inputmode="numeric" pattern="1[0-9]{10}" maxlength="11" required value="${esc(login.account || '')}" placeholder="11 位手机号"></label>
      </div>
      <button class="save academic-btn-save" type="submit">保存手机号</button>
    </form>
    <div class="academic-actions-bar">
      <button id="schoolLoginStart" class="btn-primary" ${!login.saved || login.running ? 'disabled' : ''}>启动维护 / 验证码登录</button>
      <button id="schoolLoginStop" class="btn-warning" ${!login.running && !login.maintenance_enabled ? 'disabled' : ''}>停止维护</button>
      <button id="schoolDeleteCredentials" class="btn-danger" ${!login.saved || login.running ? 'disabled' : ''}>删除手机号</button>
    </div>
    <div id="schoolCodePanel" class="school-code-box" ${['ready_for_code', 'waiting_code'].includes(login.state) ? '' : 'hidden'}>
      <div class="code-header">
        <span id="schoolCodeTip" class="code-tip" role="status">学校要求安全验证码</span>
        <button id="schoolSendCode" class="ghost btn-code-send">获取验证码</button>
      </div>
      <form id="schoolCodeForm" class="code-form">
        <input id="schoolCode" type="text" autocomplete="one-time-code" maxlength="32" placeholder="收到验证码后输入">
        <button type="submit" class="save">提交验证码并登录</button>
      </form>
    </div>
    <p id="schoolQueryStatus" class="meta"></p>
    <p id="schoolLoginError" class="error"></p><div id="schoolDiagnostic" hidden><p class="meta">学校登录页面（输入内容已隐藏）</p><img id="schoolDiagnosticImage" style="max-width:100%;border-radius:12px" alt="学校当前登录页面"></div>
    <p class="meta school-notice">手机与电脑均可点击「启动维护 / 验证码登录」，等待下方出现获取验证码入口，再输入短信验证码。已有会话可恢复时，无需验证码。停止维护会保留现有查询会话，后续失效时需重新登录。</p>
  </div>
  <div class="glass panel academic-card">
    <h2>QQ 邮件通知</h2>
    <p class="meta">维护需要人工处理时检查查询连接后提醒；查询后来失效时另发一次升级提醒。发件邮箱与收件邮箱可以相同。</p>
    <form id="schoolMailForm" class="academic-form">
      <label class="checkbox-row"><input id="schoolMailEnabled" type="checkbox" ${mail.enabled ? 'checked' : ''}> 启用掉线邮件通知</label>
      <div class="form-row-2">
        <label>QQ / Foxmail 发件邮箱<input id="schoolMailSender" type="email" required maxlength="254" value="${esc(mail.sender || '')}" placeholder="你的 QQ 邮箱"></label>
        <label>通知收件邮箱<input id="schoolMailRecipient" type="email" maxlength="254" value="${esc(mail.recipient || '')}" placeholder="留空则发送给发件邮箱"></label>
      </div>
      <label>SMTP 授权码<input id="schoolMailCode" type="password" autocomplete="new-password" maxlength="128" placeholder="${mail.configured ? '已加密保存；留空保留原授权码' : '在 QQ 邮箱设置中开启 SMTP 并获取授权码'}"></label>
      <p class="meta">使用 QQ 邮箱 SMTP 授权码。授权码加密保存，保存后不会回显。</p>
      <button class="save" type="submit">保存通知设置</button>
      <p id="schoolMailStatus" class="meta"></p><p id="schoolMailError" class="error"></p>
    </form>
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
  let revealCodePanel = false
  let actionPending = false
  let diagnosticUrl = null
  let diagnosticState = null
  let mailCheckedAt = Date.now()
  function renderMailStatus(value) {
    if (!$('schoolMailStatus')) return
    const labels = { pending: '等待发送', sending: '正在发送', sent: '已发送', failed: '发送失败', unknown: '发送结果未确认', cancelled: '会话已恢复，提醒已取消', disabled: '通知已关闭' }
    $('schoolMailStatus').textContent = `${value.enabled ? '通知已启用' : '通知未启用'} · ${labels[value.status] || '暂无掉线提醒'}${value.last_sent_at ? ' · 最近发送：' + timeText(value.last_sent_at) : ''}${value.next_attempt_at ? ' · 下次重试：' + timeText(new Date(value.next_attempt_at * 1000).toISOString()) : ''}`
    $('schoolMailError').textContent = value.config_error || value.last_error || ''
    if ($('schoolQueryStatus')) {
      const queryLabels = { available: '查询会话可用', unavailable: '查询会话不可用，需要重新登录', unknown: '查询会话暂未确认' }
      $('schoolQueryStatus').textContent = value.query_checked_at
        ? (queryLabels[value.query_state] || '查询会话暂未确认') + ' · 验证时间：' + timeText(value.query_checked_at)
        : (data.connected ? '页面打开时查询会话可用' : '页面打开时查询检查未成功：' + data.message)
    }
  }
  renderMailStatus(mail)
  $('schoolMailForm').onsubmit = async event => {
    event.preventDefault()
    const button = event.target.querySelector('button')
    button.disabled = true
    const sender = $('schoolMailSender').value.trim()
    const authorization_code = $('schoolMailCode').value.trim()
    $('schoolMailCode').value = ''
    try {
      const saved = await api('/academic/mail', { method: 'PUT', body: JSON.stringify({ enabled: $('schoolMailEnabled').checked, sender, recipient: $('schoolMailRecipient').value.trim() || sender, authorization_code }) })
      renderMailStatus(saved)
      $('schoolMailRecipient').value = saved.recipient
      $('schoolMailCode').placeholder = saved.configured ? '已加密保存；留空保留原授权码' : '在 QQ 邮箱设置中开启 SMTP 并获取授权码'
      toast('邮件通知设置已保存')
    } catch (e) { if ($('schoolMailError')) $('schoolMailError').textContent = e.message }
    finally { button.disabled = false }
  }
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
      if (latest.state === 'needs_login' && previousState !== 'needs_login') toast('学校连接需要人工登录，请重新发起登录')
      const maintenanceLabels = { connected: '正常维护', retrying: '等待自动重试', recovering: '正在恢复', checking: '正在验证', needs_login: '等待人工登录', ready_for_code: '等待获取验证码', waiting_code: '等待输入验证码', manual_waiting: '等待人工登录', stopped: '已停止', not_started: '未启动', error: '维护异常' }
      $('schoolMaintenanceTag').textContent = maintenanceLabels[latest.state] || '正在登录'
      $('schoolMaintenanceTag').className = 'tag ' + (latest.state === 'connected' ? 'good' : ['needs_login', 'error'].includes(latest.state) ? 'bad' : 'processing')
      $('schoolMaintenanceSummary').textContent = `${latest.maintenance_enabled ? '已启用重启自动恢复' : '自动维护未启用'} · 最近验证成功：${timeText(latest.last_verified_at)}${latest.next_retry_at ? ' · 下次重试：' + timeText(latest.next_retry_at) : ''}${latest.error_type ? ' · 异常类型：' + latest.error_type : ''}`
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
      const codeReady = ['ready_for_code', 'waiting_code'].includes(latest.state)
      const codeVisible = codeReady || (!latest.visible && latest.running && ['starting', 'checking', 'recovering', 'retrying', 'processing', 'submitting', 'continuing'].includes(latest.state))
      $('schoolCodePanel').hidden = !codeVisible
      $('schoolCodeTip').textContent = codeReady ? '学校要求安全验证码' : '正在准备学校登录，请稍候…'
      $('schoolCodeForm').hidden = !codeReady && !['processing', 'submitting'].includes(latest.state)
      if (revealCodePanel && codeReady) {
        $('schoolCodePanel').scrollIntoView({ behavior: 'smooth', block: 'center' })
        revealCodePanel = false
      }
      if (['connected', 'stopped', 'needs_login', 'error'].includes(latest.state)) revealCodePanel = false
      $('schoolLoginStart').disabled = actionPending || !latest.saved || latest.running
      $('schoolLoginStop').disabled = !latest.running && !latest.maintenance_enabled
      $('schoolDeleteCredentials').disabled = !latest.saved || latest.running
      $('schoolCredentialsForm').querySelector('button').disabled = latest.running
      $('schoolSendCode').disabled = latest.state !== 'ready_for_code' && latest.state !== 'waiting_code'
      if (Date.now() - mailCheckedAt > 15000) {
        mailCheckedAt = Date.now()
        const mailStatus = await api('/academic/mail')
        if (state.page === 'academic') renderMailStatus(mailStatus)
      }
    } catch (e) { if ($('schoolLoginError')) $('schoolLoginError').textContent = e.message }
    if (state.page === 'academic') academicLoginTimer = setTimeout(refreshLogin, 2000)
  }
  async function loginAction(path, options) {
    $('schoolLoginError').textContent = ''
    if (actionPending) return
    actionPending = true
    $('schoolLoginStart').disabled = true
    try {
      latest = await api('/academic/login/' + path, options)
      actionPending = false
      await refreshLogin()
      return true
    } catch (e) {
      $('schoolLoginError').textContent = e.message
      return false
    } finally {
      actionPending = false
      $('schoolLoginStart').disabled = !latest.saved || latest.running
    }
  }
  $('schoolCredentialsForm').onsubmit = async event => {
    event.preventDefault()
    const account = $('schoolAccount').value.trim()
    await loginAction('credentials', { method: 'PUT', body: JSON.stringify({ account }) })
  }
  $('schoolLoginStart').onclick = async () => {
    revealCodePanel = true
    $('schoolCodePanel').hidden = false
    $('schoolCodeForm').hidden = true
    $('schoolSendCode').disabled = true
    $('schoolCodeTip').textContent = '正在启动学校登录，请稍候…'
    $('schoolCodePanel').scrollIntoView({ behavior: 'smooth', block: 'center' })
    if (!await loginAction('start', { method: 'POST' })) {
      revealCodePanel = false
      $('schoolCodePanel').hidden = true
    }
  }
  $('schoolLoginStop').onclick = async () => {
    if (await loginAction('stop', { method: 'POST' })) toast('已停止自动维护，现有查询会话仍保留，失效后需重新登录')
  }
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
  async function refreshSync() {
    if (state.page !== 'academicSync' || current !== academicSyncRevision) return
    try {
      const data = await api('/academic/sync/status')
      if (state.page !== 'academicSync' || current !== academicSyncRevision) return
      const counts = data.counts || {}
      $('allSchoolSyncStats').innerHTML = `<div class="stats">${stat('已绑定账号', data.bound_count)}${stat('排队', counts.queued || 0)}${stat('执行中', counts.running || 0)}${stat('成功（近 30 天）', counts.succeeded || 0)}${stat('失败（近 30 天）', counts.failed || 0)}</div><p class="meta">${esc(syncSummary(data))} 最近自动批次：${esc(data.last_daily_run?.run_date || '尚未生成')}</p>`
      const states = { queued: '排队中', running: '同步中', succeeded: '成功', failed: '失败' }
      const sources = { daily: '零点自动', manual: '用户发起', admin: '后台主动' }
      $('allSchoolSyncJobs').innerHTML = (data.recent || []).length ? `<div class="table-shell"><table class="management-table"><thead><tr><th>状态</th><th>用户 / 学期</th><th>来源</th><th>尝试</th><th>最近更新</th><th>失败原因</th></tr></thead><tbody>${data.recent.map(job => `<tr><td><span class="tag ${job.state === 'failed' ? 'bad' : job.state === 'succeeded' ? 'good' : 'processing'}">${esc(states[job.state] || job.state)}</span></td><td>UID ${esc(job.user_id)}<small class="cell-secondary">${esc(job.term)}</small></td><td>${esc(sources[job.source] || job.source)}</td><td>${esc(job.attempts)} 次</td><td>${timeText(job.updated_at)}</td><td class="description-cell">${esc(job.error || '—')}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">暂无同步任务</div>'
    } catch (e) { if (current === academicSyncRevision && state.page === 'academicSync') $('allSchoolSyncError').textContent = e.message }
    if (state.page === 'academicSync' && current === academicSyncRevision) academicSyncTimer = setTimeout(refreshSync, 3000)
  }
  $('startAllSchoolSync').onclick = async () => {
    if (!confirm('将为全部已绑定账号同步学校课表，成功后覆盖学校课表中的导入内容和个人修改。确定继续吗？')) return
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
