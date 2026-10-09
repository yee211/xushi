const app = getApp()
Page({
  data: { nightMode: false, backgroundPath: '', syncStatus: '', bound: null, lastSyncedText: '', keyword: '', students: [], selected: null, terms: [], termIndex: 0, busy: false, error: '', notice: '', searched: false },
  onShow() {
    const nightMode = wx.getStorageSync('night_mode') === true
    const backgroundPath = wx.getStorageSync('schedule_background') || ''
    this.setData({ nightMode, backgroundPath })
    if (wx.setNavigationBarColor) {
      wx.setNavigationBarColor({
        frontColor: (nightMode || backgroundPath) ? '#ffffff' : '#000000',
        backgroundColor: nightMode ? '#070d19' : (backgroundPath ? '#000000' : '#f3f6fb')
      }).catch(() => {})
    }
  },
  async onLoad() {
    this.setData({ busy: true })
    try {
      const binding = await app.request('/api/academic/binding')
      if (this.closed) return
      if (binding.student) {
        wx.setStorageSync('bound_student', binding.student)
        this.setData({ bound: binding.student, selected: binding.student, lastSyncedText: binding.last_synced_at ? new Date(binding.last_synced_at).toLocaleString() : '尚未同步' })
        await this.loadTerms(binding.student)
      } else {
        wx.removeStorageSync('bound_student')
      }
    }
    catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    finally { if (!this.closed && !this.data.syncStatus) this.setData({ busy: false }) }
    if (this.data.bound) {
      try {
        const latest = await app.request('/api/academic/binding/sync/tasks/latest')
        if (latest.task && (['queued', 'running'].includes(latest.task.state) || wx.getStorageSync('academic_pending_task_id') === latest.task.id)) await this.followTask(latest.task)
        else if (latest.task && latest.task.state === 'failed') this.setData({ error: latest.task.error })
      } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    }
  },
  onUnload() { this.closed = true; clearTimeout(this.pollTimer) },
  inputKeyword(e) { this.setData({ keyword: e.detail.value }) },
  changeTerm(e) { this.setData({ termIndex: Number(e.detail.value) }) },
  async search() {
    if (this.data.busy) return
    const keyword = this.data.keyword.trim()
    if (!keyword) { this.setData({ error: '请输入姓名、专业、班级或年级关键词' }); return }
    this.setData({ busy: true, error: '', notice: '', selected: null, students: [], searched: false })
    try {
      const data = await app.request('/api/academic/students', { data: { q: keyword }, timeout: 120000 })
      if (!this.closed) this.setData({ students: data.students || [], searched: true, notice: data.stale ? '学校暂时无法连接，先为你显示已保存的学生信息。' : data.truncated ? '找到的学生较多，请补充姓名或班级，方便找到自己。' : '' })
    } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    finally { if (!this.closed) this.setData({ busy: false }) }
  },
  choose(e) {
    if (this.data.busy) return
    const selected = this.data.students.find(s => s.id === e.currentTarget.dataset.id)
    if (selected) this.setData({ selected, terms: [], error: '' })
  },
  async loadTerms(student) {
    // Default term remains usable if the optional term-list request fails.
    const fallback = student.default_term ? [student.default_term] : []
    if (!this.closed) this.setData({ terms: fallback, termIndex: 0 })
    const data = await app.request('/api/academic/students/' + encodeURIComponent(student.id) + '/terms', { timeout: 120000 })
    if (!this.closed) {
      const terms = data.terms || []
      this.setData({ terms, termIndex: Math.max(0, terms.indexOf(student.default_term)) })
    }
  },
  async bindSchool() {
    if (this.data.busy || !this.data.selected) return
    this.setData({ busy: true, error: '' })
    try {
      const data = await app.request('/api/academic/binding', { method: 'PUT', data: { student_id: this.data.selected.id } })
      if (!this.closed) {
        wx.setStorageSync('bound_student', data.student)
        this.setData({ bound: data.student, selected: data.student, lastSyncedText: '尚未同步' })
        wx.showToast({ title: '学校信息已关联', icon: 'success' })
        await this.loadTerms(data.student)
      }
    } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    finally { if (!this.closed) this.setData({ busy: false }) }
  },
  async syncSchool() {
    if (this.data.busy || !this.data.bound || !this.data.terms.length) return
    if (this.confirmingSync) return;
    this.confirmingSync = true;
    const term = this.data.terms[this.data.termIndex];
    const confirmed = await new Promise(resolve => wx.showModal({ title: '更新为学校课表？', content: `将同步 ${term} 的学校课表。同步成功后只保留这份课表，其他课表和个人调课会被替换。当前内容会先备份，同步失败时保留原课表。`, confirmText: '同步课表', cancelText: '暂不同步', confirmColor: '#b74343', success: answer => resolve(answer.confirm), fail: () => resolve(false) }));
    this.confirmingSync = false;
    if (!confirmed || this.closed || this.data.busy) return;
    this.setData({ busy: true, error: '' })
    try {
      const task = await app.request('/api/academic/binding/sync/tasks', { method: 'POST', data: { term } })
      await this.followTask(task)
    } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    finally { if (!this.closed && !this.data.syncStatus) this.setData({ busy: false }) }
  },
  async followTask(task) {
    if (this.closed) return
    if (task.state === 'succeeded') {
      if (wx.getStorageSync('academic_pending_task_id') === task.id) wx.removeStorageSync('academic_pending_task_id')
      const result = task.result
      this.setData({ syncStatus: '', busy: false })
      if (!this.closed) {
        wx.setStorageSync('active_schedule_id', result.schedule_id)
        this.setData({ lastSyncedText: new Date(result.last_synced_at).toLocaleString() })
        const pages = getCurrentPages()
        const previous = pages[pages.length - 2]
        if (previous && typeof previous.load === 'function') await previous.load(result.schedule_id)
        if (result.warnings && result.warnings.length) {
          wx.showModal({ title: '同步完成', content: '课表已同步。\n' + result.warnings.join('；'), showCancel: false, confirmText: '我知道了' })
        } else wx.showToast({ title: result.unchanged ? '课表已是最新' : '已同步到我的课表', icon: 'success' })
      }
      return
    }
    if (task.state === 'failed') {
      if (wx.getStorageSync('academic_pending_task_id') === task.id) wx.removeStorageSync('academic_pending_task_id')
      this.setData({ busy: false, syncStatus: '', error: task.error || '同步失败，原课表已保留' })
      return
    }
    wx.setStorageSync('academic_pending_task_id', task.id)
    this.setData({ busy: true, syncStatus: task.state === 'running' ? '正在从学校同步课表…' : '已加入同步队列，等待处理…' })
    this.pollTimer = setTimeout(async () => {
      try { await this.followTask(await app.request('/api/academic/binding/sync/tasks/' + encodeURIComponent(task.id))) }
      catch (e) { if (!this.closed) this.setData({ busy: false, syncStatus: '', error: '暂时无法查看同步进度。任务可能仍在进行，请稍后重新打开查看。' }) }
    }, 1500)
  },
  async restoreSchoolBackup() {
    if (this.data.busy || this.closed) return
    this.setData({ busy: true, error: '' })
    try {
      const data = await app.request('/api/academic/backups')
      if (this.closed) return
      const backups = data.backups || []
      if (!backups.length) {
        wx.showToast({ title: '暂无恢复记录', icon: 'none' })
        return
      }
      wx.showActionSheet({ itemList: backups.map(b => new Date(b.created_at).toLocaleString() + ' · ' + b.schedule_count + '份课表'), success: choice => {
        if (this.closed) return
        wx.showModal({ title: '恢复这份课表？', content: '将恢复所选时间保存的课表，替换当前全部课表和调课。当前内容会先备份，可再次恢复。学校自动同步仍会继续更新课表。', confirmText: '恢复课表', cancelText: '暂不恢复', confirmColor: '#b74343', success: async answer => {
          if (!answer.confirm || this.closed || this.data.busy) return
          this.setData({ busy: true, error: '' })
          try {
            const result = await app.request('/api/academic/backups/' + encodeURIComponent(backups[choice.tapIndex].id) + '/restore', { method: 'POST' })
            if (this.closed) return
            wx.setStorageSync('active_schedule_id', result.schedule_id)
            this.setData({ lastSyncedText: '已恢复同步前课表' })
            const pages = getCurrentPages()
            const previous = pages[pages.length - 2]
            if (previous && typeof previous.load === 'function') await previous.load(result.schedule_id)
            wx.showToast({ title: '已恢复课表和调课', icon: 'success' })
          } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
          finally { if (!this.closed) this.setData({ busy: false }) }
        } })
      } })
    } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    finally { if (!this.closed) this.setData({ busy: false }) }
  },
  unbindSchool() {
    if (this.data.busy) return
    wx.showModal({ title: '解除学校绑定？', content: '解除后不再自动同步学校课表，已同步的课表会保留。你可以随时重新绑定或选择其他学校身份。', confirmText: '解除绑定', cancelText: '保留绑定', confirmColor: '#b74343', success: async res => {
      if (!res.confirm || this.closed) return
      this.setData({ busy: true, error: '' })
      try {
        await app.request('/api/academic/binding', { method: 'DELETE' })
        wx.removeStorageSync('bound_student')
        if (!this.closed) this.setData({ bound: null, selected: null, students: [], terms: [], searched: false })
        wx.removeStorageSync('academic_pending_task_id')
      } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
      finally { if (!this.closed) this.setData({ busy: false }) }
    } })
  }
})

