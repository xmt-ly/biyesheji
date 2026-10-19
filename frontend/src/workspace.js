import { reactive } from 'vue'
import { createApiClient } from './api.js'
import { mergeMessages } from './state.js'

const emptyData = () => ({ project: null, course: null, requirements: [], tasks: [], progress: null, plans: [], submissions: [], messages: [], cards: [], files: [], runs: [] })

export function createWorkspace({ storage = globalThis.sessionStorage, fetchImpl = globalThis.fetch, WebSocketImpl = globalThis.WebSocket, locationImpl = globalThis.location } = {}) {
  const s = reactive({ token: storage.getItem('course_token') || '', user: null, courses: [], projects: [], config: null, data: emptyData(), selectedId: null, tab: 'home', loading: false, busy: false, booting: true, error: '', notice: '', resourceErrors: {}, connection: '未连接', agentStatus: '', outbox: [], focusMessage: null })
  let epoch = 0, loadVersion = 0, historyAfter = 0, socket, reconnectTimer, heartbeatTimer, retries = 0
  const api = createApiClient({ fetchImpl, getToken: () => s.token, onUnauthorized: () => logout('登录已失效，请重新登录') })
  function closeSocket() {
    clearTimeout(reconnectTimer); clearInterval(heartbeatTimer)
    if (socket) { socket.onclose = null; socket.close(); socket = null }
    s.connection = '未连接'
  }
  function logout(message = '') {
    epoch++; loadVersion++; historyAfter = 0; closeSocket(); storage.removeItem('course_token')
    Object.assign(s, { token: '', user: null, data: emptyData(), projects: [], courses: [], config: null, resourceErrors: {}, selectedId: null, outbox: [], error: message, notice: '', loading: false, busy: false, agentStatus: '', focusMessage: null, tab: 'home' })
  }
  async function init() {
    const mine = epoch
    try { if (s.token) { const user = await api.request('/auth/me'); if (mine !== epoch) return; s.user = user; await loadBasics() } }
    catch (error) { if (mine === epoch) s.error = error.message }
    finally { s.booting = false }
  }
  async function login(username, password) {
    const mine = epoch
    s.busy = true; s.error = ''
    try {
      const result = await api.request('/auth/login', { method: 'POST', data: { username, password } })
      if (mine !== epoch) return
      s.token = result.access_token; s.user = result.user; storage.setItem('course_token', s.token)
      await loadBasics()
    } catch (error) { if (mine === epoch) s.error = error.message }
    finally { if (mine === epoch) s.busy = false }
  }
  async function loadBasics() {
    const mine = epoch
    const names = ['courses', 'projects', 'config']
    const results = await Promise.allSettled(['/courses', '/projects', '/config/status'].map(path => api.request(path)))
    if (mine !== epoch) return
    results.forEach((result, i) => {
      if (result.status === 'fulfilled') { s[names[i]] = result.value; delete s.resourceErrors[names[i]] }
      else s.resourceErrors[names[i]] = result.reason.message
    })
  }
  async function selectProject(id) {
    epoch++; loadVersion++; historyAfter = 0; closeSocket(); retries = 0
    const mine = epoch
    Object.assign(s, { selectedId: Number(id), data: emptyData(), outbox: [], resourceErrors: {}, error: '', notice: '', tab: s.user.identity === 'teacher' ? 'overview' : 'collaboration', agentStatus: '', focusMessage: null })
    await refreshProject()
    if (mine === epoch && s.data.project && s.user?.identity === 'student') connect(mine)
  }
  async function refreshProject() {
    if (!s.selectedId) return
    const id = s.selectedId, mine = epoch, version = ++loadVersion
    const current = () => mine === epoch && version === loadVersion
    s.loading = true
    try {
      const project = await api.request(`/projects/${id}`)
      if (!current()) return
      s.data.project = project
      const student = s.user?.identity === 'student'
      const resources = ['tasks', 'progress', 'plans', 'submissions', ...(student ? ['requirements', 'cards', 'files', 'runs'] : s.tab === 'requirements' ? ['requirements'] : [])]
      const paths = { course: `/courses/${project.course_id}`, ...Object.fromEntries(resources.map(name => [name, `/projects/${id}/${name === 'runs' ? 'agent/runs' : name}`])) }
      const names = Object.keys(paths)
      const results = await Promise.allSettled(Object.values(paths).map(path => api.request(path)))
      if (!current()) return
      results.forEach((result, i) => {
        const name = names[i]
        if (result.status === 'fulfilled') { s.data[name] = result.value; delete s.resourceErrors[name] }
        else s.resourceErrors[name] = result.reason.message
      })
      if (student) await catchUp(mine)
      else await submittedMetadata(mine, version)
    } catch (error) { if (current()) s.error = error.message }
    finally { if (current()) s.loading = false }
  }
  async function loadRequirements() {
    const mine = epoch, id = s.selectedId
    try { const result = await api.request(`/projects/${id}/requirements`); if (mine === epoch) { s.data.requirements = result; delete s.resourceErrors.requirements } }
    catch (error) { if (mine === epoch) s.resourceErrors.requirements = error.message }
  }
  async function submittedMetadata(mine, version) {
    const ids = [...new Set(s.data.submissions.flatMap(x => x.file_ids || []))]
    const result = await Promise.allSettled(ids.map(id => api.request(`/files/${id}/metadata`)))
    if (mine !== epoch || version !== loadVersion) return
    s.data.files = result.filter(x => x.status === 'fulfilled').map(x => x.value)
    const failed = result.find(x => x.status === 'rejected')
    if (failed) s.resourceErrors.files = failed.reason.message
    else delete s.resourceErrors.files
  }
  function acceptMessages(messages) {
    s.data.messages = mergeMessages(s.data.messages,messages)
    const delivered = new Set(s.data.messages.filter(message => message.project_id === s.selectedId && message.user_id === s.user?.id && message.client_id).map(message => message.client_id))
    s.outbox = s.outbox.filter(entry => !delivered.has(entry.payload.client_id))
  }
  async function catchUp(mine = epoch) {
    const id = s.selectedId
    let after = historyAfter
    try {
      for (;;) {
        const page = await api.request(`/projects/${id}/messages?after_id=${after}&limit=200`)
        if (mine !== epoch) return
        acceptMessages(page)
        if (page.length) historyAfter = Math.max(historyAfter, page.at(-1).id)
        if (page.length < 200) break
        after = page.at(-1).id
      }
      delete s.resourceErrors.messages
    } catch (error) { if (mine === epoch) s.resourceErrors.messages = error.message }
  }
  function connect(mine) {
    if (mine !== epoch || !s.token || s.user?.identity !== 'student') return
    s.connection = retries ? '重连中' : '连接中'
    const proto = locationImpl.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocketImpl(`${proto}//${locationImpl.host}/api/projects/${s.selectedId}/ws?token=${encodeURIComponent(s.token)}`)
    socket.onopen = () => {
      if (mine !== epoch) return
      retries = 0; s.connection = '已连接'; catchUp(mine)
      clearInterval(heartbeatTimer)
      heartbeatTimer = setInterval(() => { if (socket?.readyState === 1) socket.send(JSON.stringify({ type: 'ping' })) }, 30000)
    }
    socket.onmessage = event => {
      if (mine !== epoch) return
      let payload
      try { payload = JSON.parse(event.data) } catch { return }
      if (payload.type === 'message') acceptMessages([payload.message])
      if (['cards_changed', 'project_changed'].includes(payload.type)) refreshProject()
      if (payload.type === 'agent_status') {
        s.agentStatus = { analyzing: '正在分析讨论…', completed: '分析完成', failed: payload.message || '分析失败，请重试' }[payload.status] || payload.status
        if (payload.status !== 'analyzing') refreshProject()
      }
    }
    socket.onerror = () => { if (mine === epoch) s.connection = '连接异常' }
    socket.onclose = event => {
      clearInterval(heartbeatTimer)
      if (mine !== epoch || !s.token) return
      if (event.code === 1008) { s.connection = '连接被拒绝，请核对登录或项目权限'; return }
      s.connection = '已断开，自动重连'; retries++
      reconnectTimer = setTimeout(() => connect(mine), Math.min(30000, 1500 * retries))
    }
  }
  async function sendMessage(payload, retryEntry) {
    const mine = epoch, id = s.selectedId
    let entry = retryEntry || { payload: { ...payload, client_id: crypto.randomUUID() }, sending: false, error: '' }
    if (entry.sending) return
    if (!retryEntry) { s.outbox.push(entry); entry = s.outbox.at(-1) }
    entry.sending = true; entry.error = ''
    try {
      const message = await api.request(`/projects/${id}/messages`, { method: 'POST', data: entry.payload })
      if (mine !== epoch) return
      acceptMessages([message])
    } catch (error) { if (mine === epoch) entry.error = error.message }
    finally { entry.sending = false }
  }
  async function mutate(path, data, method = 'POST', { refresh = true } = {}) {
    const mine = epoch
    const result = await api.request(path, { method, ...(data !== undefined ? { data } : {}) })
    if (mine === epoch) {
      s.notice = '操作已保存'; s.error = ''
      if (refresh && s.selectedId) await refreshProject()
    }
    return result
  }
  function captureScope() { const mine = epoch; return () => mine === epoch }
  async function createProject(data) {
    const isCurrent = captureScope()
    const project = await mutate('/projects',data,'POST',{ refresh:false })
    if (!isCurrent()) return project
    await loadBasics()
    if (isCurrent()) await selectProject(project.id)
    return project
  }
  async function analyze(mode) {
    const isCurrent = captureScope(), id = s.selectedId, previousStatus = s.agentStatus
    try {
      const result = await api.request(`/projects/${id}/agent/analyze`, { method:'POST',data:{mode} })
      if (isCurrent() && s.agentStatus === previousStatus) s.agentStatus = '分析已排队，等待服务端处理…'
      return result
    } catch (error) { if (isCurrent()) s.agentStatus = `分析请求失败：${error.message}`; throw error }
  }
  async function upload(file) {
    const form = new FormData(); form.append('file', file)
    return mutate(`/projects/${s.selectedId}/files`, form)
  }
  async function download(id, filename) {
    const blob = await api.request(`/files/${Number(id)}`, { blob: true })
    const url = URL.createObjectURL(blob), anchor = document.createElement('a')
    anchor.href = url; anchor.download = filename || `附件-${id}`; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function locateMessage(id) { s.tab = 'collaboration'; s.focusMessage = id }
  return { s, api, init, login, logout, loadBasics, selectProject, refreshProject, loadRequirements, mutate, analyze, createProject, captureScope, upload, download, sendMessage, locateMessage, dispose: closeSocket }
}
