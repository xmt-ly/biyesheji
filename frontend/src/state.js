export function mergeMessages(current, incoming) {
  const merged = new Map()
  for (const message of [...current, ...incoming]) {
    const key = message.id != null ? `id:${message.project_id}:${message.id}` : `client:${message.project_id}:${message.user_id}:${message.client_id}`
    merged.set(key, message)
    if (message.id != null && message.client_id) merged.delete(`client:${message.project_id}:${message.user_id}:${message.client_id}`)
  }
  return [...merged.values()].sort((a, b) => (a.id ?? Infinity) - (b.id ?? Infinity))
}

export function canPublishCard(role, card, currentRevision) {
  return role === 'leader' && ['pending', 'ready'].includes(card.status) && card.base_revision === currentRevision && card.checks?.valid === true && !(card.questions?.length)
}

export function canEditTask(user, role, task) {
  return role === 'leader' || (role === 'member' && user?.id === task.assignee_id && task.status !== 'done')
}

export function comparePlans(beforeTasks, afterTasks) {
  const before = new Map(beforeTasks.map(x => [x.id, x]))
  const after = new Map(afterTasks.map(x => [x.id, x]))
  const fields = ['title', 'description', 'requirement_id', 'acceptance', 'assignee_id', 'estimated_hours', 'remaining_hours', 'start_date', 'due_date', 'dependencies', 'stage_index', 'status', 'progress', 'artifact_url', 'blocker']
  return [...new Set([...before.keys(), ...after.keys()])].flatMap(id => {
    const a = before.get(id), b = after.get(id)
    if (!a) return [{ id, kind: 'added', before: null, after: b }]
    if (!b) return [{ id, kind: 'removed', before: a, after: null }]
    return fields.some(key => JSON.stringify(a[key]) !== JSON.stringify(b[key])) ? [{ id, kind: 'changed', before: a, after: b }] : []
  })
}

export function safeUrl(value) {
  if (!value || typeof value !== 'string') return ''
  if (/^\/api\/files\/\d+$/.test(value)) return value
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : '' } catch { return '' }
}

export function buildTaskPayload(form, original, role, correctionReason = '') {
  const fields = role === 'leader' ? ['title','description','requirement_id','acceptance','assignee_id','estimated_hours','remaining_hours','dependencies','start_date','due_date','stage_index','status','progress','artifact_url','blocker'] : ['remaining_hours','status','progress','artifact_url','blocker']
  const data = Object.fromEntries(fields.filter(key => form[key] !== undefined && (!original || JSON.stringify(form[key]) !== JSON.stringify(original[key]))).map(key => [key, form[key]]))
  if (original?.status === 'done' && role === 'leader') data.correction_reason = correctionReason
  return data
}

export function lines(value) { return String(value || '').split('\n').map(x => x.trim()).filter(Boolean) }
export function time(value) { return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—' }
export const statusNames = { todo: '待开始', doing: '进行中', done: '已完成', pending: '待核对', ready: '可发布', published: '已发布', rejected: '已拒绝', stale: '已失效', failed: '失败', passed: '通过', needs_changes: '需修改', draft: '草稿', confirmed: '已确认', preparing: '筹备中', active: '进行中', archived: '已归档' }
