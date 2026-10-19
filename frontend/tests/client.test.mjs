import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'

const apiPath = new URL('../src/api.js', import.meta.url)
const statePath = new URL('../src/state.js', import.meta.url)

async function api() {
  assert.ok(existsSync(apiPath), 'API 客户端尚未实现')
  return import(apiPath)
}

async function state() {
  assert.ok(existsSync(statePath), '协作状态处理尚未实现')
  return import(statePath)
}

test('服务器失败必须向界面传播，不能把失败变成空列表', async () => {
  const { createApiClient } = await api()
  const client = createApiClient({
    getToken: () => 'demo-token',
    fetchImpl: async () => new Response(JSON.stringify({ detail: '模型接口暂不可用' }), { status: 503 }),
  })
  await assert.rejects(client.request('/projects/1/cards'), /模型接口暂不可用/)
})

test('网络中断显示明确中文连接错误而不是空数据', async () => {
  const { createApiClient } = await api()
  const client = createApiClient({ fetchImpl:async () => { throw new TypeError('Failed to fetch') } })
  await assert.rejects(client.request('/projects'),/网络连接失败/)
})

test('每次请求读取当前登录身份，并携带 JSON 请求体', async () => {
  const { createApiClient } = await api()
  let token = 'first'
  const calls = []
  const client = createApiClient({
    getToken: () => token,
    fetchImpl: async (url, init) => {
      calls.push({ url, init })
      return new Response(JSON.stringify({ id: 1 }), { status: 200 })
    },
  })
  await client.request('/projects', { method: 'POST', data: { name: '课程项目' } })
  token = 'second'
  await client.request('/projects')
  assert.equal(calls[0].url, '/api/projects')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer first')
  assert.deepEqual(JSON.parse(calls[0].init.body), { name: '课程项目' })
  assert.equal(calls[1].init.headers.Authorization, 'Bearer second')
})

test('登录失效调用统一退出处理，同时保留请求失败', async () => {
  const { createApiClient } = await api()
  let expired = 0
  const client = createApiClient({
    getToken: () => 'expired',
    onUnauthorized: () => expired++,
    fetchImpl: async () => new Response(JSON.stringify({ detail: '登录已失效' }), { status: 401 }),
  })
  await assert.rejects(client.request('/auth/me'), /登录已失效/)
  assert.equal(expired, 1)
})

test('旧身份的延迟 401 不退出新的登录会话，登录输错密码不清理会话', async () => {
  const { createApiClient } = await api()
  let token = 'old', expired = 0, release
  const client = createApiClient({ getToken:() => token,onUnauthorized:() => expired++,fetchImpl:() => new Promise(resolve => { release = () => resolve(new Response(JSON.stringify({detail:'旧身份失效'}),{status:401})) }) })
  const pending = client.request('/auth/me')
  token = 'new'; release()
  await assert.rejects(pending,/旧身份失效/)
  assert.equal(expired,0)
  const badLogin = client.request('/auth/login',{method:'POST',data:{username:'name',password:'bad'}})
  release(); await assert.rejects(badLogin,/旧身份失效/)
  assert.equal(expired,0)
})

test('输入校验错误应展示字段及实际错误消息', async () => {
  const { createApiClient } = await api()
  const client = createApiClient({
    getToken: () => '',
    fetchImpl: async () => new Response(JSON.stringify({
      detail: [{ loc: ['body', 'estimated_hours'], msg: '工时必须大于等于零' }],
    }), { status: 422 }),
  })
  await assert.rejects(client.request('/tasks/1', { method: 'PATCH', data: {} }), /estimated_hours.*工时必须大于等于零/)
})

test('实时广播和重连历史合并后不重复展示消息', async () => {
  const { mergeMessages } = await state()
  const result = mergeMessages(
    [{ id: 4, project_id: 1, client_id: 'a', user_id: 1, content: '第一条' }],
    [
      { id: 4, project_id: 1, client_id: 'a', user_id: 1, content: '第一条' },
      { id: 5, project_id: 1, client_id: 'b', user_id: 2, content: '第二条' },
    ],
  )
  assert.deepEqual(result.map(x => x.id), [4, 5])
})

test('教师和普通成员不能发布卡片，旧版本建议不能直接发布', async () => {
  const { canPublishCard } = await state()
  const card = { status: 'ready', base_revision: 3, checks: { valid: true } }
  assert.equal(canPublishCard('teacher', card, 3), false)
  assert.equal(canPublishCard('member', card, 3), false)
  assert.equal(canPublishCard('leader', card, 4), false)
  assert.equal(canPublishCard('leader', card, 3), true)
  assert.equal(canPublishCard('leader', { ...card, status: 'published' }, 3), false)
  assert.equal(canPublishCard('leader', { ...card, checks: { valid: false } }, 3), false)
})

test('成员只能推进本人任务，教师没有任务编辑入口', async () => {
  const { canEditTask } = await state()
  const task = { assignee_id: 3 }
  assert.equal(canEditTask({ id: 3 }, 'member', task), true)
  assert.equal(canEditTask({ id: 4 }, 'member', task), false)
  assert.equal(canEditTask({ id: 4 }, 'leader', task), true)
  assert.equal(canEditTask({ id: 4 }, 'teacher', task), false)
})

test('计划比较根据历史快照显示负责人和日期的真实变化', async () => {
  const { comparePlans } = await state()
  const before = [{ id: 1, title: '接口', assignee_id: 2, due_date: '2026-10-15' }]
  const after = [
    { id: 1, title: '接口', assignee_id: 3, due_date: '2026-10-17' },
    { id: 2, title: '联调', assignee_id: 2, due_date: '2026-10-18' },
  ]
  const result = comparePlans(before, after)
  assert.equal(result.length, 2)
  const changed = result.find(x => x.id === 1)
  assert.equal(changed.kind, 'changed')
  assert.equal(changed.before.due_date, '2026-10-15')
  assert.equal(changed.after.assignee_id, 3)
  assert.equal(result.find(x => x.id === 2).kind, 'added')
})
