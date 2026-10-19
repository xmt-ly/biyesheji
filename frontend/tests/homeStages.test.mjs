import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, createSSRApp, h, markRaw, nextTick, reactive } from 'vue'
import { renderToString } from '@vue/server-renderer'

async function componentUrl(path) {
  const location = new URL(path, import.meta.url)
  const { descriptor } = parse(await readFile(location, 'utf8'))
  let code = compileScript(descriptor, { id: location.href, inlineTemplate: true }).content
  code = code.replace(/from (['"])vue\1/g, `from ${JSON.stringify(import.meta.resolve('vue'))}`)
  for (const match of [...code.matchAll(/from (['"])(\.\.?\/[^'"]+)\1/g)]) {
    const dependency = new URL(match[2], location)
    const url = dependency.pathname.endsWith('.vue') ? await componentUrl(dependency.href) : dependency.href
    code = code.replace(match[0], `from ${JSON.stringify(url)}`)
  }
  return `data:text/javascript,${encodeURIComponent(code)}`
}

function descendants(root) { return root.children.flatMap(item => [item, ...descendants(item)]) }
function textOf(root) { return [root.text, ...root.children.map(textOf)].join('') }
function surface() {
  globalThis.Document = class {}
  const doc = Object.assign(new Document(), { activeElement: null, body: { style: {} }, addEventListener() {}, removeEventListener() {} })
  function node(tag, text = '') {
    const value = { tag, tagName: tag.toUpperCase(), text, children: [], props: {}, parent: null, isConnected: true, get options() { return value.children.filter(child => child.tag === 'option') }, getRootNode() { return doc }, focus() { doc.activeElement = value }, contains(item) { return item === value || value.children.some(child => child.contains(item)) }, querySelectorAll() { return [] }, addEventListener() {}, removeEventListener() {} }
    return markRaw(value)
  }
  const renderer = createRenderer({
    createElement: tag => node(tag), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (item, text) => { item.text = text }, setElementText: (item, text) => { item.text = text; item.children = [] },
    patchProp: (item, key, before, after) => { item.props[key] = after },
    insert(item, parent, anchor = null) { if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1); item.parent = parent; const index = parent.children.indexOf(anchor); if (index < 0) parent.children.push(item); else parent.children.splice(index, 0, item) },
    remove(item) { item.isConnected = false; item.parent.children.splice(item.parent.children.indexOf(item), 1) },
    parentNode: item => item.parent, nextSibling: item => item.parent?.children[item.parent.children.indexOf(item) + 1] || null,
  })
  const root = node('root')
  globalThis.document = doc
  return { root, renderer, find: predicate => descendants(root).find(predicate) }
}

function workspace(identity = 'student', role = 'member') {
  return { s: reactive({ user: { id: 3, identity, name: '成员甲' }, projects: [{ id: 1, name: '一组项目', role, members: [] }], courses: [{ id: 2, title: '软件工程' }], selectedId: 1, tab: 'home', loading: false, data: { project: { id: 1, name: '一组项目', role, members: [{ user_id: 3, name: '成员甲' }, { user_id: 4, name: '成员乙' }] }, course: { stages: [{ name: '需求与计划检查', deadline: '2026-10-25', deliverables: ['需求清单', '开发计划'] }, { name: '开发中期', deadline: '2026-11-15', deliverables: ['中期成果'] }, { name: '最终验收', deadline: '2026-12-06', deliverables: ['最终材料'] }] }, tasks: [], cards: [], submissions: [], files: [], requirements: [], progress: { done: 0, total: 2, completion_percent: 0 }, messages: [] } }), captureScope: () => () => true, loadBasics() {}, selectProject() {}, mutate: async () => {}, download: async () => {}, api: { request: async () => [] } }
}
const task = (id, owner, title, values = {}) => ({ id, assignee_id: owner, title, status: 'todo', progress: 0, blocker: '', planning_risks: [], description: '', acceptance: '', remaining_hours: 4, estimated_hours: 6, start_date: '2026-10-12', due_date: '2026-10-20', stage_index: 0, dependencies: [], ...values })

test('工作台本人任务和协同关注分开，本人阻碍任务可直接打开推进抽屉', async () => {
  const Home = (await import(await componentUrl('../src/views/HomeView.vue'))).default
  const ws = workspace(), ui = surface()
  ws.s.data.tasks = [task(1, 3, '本人普通任务'), task(2, 3, '本人阻碍任务', { blocker: '等待接口说明', due_date: '2026-10-22' }), task(3, 4, '协同关注任务')]
  const app = ui.renderer.createApp(Home).provide('workspace', ws)
  try {
    app.mount(ui.root)
    const mine = ui.find(item => item.props['aria-label'] === '本人任务')
    const team = ui.find(item => item.props['aria-label'] === '协同关注')
    assert.ok(mine && team, '工作台应明确区分本人工作和其他成员工作')
    assert.ok(textOf(mine).includes('本人普通任务'))
    assert.equal(textOf(mine).includes('协同关注任务'), false)
    assert.ok(textOf(team).includes('协同关注任务'))
    const next = ui.find(item => item.props['aria-label'] === '我的下一步')
    assert.ok(textOf(next).includes('本人阻碍任务'))
    ui.find(item => item.tag === 'button' && textOf(item).includes('继续本人任务')).props.onClick()
    await nextTick()
    assert.ok(ui.find(item => item.props.role === 'dialog' && item.props['aria-label'] === '本人阻碍任务'))
    assert.equal(ws.s.tab, 'home', '本人任务应在当前工作台直接推进')
  } finally { app.unmount(); delete globalThis.document; delete globalThis.Document }
})

test('教师工作台显示指导项目与课程，不渲染内部卡片、消息和本人推进入口', async () => {
  const Home = (await import(await componentUrl('../src/views/HomeView.vue'))).default
  const ws = workspace('teacher', 'teacher')
  ws.s.data.cards = [{ id: 1, status: 'ready', title: '内部卡片_SENTINEL' }]
  ws.s.data.messages = [{ id: 1, content: '内部消息_SENTINEL' }]
  ws.s.data.tasks = [task(1, 3, '教师本人任务_SENTINEL')]
  const html = await renderToString(createSSRApp(Home).provide('workspace', ws))
  for (const value of ['我的指导项目', '我的课程', '需求与计划检查']) assert.ok(html.includes(value), `缺少教师公开内容：${value}`)
  for (const value of ['内部卡片_SENTINEL', '内部消息_SENTINEL', '教师本人任务_SENTINEL', '继续本人任务', '待核对安排']) assert.equal(html.includes(value), false, `教师界面泄露内部信息：${value}`)
})

test('工作台任务抽屉收到团队刷新后只提交本人实际编辑的字段，不回滚新排期', async () => {
  const Home = (await import(await componentUrl('../src/views/HomeView.vue'))).default
  const ws = workspace('student', 'leader'), ui = surface(), requests = []
  ws.s.data.tasks = [task(1, 3, '本人接口任务', { progress: 20 })]
  ws.mutate = async (...args) => { requests.push(args) }
  const app = ui.renderer.createApp(Home).provide('workspace', ws)
  try {
    app.mount(ui.root)
    ui.find(item => item.tag === 'button' && textOf(item).includes('继续本人任务')).props.onClick()
    await nextTick()
    const progress = ui.find(item => item.tag === 'input' && item.props.type === 'number' && item.props.max === '100')
    assert.ok(progress, '本人任务应有实际进度字段')
    progress.props['onUpdate:modelValue'](40)
    ws.s.data.tasks = [{ ...ws.s.data.tasks[0], due_date: '2026-10-25', estimated_hours: 8, dependencies: [2] }]
    await nextTick()
    assert.ok(textOf(ui.root).includes('2026-10-25'), '只读任务依据应显示刷新后的排期')
    const save = ui.find(item => item.tag === 'form' && descendants(item).some(child => child.tag === 'button' && textOf(child).includes('保存任务')))
    await save.props.onSubmit({ preventDefault() {} })
    assert.deepEqual(requests, [['/tasks/1', { progress: 40 }, 'PATCH']], '未编辑的排期、工时、依赖不能随进度保存被回滚')
  } finally { app.unmount(); delete globalThis.document; delete globalThis.Document }
})

test('组长纠正刷新后已完成的任务时仍提交当前完成状态要求的原因', async () => {
  const Home = (await import(await componentUrl('../src/views/HomeView.vue'))).default
  const ws = workspace('student', 'leader'), ui = surface(), requests = []
  ws.s.data.tasks = [task(1, 3, '本人接口任务', { progress: 20 })]
  ws.mutate = async (...args) => { requests.push(args) }
  const app = ui.renderer.createApp(Home).provide('workspace', ws)
  try {
    app.mount(ui.root)
    ui.find(item => item.tag === 'button' && textOf(item).includes('继续本人任务')).props.onClick()
    await nextTick()
    ui.find(item => item.tag === 'input' && item.props.max === '100').props['onUpdate:modelValue'](40)
    ui.find(item => item.tag === 'select' && item.children.some(child => child.props.value === 'doing')).props['onUpdate:modelValue']('doing')
    ws.s.data.tasks = [{ ...ws.s.data.tasks[0], status: 'done', progress: 100, remaining_hours: 0 }]
    await nextTick()
    ui.find(item => item.tag === 'textarea' && item.props.placeholder === '请记录纠正内容和原因').props['onUpdate:modelValue']('完成记录需补充测试')
    const save = ui.find(item => item.tag === 'form' && descendants(item).some(child => child.tag === 'button' && textOf(child).includes('保存任务')))
    await save.props.onSubmit({ preventDefault() {} })
    assert.deepEqual(requests, [['/tasks/1', { status: 'doing', progress: 40, correction_reason: '完成记录需补充测试' }, 'PATCH']])
  } finally { app.unmount(); delete globalThis.document; delete globalThis.Document }
})

test('第一条消息等待发送结果时输入的新草稿和关联选择不会被迟到响应清空', async () => {
  const Collaboration = (await import(await componentUrl('../src/views/CollaborationView.vue'))).default
  const ws = workspace(), ui = surface(), messages = []
  ws.s.outbox = []; ws.s.data.runs = []; ws.s.connection = '已连接'
  ws.s.data.tasks = [task(1, 3, '本人接口任务')]
  let finishFirst
  ws.sendMessage = async payload => {
    messages.push(payload)
    if (messages.length === 1) await new Promise(resolve => { finishFirst = resolve })
  }
  const app = ui.renderer.createApp(Collaboration).provide('workspace', ws)
  try {
    app.mount(ui.root)
    const composer = ui.find(item => item.tag === 'textarea' && item.props.id === 'message-content')
    const form = ui.find(item => item.tag === 'form' && item.props.class === 'chat-composer')
    composer.props['onUpdate:modelValue']('第一条消息')
    const firstSend = form.props.onSubmit({ preventDefault() {} })
    await nextTick()
    composer.props['onUpdate:modelValue']('等待期间输入的第二条草稿')
    ui.find(item => item.tag === 'select' && item.children.some(child => child.props.value === 'requirement')).props['onUpdate:modelValue']('task')
    await nextTick()
    ui.find(item => item.tag === 'select' && item.children.some(child => child.props.value === 1)).props['onUpdate:modelValue'](1)
    finishFirst()
    await firstSend
    await nextTick()
    assert.ok(textOf(ui.root).includes('选择任务'), '等待期间选择的新关联对象应保留')
    await form.props.onSubmit({ preventDefault() {} })
    assert.deepEqual(messages, [
      { content: '第一条消息', supersedes_card_ids: [] },
      { content: '等待期间输入的第二条草稿', related_type: 'task', related_id: 1, supersedes_card_ids: [] },
    ], '第二条消息应保留当前未发送内容和关联，而非复用或清空第一条草稿')
  } finally { app.unmount(); delete globalThis.document; delete globalThis.Document }
})

test('未选项目时以项目入口为主，选中后只显示 API 完成数量比例', async () => {
  const Home = (await import(await componentUrl('../src/views/HomeView.vue'))).default
  const ws = workspace()
  ws.s.selectedId = null
  ws.s.data.tasks = [task(1, 3, '不可展示的旧项目任务_SENTINEL', { progress: 80 })]
  let html = await renderToString(createSSRApp(Home).provide('workspace', ws))
  assert.ok(html.includes('先选择一个团队项目'))
  assert.ok(html.includes('我的团队项目'))
  assert.equal(html.includes('不可展示的旧项目任务_SENTINEL'), false)
  ws.s.selectedId = 1
  html = await renderToString(createSSRApp(Home).provide('workspace', ws))
  assert.ok(html.includes('任务完成 0 / 2 项 · 0%'))
  assert.equal(html.includes('任务完成 0 / 2 项 · 80%'), false)
})

test('查看旧阶段版本保留旧材料和快照，当前阶段状态仍依据最新提交并在刷新后保留选择', async () => {
  const Stages = (await import(await componentUrl('../src/views/StagesView.vue'))).default
  const ws = workspace('teacher', 'teacher'), ui = surface()
  ws.s.data.files = [{ id: 4, filename: '旧材料.pdf' }, { id: 5, filename: '新材料.pdf' }]
  const old = { id: 11, stage_index: 0, version: 1, summary: '旧版说明_SENTINEL', created_at: '2026-10-10T02:00:00Z', status: 'needs_changes', plan_version: 1, file_ids: [4], materials: { '需求清单': ['file:4'] }, reviews: [{ reviewer_name: '教师', result: 'needs_changes', comment: '旧版意见_SENTINEL' }], progress_snapshot: { done: 0, total: 2, completion_percent: 0, tasks: [] } }
  const latest = { ...old, id: 12, version: 2, summary: '新版说明_SENTINEL', status: 'passed', plan_version: 2, file_ids: [5], materials: { '需求清单': ['file:5'] }, reviews: [], progress_snapshot: { done: 2, total: 2, completion_percent: 100, tasks: [] } }
  ws.s.data.submissions = [old, latest]
  const app = ui.renderer.createApp(Stages).provide('workspace', ws)
  try {
    app.mount(ui.root)
    const oldButton = ui.find(item => item.tag === 'button' && item.props['aria-label'] === '查看需求与计划检查提交 v1')
    assert.ok(oldButton, '每个历史版本须可单独选择')
    oldButton.props.onClick()
    await nextTick()
    let detail = ui.find(item => item.props['aria-label'] === '选中提交详情')
    assert.ok(textOf(detail).includes('旧版说明_SENTINEL'))
    assert.ok(textOf(detail).includes('旧版意见_SENTINEL'))
    assert.ok(textOf(detail).includes('旧材料.pdf'))
    assert.equal(textOf(detail).includes('新版说明_SENTINEL'), false)
    assert.ok(textOf(detail).includes('完成 0 / 2 项'))
    const stages = ui.find(item => item.props['aria-label'] === '阶段与提交版本')
    assert.ok(textOf(stages).includes('当前状态：通过'))
    ws.s.data.submissions = [...ws.s.data.submissions, { ...latest, id: 13, version: 3, status: 'pending' }]
    await nextTick()
    detail = ui.find(item => item.props['aria-label'] === '选中提交详情')
    assert.ok(textOf(detail).includes('旧版说明_SENTINEL'), '实时刷新不应跳走仍存在的历史版本')
    assert.ok(textOf(stages).includes('当前状态：待审核'))
  } finally { app.unmount(); delete globalThis.document; delete globalThis.Document }
})

test('阶段提交仅提供给学生组长，教师不显示内部文件目录和上传入口', async () => {
  const Stages = (await import(await componentUrl('../src/views/StagesView.vue'))).default
  for (const [identity, role, canSubmit, canUpload] of [['student', 'leader', true, true], ['student', 'member', false, true], ['teacher', 'teacher', false, false]]) {
    const ws = workspace(identity, role)
    ws.s.data.files = [{ id: 9, filename: '内部附件_SENTINEL', size: 200 }]
    const html = await renderToString(createSSRApp(Stages).provide('workspace', ws))
    assert.equal([...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].some(match => match[1].includes('提交阶段成果')), canSubmit, `${identity}/${role}提交权限不正确`)
    assert.equal(html.includes('选择并上传成果文件'), canUpload, `${identity}/${role}上传权限不正确`)
    if (identity === 'teacher') assert.equal(html.includes('内部附件_SENTINEL'), false)
  }
})

test('组长逐项映射多个交付物，缺少材料时保留表单且不提交', async () => {
  const Stages = (await import(await componentUrl('../src/views/StagesView.vue'))).default
  const ws = workspace('student', 'leader'), ui = surface(), calls = []
  ws.mutate = async (path, payload) => calls.push({ path, payload })
  const app = ui.renderer.createApp(Stages).provide('workspace', ws)
  try {
    app.mount(ui.root)
    ui.find(item => item.tag === 'button' && textOf(item).includes('提交阶段成果')).props.onClick()
    await nextTick()
    const explanation = ui.find(item => item.tag === 'textarea' && item.props.placeholder?.startsWith('说明已完成'))
    const links = ui.find(item => item.tag === 'textarea' && item.props.placeholder === 'https://...')
    explanation.props['onUpdate:modelValue']('整理后的阶段说明')
    links.props['onUpdate:modelValue']('https://example.com/requirements\nhttps://example.com/plan')
    await nextTick()
    const form = ui.find(item => item.tag === 'form')
    const event = { preventDefault() {} }
    await form.props.onSubmit(event)
    await nextTick()
    assert.equal(calls.length, 0)
    assert.ok(textOf(ui.root).includes('请逐项为每个必需交付物选择材料'))
    const mappings = descendants(ui.root).filter(item => item.tag === 'fieldset' && !textOf(item).includes('选择团队已上传附件'))
    const choose = (fieldset, value) => descendants(fieldset).find(item => item.tag === 'input' && item.props.type === 'checkbox').props['onUpdate:modelValue']([value])
    choose(mappings[0], 'https://example.com/requirements')
    choose(mappings[1], 'https://example.com/plan')
    await nextTick()
    await form.props.onSubmit(event)
    await nextTick()
    assert.equal(calls.length, 1)
    assert.deepEqual(calls[0], { path: '/projects/1/submissions', payload: { stage_index: 0, summary: '整理后的阶段说明', artifact_urls: ['https://example.com/requirements', 'https://example.com/plan'], file_ids: [], materials: { '需求清单': ['https://example.com/requirements'], '开发计划': ['https://example.com/plan'] } } })
  } finally { app.unmount(); delete globalThis.document; delete globalThis.Document }
})

test('教师可为选中的历史提交追加意见并下载其材料，原版本数据保持不变', async () => {
  const Stages = (await import(await componentUrl('../src/views/StagesView.vue'))).default
  const ws = workspace('teacher', 'teacher'), ui = surface(), calls = [], downloads = []
  ws.s.data.files = [{ id: 4, filename: '已提交材料.pdf' }]
  ws.s.data.submissions = [{ id: 11, stage_index: 0, version: 1, summary: '第一版', status: 'needs_changes', plan_version: 1, materials: { '需求清单': ['file:4'] }, reviews: [{ result: 'needs_changes', comment: '第一条意见' }] }, { id: 12, stage_index: 0, version: 2, summary: '第二版', status: 'passed', materials: {}, reviews: [] }]
  const original = JSON.stringify(ws.s.data.submissions)
  ws.mutate = async (path, payload) => calls.push({ path, payload })
  ws.download = async (id, filename) => downloads.push({ id, filename })
  const app = ui.renderer.createApp(Stages).provide('workspace', ws)
  try {
    app.mount(ui.root)
    ui.find(item => item.props['aria-label'] === '查看需求与计划检查提交 v1').props.onClick()
    await nextTick()
    await ui.find(item => item.tag === 'button' && textOf(item).includes('下载文件')).props.onClick()
    assert.deepEqual(downloads, [{ id: 4, filename: '已提交材料.pdf' }])
    ui.find(item => item.tag === 'button' && textOf(item).includes('提交审核意见')).props.onClick()
    await nextTick()
    ui.find(item => item.tag === 'select').props['onUpdate:modelValue']('needs_changes')
    ui.find(item => item.tag === 'textarea').props['onUpdate:modelValue']('补充历史记录意见')
    await nextTick()
    await ui.find(item => item.tag === 'form').props.onSubmit({ preventDefault() {} })
    await nextTick()
    assert.deepEqual(calls, [{ path: '/submissions/11/review', payload: { result: 'needs_changes', comment: '补充历史记录意见' } }])
    assert.equal(JSON.stringify(ws.s.data.submissions), original)
  } finally { app.unmount(); delete globalThis.document; delete globalThis.Document }
})
