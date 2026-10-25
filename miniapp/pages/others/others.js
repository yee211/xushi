const app = getApp()
Page({
  data: { nightMode: false, backgroundPath: '', keyword: '', students: [], selected: null, terms: [], termIndex: 0, remark: '', busy: false, error: '', notice: '', searched: false, saved: false, updatedText: '', scrollIntoView: '', savedPeople: [], loadingSaved: false, savedError: '' },
  onShow() {
    const nightMode = typeof wx.getStorageSync === 'function' && wx.getStorageSync('night_mode') === true
    const backgroundPath = (typeof wx.getStorageSync === 'function' && wx.getStorageSync('schedule_background')) || ''
    this.setData({ nightMode, backgroundPath })
    if (this._loaded) this.loadSavedPeople()
    if (wx.setNavigationBarColor) {
      try {
        const pending = wx.setNavigationBarColor({
          frontColor: (nightMode || backgroundPath) ? '#ffffff' : '#000000',
          backgroundColor: nightMode ? '#070d19' : (backgroundPath ? '#000000' : '#f3f6fb')
        })
        if (pending && typeof pending.catch === 'function') pending.catch(() => {})
      } catch (_) {}
    }
  },
  async onLoad(options) {
    const people = await this.loadSavedPeople()
    this._loaded = true
    if (!options || !options.studentId || this.closed) return
    const pages = getCurrentPages()
    const previous = pages[pages.length - 2]
    const preview = previous && previous.data.otherPerson
    const person = people.find(p => p.student_id === options.studentId) || (preview && preview.student_id === options.studentId ? preview : null)
    if (person) await this.selectSavedPerson(person, people.some(p => p.student_id === person.student_id))
  },
  async loadSavedPeople() {
    const session = wx.getStorageSync('session_token')
    const revision = this._savedRevision = (this._savedRevision || 0) + 1
    const current = () => !this.closed && revision === this._savedRevision && session === wx.getStorageSync('session_token')
    this.setData({ loadingSaved: true, savedError: '' })
    try {
      const result = await app.request('/api/academic/others')
      const people = (result && Array.isArray(result.people)) ? result.people : []
      if (!current()) return []
      this.setData({ savedPeople: people })
      try { wx.setStorageSync('other_schedules_cache', { session, people }) } catch (_) {}
      return people
    } catch (e) {
      if (!current()) return []
      if (!this.closed) this.setData({ savedError: e.message })
      try {
        const cache = wx.getStorageSync('other_schedules_cache')
        if (![401, 403].includes(e.statusCode) && cache && cache.session === wx.getStorageSync('session_token') && Array.isArray(cache.people)) {
          if (!this.closed) this.setData({ savedPeople: cache.people, savedError: '暂时离线，显示上次保存的名单' })
          return cache.people
        }
      } catch (_) {}
      this.setData({ savedPeople: [] })
      return []
    } finally { if (!this.closed && revision === this._savedRevision) this.setData({ loadingSaved: false }) }
  },
  async selectSavedPerson(person, saved = true) {
    if (this.data.busy) return
    const student = {
      ...(person.snapshot && person.snapshot.student),
      id: (person.snapshot && person.snapshot.student && person.snapshot.student.id) || person.student_id
    }
    this.setData({ busy: true, selected: student, remark: person.remark || '', saved, error: '', scrollIntoView: 'selected-panel', updatedText: person.updated_at ? new Date(person.updated_at).toLocaleString() : '' })
    try { await this.loadTerms(student, person.term) }
    finally { if (!this.closed) this.setData({ busy: false }) }
  },
  chooseSaved(e) {
    const person = this.data.savedPeople.find(p => p.student_id === e.currentTarget.dataset.id)
    if (person) return this.selectSavedPerson(person)
  },
  viewSaved(e) {
    if (this.data.busy) return
    const person = this.data.savedPeople.find(p => p.student_id === e.currentTarget.dataset.id)
    if (person) this.showOnHome(person)
  },
  removeSaved(e) {
    if (this.data.busy || this._confirmingRemove) return
    const id = e.currentTarget.dataset.id
    const person = this.data.savedPeople.find(p => p.student_id === id)
    if (!person) return
    const name = (person.snapshot && person.snapshot.student && person.snapshot.student.name) || person.remark || '此人'
    this._confirmingRemove = true
    wx.showModal({
      title: '移除保存的课表？',
      content: `确定移除 ${name} 的课表吗？只移除你保存的此人课表。`,
      confirmColor: '#dc2626',
      complete: () => { this._confirmingRemove = false },
      success: async answer => {
        if (!answer.confirm || this.closed || this.data.busy) return
        this.setData({ busy: true, error: '' })
        try {
          await app.request('/api/academic/others/' + encodeURIComponent(id), { method: 'DELETE' })
          const pages = getCurrentPages()
          const previous = pages[pages.length - 2]
          if (previous && previous.previewOther && previous.previewOther.student_id === id) {
            previous.previewOther = null
          }
          this.cachePerson({ student_id: id }, true)
          const nextPeople = this.data.savedPeople.filter(p => p.student_id !== id)
          const updates = { savedPeople: nextPeople }
          const activeId = this.data.selected && (this.data.selected.id || this.data.selected.student_id)
          if (activeId === id) {
            updates.selected = null
            updates.saved = false
            updates.remark = ''
            updates.updatedText = ''
            updates.terms = []
            updates.termIndex = 0
          }
          if (!this.closed) {
            this.setData(updates)
            if (typeof wx.showToast === 'function') wx.showToast({ title: '已移除', icon: 'success' })
          }
        } catch (e) {
          if (!this.closed) this.setData({ error: e.message })
        } finally {
          if (!this.closed) this.setData({ busy: false })
        }
      }
    })
  },
  showOnHome(person) {
    const pages = getCurrentPages()
    const previous = pages[pages.length - 2]
    if (previous && typeof previous.showOtherPerson === 'function') {
      previous.previewOther = person
      previous.setData({ currentTab: 'home', scheduleScope: 'others' })
      previous.showOtherPerson(person)
      if (wx.setNavigationBarTitle) wx.setNavigationBarTitle({ title: '序时课表' })
    }
    wx.navigateBack()
  },
  onUnload() { this.closed = true },
  inputKeyword(e) { this.setData({ keyword: e.detail.value }) },
  inputRemark(e) { this.setData({ remark: e.detail.value }) },
  changeTerm(e) { this.setData({ termIndex: Number(e.detail.value) }) },
  cachePerson(person, remove = false) {
    try {
      const session = wx.getStorageSync('session_token')
      const cached = wx.getStorageSync('other_schedules_cache')
      const people = cached && cached.session === session && Array.isArray(cached.people) ? cached.people : []
      const remaining = people.filter(p => p.student_id !== person.student_id)
      wx.setStorageSync('other_schedules_cache', { session, people: remove ? remaining : [person, ...remaining] })
    } catch (_) { /* Cache is optional; a committed save/delete remains successful. */ }
  },
  async search() {
    if (this.data.busy || !this.data.keyword.trim()) return
    this.setData({ busy: true, error: '', selected: null, students: [], searched: false, saved: false })
    try {
      const result = await app.request('/api/academic/students', { data: { q: this.data.keyword.trim() }, timeout: 120000 })
      if (!this.closed) this.setData({
        students: result.students || [],
        searched: true,
        notice: result.stale ? '学校暂时无法连接，先为你显示已保存的学生信息。' : result.truncated ? '匹配到的学生较多，请补充姓名或班级以缩小范围。' : ''
      })
    } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    finally { if (!this.closed) this.setData({ busy: false }) }
  },
  async choose(e) {
    if (this.data.busy) return
    const student = this.data.students.find(s => s.id === e.currentTarget.dataset.id)
    if (!student) return
    this.setData({ busy: true, selected: student, remark: '', saved: false, updatedText: '', error: '', scrollIntoView: '', terms: student.default_term ? [student.default_term] : [], termIndex: 0 })
    this.setData({ scrollIntoView: 'selected-panel' })
    try {
      const result = await app.request('/api/academic/others')
      const people = (result && Array.isArray(result.people)) ? result.people : []
      const person = people.find(p => p.student_id === student.id)
      if (person && !this.closed) this.setData({ saved: true, remark: person.remark || '', updatedText: person.updated_at ? new Date(person.updated_at).toLocaleString() : '' })
      await this.loadTerms(student, person && person.term)
    } catch (e) {
      if (!this.closed) {
        this.setData({ error: e.message })
        await this.loadTerms(student)
      }
    } finally {
      if (!this.closed && !this.data.terms.length) await this.loadTerms(student)
      if (!this.closed) this.setData({ busy: false })
    }
  },
  async loadTerms(student, preferred) {
    const fallback = preferred || student.default_term
    this.setData({ terms: fallback ? [fallback] : [], termIndex: 0 })
    try {
      const result = await app.request('/api/academic/students/' + encodeURIComponent(student.id) + '/terms', { timeout: 120000 })
      if (!this.closed && result.terms && result.terms.length) {
        const terms = fallback && !result.terms.includes(fallback) ? [fallback, ...result.terms] : result.terms
        this.setData({ terms, termIndex: Math.max(0, terms.indexOf(fallback)) })
      }
    } catch (e) { if (!this.closed) this.setData({ error: '学期加载失败，可重试选择学生；有默认学期时仍可查看。' }) }
  },
  async preview() { await this.submit(false) },
  async save() { await this.submit(true) },
  async submit(save) {
    const student = this.data.selected
    const term = this.data.terms[this.data.termIndex]
    if (this.data.busy || !student || !term) return
    this.setData({ busy: true, error: '' })
    try {
      let person
      if (save) {
        person = await app.request('/api/academic/others', { method: 'PUT', data: { student_id: student.id, term, remark: this.data.remark }, timeout: 120000 })
        this.cachePerson(person)
      }
      else {
        const snapshot = await app.request('/api/academic/students/' + encodeURIComponent(student.id) + '/schedule', { data: { term }, timeout: 120000 })
        if (snapshot.stale || !snapshot.complete) throw new Error('学校暂不可用，请稍后重试')
        person = { student_id: student.id, term, remark: this.data.remark, snapshot }
      }
      if (this.closed) return
      this.showOnHome(person)
    } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
    finally { if (!this.closed) this.setData({ busy: false }) }
  },
  remove() {
    if (this.data.busy || !this.data.saved || this._confirmingRemove) return
    this._confirmingRemove = true
    wx.showModal({ title: '移除保存的课表？', content: '只移除你保存的此人课表。', confirmColor: '#dc2626', complete: () => { this._confirmingRemove = false }, success: async answer => {
      if (!answer.confirm || this.closed || this.data.busy) return
      this.setData({ busy: true, error: '' })
      try {
        await app.request('/api/academic/others/' + encodeURIComponent(this.data.selected.id), { method: 'DELETE' })
        const pages = getCurrentPages()
        const previous = pages[pages.length - 2]
        if (previous && previous.previewOther && previous.previewOther.student_id === this.data.selected.id) {
          previous.previewOther = null
        }
        this.cachePerson({ student_id: this.data.selected.id }, true)
        const nextPeople = this.data.savedPeople.filter(p => p.student_id !== this.data.selected.id)
        if (!this.closed) {
          this.setData({ savedPeople: nextPeople, selected: null, saved: false })
          wx.navigateBack()
        }
      } catch (e) { if (!this.closed) this.setData({ error: e.message }) }
      finally { if (!this.closed) this.setData({ busy: false }) }
    } })
  }
})
