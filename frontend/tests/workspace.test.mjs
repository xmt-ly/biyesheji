import test from 'node:test'
import assert from 'node:assert/strict'
import { createWorkspace } from '../src/workspace.js'
import { safeUrl, mergeMessages, canPublishCard, comparePlans } from '../src/state.js'
import * as state from '../src/state.js'

const response = data => new Response(JSON.stringify(data), { status: 200 })
const storage = () => ({ getItem: () => '', setItem() {}, removeItem() {} })
const project = id => ({ id, course_id:id, role:'member', revision:1, members:[] })

test('项目切换时慢响应不覆盖新项目，也不额外建立旧连接', async () => {
  let release
  const connections = []
  class Socket {
    constructor(url) { connections.push(url) }
    close() {}
  }
  const ws = createWorkspace({ storage:storage(), WebSocketImpl:Socket, locationImpl:{ protocol:'http:',host:'localhost' }, fetchImpl:async url => {
    if (url === '/api/projects/1') return new Promise(resolve => { release = () => resolve(response(project(1))) })
    if (url === '/api/projects/2') return response(project(2))
    if (url === '/api/courses/2') return response({ id:2 })
    return response([])
  } })
  ws.s.user = { id:1,identity:'student' }; ws.s.token = 'token'
  const old = ws.selectProject(1)
  await ws.selectProject(2)
  release(); await old
  assert.equal(ws.s.data.project.id,2)
  assert.equal(connections.length,1)
  assert.match(connections[0],/projects\/2\/ws/)
  ws.dispose()
})

test('教师项目基础加载不请求内部协作、附件目录或运行记录', async () => {
  const calls = []
  const ws = createWorkspace({ storage:storage(), fetchImpl:async url => {
    calls.push(url)
    if (url === '/api/projects/1') return response({ ...project(1),role:'teacher' })
    if (url === '/api/courses/1') return response({ id:1 })
    if (url.endsWith('/submissions')) return response([{ file_ids:[7] }])
    if (url.endsWith('/metadata')) return response({ id:7,filename:'已提交.pdf' })
    return response([])
  } })
  ws.s.user = { id:1,identity:'teacher' }; ws.s.token = 'token'
  await ws.selectProject(1)
  assert.equal(calls.some(path => /\/(messages|cards|agent\/runs|comments)$/.test(path)),false)
  assert.equal(calls.includes('/api/projects/1/files'),false)
  assert.equal(calls.includes('/api/files/7/metadata'),true)
  assert.deepEqual(ws.s.data.files.map(x => x.id),[7])
})

test('教师停留需求清单点击刷新时获得新确认需求，其他页面仍不加载需求', async () => {
  let revision = 1
  const calls = []
  const ws = createWorkspace({ storage:storage(),fetchImpl:async url => {
    calls.push(url)
    if (url === '/api/projects/1') return response({ ...project(1),role:'teacher',revision })
    if (url === '/api/courses/1') return response({ id:1 })
    if (url.endsWith('/requirements')) return response(Array.from({length:revision},(_,i) => ({ id:i+1,status:'confirmed',title:`需求${i+1}` })))
    return response([])
  } })
  ws.s.user = { id:1,identity:'teacher' }; ws.s.token = 'token'
  await ws.selectProject(1)
  assert.equal(calls.includes('/api/projects/1/requirements'),false)
  ws.s.tab = 'requirements';await ws.loadRequirements()
  assert.equal(ws.s.data.requirements.length,1)
  revision = 2;await ws.refreshProject()
  assert.equal(ws.s.data.project.revision,2)
  assert.equal(ws.s.data.requirements.length,2)
  assert.equal(calls.filter(x => x.endsWith('/requirements')).length,2)
  assert.equal(calls.some(path => /\/(messages|cards|agent\/runs|comments)$/.test(path)),false)
})

test('聊天失败重试复用 client_id，HTTP 与广播合并后不重复', async () => {
  const sent = []; let attempt = 0
  const ws = createWorkspace({ storage:storage(), fetchImpl:async (url,init) => {
    const data = JSON.parse(init.body); sent.push(data); attempt++
    return attempt === 1 ? new Response(JSON.stringify({ detail:'暂时离线' }),{ status:503 }) : response({ ...data,id:4,project_id:1,user_id:2 })
  } })
  ws.s.selectedId = 1; ws.s.user = { id:2,identity:'student' }
  await ws.sendMessage({ content:'需要协助' })
  assert.equal(ws.s.outbox.length,1)
  assert.equal(ws.s.outbox[0].error,'暂时离线')
  await ws.sendMessage(null,ws.s.outbox[0])
  assert.equal(sent[0].client_id,sent[1].client_id)
  assert.equal(ws.s.outbox.length,0)
  assert.equal(mergeMessages(ws.s.data.messages,[ws.s.data.messages[0]]).length,1)
})

test('WebSocket已确认本人持久消息时，HTTP中断不保留重复失败副本', async () => {
  let socket
  class Socket { constructor() { socket = this } close() {} }
  const ws = createWorkspace({ storage:storage(),WebSocketImpl:Socket,locationImpl:{protocol:'http:',host:'localhost'},fetchImpl:async (url,init) => {
    if (url === '/api/projects/1') return response(project(1))
    if (url === '/api/courses/1') return response({id:1})
    if (url === '/api/projects/1/messages') {
      const payload = JSON.parse(init.body)
      socket.onmessage({data:JSON.stringify({type:'message',message:{...payload,id:8,project_id:1,user_id:2}})})
      throw new TypeError('Failed to fetch')
    }
    return response([])
  } })
  ws.s.user = {id:2,identity:'student'};ws.s.token = 'token';await ws.selectProject(1)
  await ws.sendMessage({content:'服务端已经收到'})
  assert.equal(ws.s.data.messages.length,1)
  assert.equal(ws.s.outbox.length,0,'已获WS确认的消息不能显示重复发送失败')
  ws.dispose()
})

test('历史补漏确认本人消息后清除同client_id失败待发项', async () => {
  let persisted
  const ws = createWorkspace({ storage:storage(),WebSocketImpl:class{close(){}},locationImpl:{protocol:'http:',host:'localhost'},fetchImpl:async (url,init) => {
    if (url === '/api/projects/1') return response(project(1))
    if (url === '/api/courses/1') return response({id:1})
    if (url === '/api/projects/1/messages') { persisted = {...JSON.parse(init.body),id:8,project_id:1,user_id:2};throw new TypeError('Failed to fetch') }
    if (url.includes('/messages?')) return response(persisted ? [persisted] : [])
    return response([])
  } })
  ws.s.user = {id:2,identity:'student'};ws.s.token = 'token';await ws.selectProject(1)
  await ws.sendMessage({content:'断线后补漏'})
  assert.equal(ws.s.outbox.length,1)
  await ws.refreshProject()
  assert.equal(ws.s.data.messages.length,1)
  assert.equal(ws.s.outbox.length,0)
  ws.dispose()
})

test('断线期间HTTP收到新消息后，重连仍补齐之前缺失的历史', async () => {
  let socket
  const history = []
  const message = id => ({ id,project_id:1,user_id:2,content:`消息${id}` })
  class Socket { constructor() { socket = this } close() {} }
  const ws = createWorkspace({ storage:storage(),WebSocketImpl:Socket,locationImpl:{ protocol:'http:',host:'localhost' },fetchImpl:async (url,init) => {
    if (url === '/api/projects/1') return response(project(1))
    if (url === '/api/courses/1') return response({ id:1 })
    if (url === '/api/projects/1/messages') return response({ ...message(3),...JSON.parse(init.body) })
    if (url.includes('/messages?')) { history.push(url);return response(history.length === 1 ? [message(1)] : [message(2),message(3)]) }
    return response([])
  } })
  ws.s.user = { id:2,identity:'student' }; ws.s.token = 'token'
  await ws.selectProject(1)
  await ws.sendMessage({ content:'消息3' })
  socket.onopen()
  try {
    await new Promise(resolve => setImmediate(resolve))
    assert.match(history[1],/after_id=1&/)
    assert.deepEqual(ws.s.data.messages.map(x => x.id),[1,2,3])
  } finally { ws.dispose() }
})

test('未经确认的问题阻止发布，危险和协议相对链接不可点击', () => {
  assert.equal(canPublishCard('leader',{ status:'ready',base_revision:1,checks:{ valid:true },questions:['工时？'] },1),false)
  for (const value of ['javascript:alert(1)','data:text/html,test','//external.test','/api/files/2/evil','/api/files/../2']) assert.equal(safeUrl(value),'')
  assert.equal(safeUrl('/api/files/2'),'/api/files/2')
  assert.equal(safeUrl('https://example.com/report'),'https://example.com/report')
})

test('计划对比能识别依赖变更、移除且忽略纯更新时间', () => {
  const before = [{ id:1,dependencies:[2],updated_at:'a' },{ id:2 }]
  const after = [{ id:1,dependencies:[],updated_at:'b' }]
  assert.deepEqual(comparePlans(before,after).map(x => x.kind),['changed','removed'])
  assert.equal(comparePlans([{ id:1,updated_at:'a' }],[{ id:1,updated_at:'b' }]).length,0)
})

test('退出后尚未返回的登录恢复请求不重新写入身份', async () => {
  let release
  const ws = createWorkspace({ storage:{ ...storage(),getItem:() => 'saved-token' },fetchImpl:async url => {
    if (url.endsWith('/auth/me')) return new Promise(resolve => { release = () => resolve(response({ id:1,identity:'student' })) })
    return response([])
  } })
  const pending = ws.init(); ws.logout(); release(); await pending
  assert.equal(ws.s.user,null)
  assert.equal(ws.s.token,'')
})

test('旧项目分析请求成功或失败都不污染切换后的分析状态', async () => {
  let release
  const ws = createWorkspace({ storage:storage(),WebSocketImpl:class{close(){}},locationImpl:{ protocol:'http:',host:'localhost' },fetchImpl:async url => {
    if (url.endsWith('/agent/analyze')) return new Promise(resolve => { release = response => resolve(response) })
    if (/\/projects\/[12]$/.test(url)) return response(project(Number(url.split('/').at(-1))))
    if (url.includes('/courses/')) return response({ id:1 })
    return response([])
  } })
  assert.equal(typeof ws.analyze,'function','分析状态尚未受到请求代次保护')
  ws.s.user = { id:1,identity:'student' }; ws.s.token = 'token'
  await ws.selectProject(1)
  const pending = ws.analyze('discussion'); await ws.selectProject(2); release(response({ status:'queued' })); await pending
  assert.equal(ws.s.agentStatus,'')
  const failed = ws.analyze('plan'); ws.logout(); release(new Response(JSON.stringify({ detail:'配置不可用' }),{ status:503 }))
  await assert.rejects(failed,/配置不可用/)
  assert.equal(ws.s.agentStatus,'')
  ws.dispose()
})

test('创建项目请求迟到时不会把用户从已切换项目拉回新建项目', async () => {
  let release
  const ws = createWorkspace({ storage:storage(),WebSocketImpl:class{close(){}},locationImpl:{protocol:'http:',host:'localhost' },fetchImpl:async (url,init) => {
    if (url === '/api/projects' && init.method === 'POST') return new Promise(resolve => { release = () => resolve(response(project(1))) })
    if (url === '/api/projects/2') return response(project(2))
    if (url === '/api/courses/2') return response({ id:2 })
    return response([])
  } })
  assert.equal(typeof ws.createProject,'function','项目创建与导航尚未由会话范围统一保护')
  ws.s.user = { id:1,identity:'student' };ws.s.token = 'token'
  const pending = ws.createProject({ course_id:1,name:'新建项目',description:'' })
  await ws.selectProject(2);release();await pending
  assert.equal(ws.s.selectedId,2)
  assert.equal(ws.s.data.project.id,2)
  ws.dispose()
})

test('组长仅改实际进度时不发送未变的排期字段，成员载荷不包含规划字段', () => {
  assert.equal(typeof state.buildTaskPayload,'function','尚未实现最小任务更新载荷')
  const { buildTaskPayload } = state
  const original = { title:'任务',assignee_id:2,status:'doing',progress:10,remaining_hours:6,start_date:'2026-10-12',due_date:'2026-10-15',dependencies:[] }
  const form = { ...original,progress:30,remaining_hours:4 }
  assert.deepEqual(buildTaskPayload(form,original,'leader'),{ progress:30,remaining_hours:4 })
  assert.deepEqual(buildTaskPayload({ ...form,title:'越权改名' },original,'member'),{ progress:30,remaining_hours:4 })
  const corrected = buildTaskPayload({ ...original,status:'doing' },{ ...original,status:'done' },'leader','纠正误报')
  assert.equal(corrected.correction_reason,'纠正误报')
})
