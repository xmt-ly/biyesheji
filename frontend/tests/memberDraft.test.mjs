import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { reactive, effectScope, nextTick } from 'vue'

test('本人资料的未保存草稿不会被队友触发的刷新覆盖，保存后恢复服务端同步', async () => {
  const modulePath = new URL('../src/memberDraft.js',import.meta.url)
  assert.ok(existsSync(modulePath),'尚未实现保留未保存输入的本人资料草稿')
  const { useMemberDraft } = await import(modulePath)
  const source = reactive({ member:{ user_id:3,skills:['Python'],weekly_hours:12 } })
  const scope = effectScope()
  try {
    const draft = scope.run(() => useMemberDraft(() => source.member))
    assert.equal(draft.form.skillsText,'Python')
    draft.form.skillsText = 'Python\nJavaScript';draft.form.weeklyHours = 16
    assert.equal(draft.dirty.value,true)
    source.member = { user_id:3,skills:['Python'],weekly_hours:12 }
    await nextTick()
    assert.equal(draft.form.skillsText,'Python\nJavaScript')
    assert.equal(draft.form.weeklyHours,16)
    source.member = { user_id:3,skills:['Python'],weekly_hours:14 }
    await nextTick()
    assert.equal(draft.form.weeklyHours,16,'远程实际字段变化仍不得清除未提交输入')
    draft.syncSaved({ user_id:3,skills:['Python','JavaScript'],weekly_hours:16 })
    assert.equal(draft.dirty.value,false)
    source.member = { user_id:3,skills:['Python','JavaScript'],weekly_hours:20 }
    await nextTick()
    assert.equal(draft.form.weeklyHours,20,'没有本地草稿时应显示最新服务端资料')
    assert.equal(draft.dirty.value,false)
  } finally { scope.stop() }
})
