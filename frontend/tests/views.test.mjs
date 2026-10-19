import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'

test('成员本人任务详情在可编辑进度旁保留需求、验收、排期与前置依据', async () => {
  globalThis.document = { activeElement:null }
  const server = await createServer({ server:{middlewareMode:true},appType:'custom' })
  try {
    const component = (await server.ssrLoadModule('/src/components/TaskDetails.vue')).default
    const task = { id:2,title:'本人任务',assignee_id:3,description:'任务上下文_SENTINEL',requirement_id:7,acceptance:'验收条件_SENTINEL',estimated_hours:6,remaining_hours:4,start_date:'2026-10-12',due_date:'2026-10-18',stage_index:1,status:'doing',progress:20,dependencies:[1],artifact_url:'',blocker:'' }
    const ws = { s:{ user:{id:3,identity:'student'},selectedId:1,data:{project:{role:'member',members:[{user_id:3,name:'成员'}]},requirements:[{id:7,title:'关联需求_SENTINEL'}],tasks:[{id:1,title:'前置任务_SENTINEL'},task],course:{stages:[{name:'阶段一'},{name:'中期阶段_SENTINEL'}]}}},api:{request:async()=>[]} }
    const html = await renderToString(createSSRApp({render:()=>h(component,{task})}).provide('workspace',ws))
    for (const expected of ['任务上下文_SENTINEL','验收条件_SENTINEL','关联需求_SENTINEL','前置任务_SENTINEL','2026-10-12','2026-10-18','中期阶段_SENTINEL']) assert.ok(html.includes(expected),`缺少任务依据：${expected}`)
    assert.ok(html.includes('实际进度'))
    assert.equal(html.includes('任务名称<input'),false,'普通成员不能得到规划编辑表单')
  } finally { await server.close();delete globalThis.document }
})
