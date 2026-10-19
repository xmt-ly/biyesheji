import test from 'node:test'
import assert from 'node:assert/strict'

async function model() { return (await import('../src/workbench.js')).buildWorkbench }

const task = (id, assignee, values = {}) => ({ id, assignee_id:assignee, title:`任务${id}`, status:'todo', blocker:'', planning_risks:[], due_date:'2026-10-20', remaining_hours:6, ...values })

test('本人工作台不把他人任务计入本人数量，优先展示本人阻碍与待推进任务', async () => {
  const build = await model()
  const result = build({ userId:3, tasks:[task(1,3,{status:'done'}),task(2,3,{due_date:'2026-10-14'}),task(3,3,{status:'doing',blocker:'等待接口'}),task(4,4,{blocker:'其他人的问题'})], cards:[], stages:[], submissions:[] })
  assert.deepEqual(result.myTasks.map(t=>t.id),[1,2,3])
  assert.equal(result.activeTasks.length,2)
  assert.equal(result.nextTask.id,3)
  assert.equal(result.teamTasks.length,1)
  assert.equal(result.teamTasks[0].id,4)
})

test('阶段提醒只依据各阶段最新提交，旧版需修改不会覆盖新版本通过', async () => {
  const build = await model()
  const stages=[{name:'计划'},{name:'中期'},{name:'最终'}]
  const result=build({userId:3,tasks:[],cards:[],stages,submissions:[{id:1,stage_index:0,version:1,status:'needs_changes'},{id:2,stage_index:0,version:2,status:'passed'},{id:3,stage_index:1,version:1,status:'pending'}]})
  assert.equal(result.stageItems[0].submission.id,2)
  assert.equal(result.stageItems[0].status,'passed')
  assert.equal(result.stageItems[1].status,'pending')
  assert.equal(result.stageItems[2].status,'unsubmitted')
  assert.equal(result.nextStage.index,1)
})

test('已完成本人任务不再成为下一步，已发布和失效卡片不计入待核对数量', async () => {
  const build=await model()
  const result=build({userId:3,tasks:[task(1,3,{status:'done'})],cards:[{id:1,status:'ready'},{id:2,status:'pending'},{id:3,status:'published'},{id:4,status:'stale'}],stages:[{name:'检查'}],submissions:[{stage_index:0,version:1,status:'passed'}]})
  assert.equal(result.nextTask,null)
  assert.equal(result.nextStage,null)
  assert.deepEqual(result.pendingCards.map(c=>c.id),[1,2])
})
