import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createSSRApp, reactive } from 'vue'
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

const Plans = (await import(await componentUrl('../src/views/PlansView.vue'))).default
const baseTask = { id: 1, title: '接口开发', description: '接口说明', requirement_id: 1, acceptance: '验收标准', assignee_id: 3, estimated_hours: 6, remaining_hours: 4, start_date: '2026-10-12', due_date: '2026-10-20', dependencies: [], stage_index: 0, status: 'todo', progress: 0, artifact_url: '', blocker: '' }

async function compare(before, after) {
  const plans = [{ id: 1, version: 1, created_at: '2026-10-12T01:00:00Z', summary: '初始安排', tasks: [before] }, { id: 2, version: 2, created_at: '2026-10-13T01:00:00Z', summary: '修订安排', tasks: [after] }]
  const original = JSON.stringify(plans)
  const ws = { s: reactive({ user: { id: 3, identity: 'student' }, data: { plans, tasks: [after], project: { members: [{ user_id: 3, name: '成员甲', weekly_hours: 12 }] }, requirements: [{ id: 1, title: '账号管理' }, { id: 2, title: '团队邀请' }], course: { stages: [{ name: '需求检查' }, { name: '中期检查' }, { name: '最终验收' }] }, progress: {} } }) }
  const html = await renderToString(createSSRApp(Plans).provide('workspace', ws))
  assert.equal(JSON.stringify(plans), original, '展示比较不能改写历史快照')
  const body = html.match(/<tbody>([\s\S]*?)<\/tbody>/)?.[1]
  const cells = [...body.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map(match => match[1])
  assert.equal(cells.length, 3, '应出现任务信息、变更前和变更后三个比较区域')
  return { before: cells[1], after: cells[2] }
}

test('计划比较在对应前后列展示任务名称、说明、需求、验收、阶段、成果和阻碍的真实变化', async () => {
  const before = { ...baseTask, title: '旧任务名', description: '旧说明', acceptance: '旧验收条件', artifact_url: 'https://example.com/old-result', blocker: '旧阻碍' }
  const after = { ...baseTask, title: '新任务名', description: '新说明', requirement_id: 2, acceptance: '新验收条件', stage_index: 1, artifact_url: 'https://example.com/new-result', blocker: '新阻碍' }
  const cells = await compare(before, after)
  for (const value of ['旧任务名', '旧说明', '账号管理', '旧验收条件', '需求检查', 'https://example.com/old-result', '旧阻碍']) assert.ok(cells.before.includes(value), `变更前缺少 ${value}`)
  for (const value of ['新任务名', '新说明', '团队邀请', '新验收条件', '中期检查', 'https://example.com/new-result', '新阻碍']) assert.ok(cells.after.includes(value), `变更后缺少 ${value}`)
  assert.equal(cells.before.includes('新验收条件'), false)
  assert.equal(cells.after.includes('旧验收条件'), false)
})

test('只改变验收条件也可在计划前后列查明具体变化', async () => {
  const cells = await compare({ ...baseTask, acceptance: '返回 401' }, { ...baseTask, acceptance: '返回 403' })
  assert.ok(cells.before.includes('返回 401'))
  assert.ok(cells.after.includes('返回 403'))
  assert.equal(cells.before.includes('返回 403'), false)
  assert.equal(cells.after.includes('返回 401'), false)
})
