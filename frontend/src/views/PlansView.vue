<script setup>
import { computed, inject, ref, watch } from 'vue'
import { comparePlans, time, statusNames } from '../state.js'
import Checks from '../components/Checks.vue'
import AppIcon from '../components/AppIcon.vue'
const ws = inject('workspace'), s = ws.s, beforeId = ref(''), afterId = ref('')
watch(() => s.data.plans, plans => { if (!plans.length) return; if (!plans.some(x => x.id === Number(afterId.value))) afterId.value = plans.at(-1).id; if (!plans.some(x => x.id === Number(beforeId.value))) beforeId.value = plans.at(-2)?.id || '' }, { immediate:true })
const before = computed(() => s.data.plans.find(x => x.id === Number(beforeId.value)))
const after = computed(() => s.data.plans.find(x => x.id === Number(afterId.value)))
const diff = computed(() => comparePlans(before.value?.tasks || [], after.value?.tasks || []))
const schedule = computed(() => after.value?.tasks || s.data.tasks)
const members = computed(() => s.data.project?.members || [])
const name = id => members.value.find(x => x.user_id === id)?.name || `成员 ${id}`
const workload = computed(() => members.value.map(member => ({ ...member, hours:s.data.tasks.filter(x => x.assignee_id === member.user_id && x.status !== 'done').reduce((total,x) => total + x.remaining_hours,0) })))
const maxHours = computed(() => Math.max(1, ...workload.value.map(x => x.hours)))
const validDates = computed(() => schedule.value.flatMap(x => [Date.parse(x.start_date),Date.parse(x.due_date)]).filter(Number.isFinite))
const beginning = computed(() => validDates.value.length ? Math.min(...validDates.value) : Date.now())
const end = computed(() => validDates.value.length ? Math.max(...validDates.value) + 86400000 : beginning.value + 86400000)
const ticks = computed(() => {
  if (!validDates.value.length) return []
  const first = beginning.value, last = end.value - 86400000
  const count = Math.min(5, Math.round((last - first) / 86400000) + 1)
  return Array.from({length:count}, (_, index) => new Date(first + (count === 1 ? 0 : Math.round((last - first) / (count - 1) * index / 86400000) * 86400000)).toISOString().slice(5,10))
})
function range(task) { const start = Date.parse(task.start_date), due = Date.parse(task.due_date); return { marginLeft:`${Math.max(0,(start - beginning.value) / (end.value - beginning.value)*100)}%`, width:`${Math.max(1,(due + 86400000 - start) / (end.value - beginning.value)*100)}%` } }
function dependencyNames(task, tasks) { return (task?.dependencies || []).map(id => tasks.find(x => x.id === id)?.title || `任务 ${id}`).join('、') || '无' }
const detailFields = [
  { key:'title', label:'任务名称' }, { key:'description', label:'任务说明' },
  { key:'requirement_id', label:'关联需求' }, { key:'acceptance', label:'验收条件' },
  { key:'stage_index', label:'检查阶段' }, { key:'artifact_url', label:'成果' }, { key:'blocker', label:'阻碍' },
]
function detailChanges(change) { return detailFields.filter(field => JSON.stringify(change.before?.[field.key]) !== JSON.stringify(change.after?.[field.key])) }
function detailValue(task, key) {
  const value = task?.[key]
  if (value == null || value === '') return '—'
  if (key === 'requirement_id') return s.data.requirements.find(item => item.id === value)?.title || `需求 #${value}`
  if (key === 'stage_index') return s.data.course?.stages?.[value]?.name || `阶段 ${value + 1}`
  return value
}
</script>
<template>
<div class="page-head">
<div>
<h1>计划与排期</h1>
<p>查看真实计划快照，比较每次负责人、日期与依赖调整。</p>
</div>
<button v-if="s.user.identity === 'student'" class="button secondary" @click="s.tab = 'collaboration'"><AppIcon name="checklist" />进入草案核对</button>
</div>
<section class="panel">
<header class="section-head">
<div>
<h2>计划版本比较</h2>
<p class="caption">历史快照保留发布时状态；当前任务进度可能已经变化。</p>
</div>
<span class="pill">{{ s.data.plans.length }} 个版本</span>
</header>
<div class="compare-selectors">
<label>变更前<select v-model="beforeId">
<option value="">初始空计划</option>
<option v-for="plan in s.data.plans" :key="plan.id" :value="plan.id">v{{ plan.version }} · {{ time(plan.created_at) }}</option>
</select>
</label>
<span>→</span>
<label>变更后<select v-model="afterId">
<option value="" disabled>选择版本</option>
<option v-for="plan in s.data.plans" :key="plan.id" :value="plan.id">v{{ plan.version }} · {{ time(plan.created_at) }}</option>
</select>
</label>
</div>
<div v-if="after" class="plan-basis"><AppIcon name="info" /><div><strong>发布依据</strong><p class="pre-line">{{ after.summary }}</p><small>v{{ after.version }} · {{ time(after.created_at) }}</small></div></div>
<div v-if="after" class="table-wrap plan-record-wrap">
<table class="plan-record-table">
<thead>
<tr>
<th>任务与变更</th>
<th>变更前</th>
<th>变更后</th>
</tr>
</thead>
<tbody>
<tr v-for="change in diff" :key="change.id">
<td>
<strong>{{ change.after?.title || change.before?.title }}</strong>
<span :class="['pill', change.kind === 'added' ? 'green' : 'blue']">{{ {added:'新增',removed:'移除',changed:'调整'}[change.kind] }}</span>
</td>
<td>
<span class="mobile-compare-label">变更前</span>
<template v-if="change.before">
<strong>{{ name(change.before.assignee_id) }}</strong>
<small>{{ change.before.start_date }} → {{ change.before.due_date }}</small>
<small>预计 {{ change.before.estimated_hours }}h · 剩余 {{ change.before.remaining_hours }}h</small>
<small>前置：{{ dependencyNames(change.before,before?.tasks || []) }}</small>
<small>{{ statusNames[change.before.status] }} · {{ change.before.progress }}%</small>
<dl v-if="detailChanges(change).length" class="plan-field-changes">
<template v-for="field in detailChanges(change)" :key="field.key">
<dt>{{ field.label }}</dt><dd class="pre-line">{{ detailValue(change.before,field.key) }}</dd>
</template>
</dl>
</template>
<span v-else>—</span>
</td>
<td>
<span class="mobile-compare-label">变更后</span>
<template v-if="change.after">
<strong>{{ name(change.after.assignee_id) }}</strong>
<small>{{ change.after.start_date }} → {{ change.after.due_date }}</small>
<small>预计 {{ change.after.estimated_hours }}h · 剩余 {{ change.after.remaining_hours }}h</small>
<small>前置：{{ dependencyNames(change.after,after.tasks) }}</small>
<small>{{ statusNames[change.after.status] }} · {{ change.after.progress }}%</small>
<dl v-if="detailChanges(change).length" class="plan-field-changes">
<template v-for="field in detailChanges(change)" :key="field.key">
<dt>{{ field.label }}</dt><dd class="pre-line">{{ detailValue(change.after,field.key) }}</dd>
</template>
</dl>
</template>
<span v-else>—</span>
</td>
</tr>
</tbody>
</table>
<p v-if="!diff.length" class="empty">两个快照没有任务字段变化</p>
</div>
<p v-else class="empty">暂无已发布计划，可由组长创建人工任务或发布核对后的草案。</p>
</section>
<section class="panel">
<header class="section-head">
<h2>任务时间安排</h2>
<span class="caption">{{ after ? `历史计划 v${after.version}` : '当前任务安排' }}</span>
</header>
<div v-if="schedule.length" class="timeline">
<header>
<span>任务与负责人</span>
<div>
<span>{{ new Date(beginning).toISOString().slice(0,10) }}</span>
<span>{{ new Date(end - 86400000).toISOString().slice(0,10) }}</span>
</div>
</header>
<div v-if="ticks.length > 1" class="timeline-ticks" aria-hidden="true"><span></span><div><span v-for="(tick,index) in ticks" :key="index">{{ tick }}</span></div></div>
<div v-for="task in schedule" :key="task.id" class="timeline-row">
<div>
<strong>{{ task.title }}</strong>
<small>{{ name(task.assignee_id) }} · {{ task.start_date }}—{{ task.due_date }}</small>
</div>
<div class="timeline-track">
<span :class="['timeline-bar',task.status]" :style="range(task)">{{ task.remaining_hours }}h</span>
</div>
</div>
</div>
<p v-else class="empty">暂无任务排期</p>
<details v-if="schedule.length">
<summary>任务依赖与阶段安排</summary>
<div class="table-wrap plan-record-wrap">
<table class="plan-record-table">
<thead>
<tr>
<th>任务</th>
<th>前置依赖</th>
<th>对应检查阶段</th>
</tr>
</thead>
<tbody>
<tr v-for="task in schedule" :key="task.id">
<td>{{ task.title }}</td>
<td><span class="mobile-compare-label">前置依赖</span>{{ dependencyNames(task,schedule) }}</td>
<td><span class="mobile-compare-label">对应检查阶段</span>{{ s.data.course?.stages?.[task.stage_index]?.name || `阶段 ${task.stage_index + 1}` }}</td>
</tr>
</tbody>
</table>
</div>
</details>
</section>
<div class="plan-summary-grid">
<section class="panel">
<h2>成员当前剩余工作量</h2>
<p class="caption">柱长表示本项目所有未完成任务的剩余工时总和。每周容量由本人填写，规划检查按工作日期分摊到各周；这些数据不用于贡献评分。</p>
<div v-for="member in workload" :key="member.user_id" class="workload-row">
<span>{{ member.name }}</span>
<div class="workload-track">
<i :style="{width:`${member.hours/maxHours*100}%`}">
</i>
</div>
<strong>{{ member.hours }}h</strong>
<small>容量 {{ member.weekly_hours }}h/周</small>
</div>
</section>
<section class="panel">
<h2>当前规划约束</h2>
<p class="caption">依据当前课程日期、需求覆盖、任务依赖与成员每周容量检查。历史快照保留发布时状态。</p>
<Checks :checks="s.data.progress?.planning_checks" />
<p v-if="!s.data.progress?.planning_checks" class="empty">暂未取得规划检查结果</p>
<div class="plan-stage-list"><div v-for="(stage,index) in s.data.course?.stages" :key="index"><AppIcon name="stages" :size="17" /><strong>{{ stage.name }}</strong><span>{{ stage.deadline }}</span></div></div>
</section>
</div>
<section class="panel">
<h3>计划发布历史</h3>
<div v-for="plan in [...s.data.plans].reverse()" :key="plan.id" class="file-row">
<span>
<strong>v{{ plan.version }} · {{ plan.summary }}</strong>
<small>{{ time(plan.created_at) }} · {{ plan.tasks.length }} 项任务</small>
</span>
<button class="link-button" @click="afterId = plan.id">查看快照</button>
</div>
<p v-if="!s.data.plans.length" class="empty">暂无发布历史</p>
</section>
</template>
<style scoped>
.plan-basis { display:flex; align-items:flex-start; gap:12px; background:var(--selected); border:1px solid var(--border); border-radius:8px; padding:14px 16px; margin-bottom:20px; }
.plan-basis .app-icon { color:var(--teal); flex-shrink:0; margin-top:3px; }
.plan-basis p { margin:3px 0 6px; }
.plan-basis small { color:var(--muted); }
.plan-summary-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:24px; }
.plan-summary-grid>section { min-width:0; }
.plan-stage-list { display:grid; gap:12px; margin-top:16px; }
.plan-stage-list>div { display:flex; align-items:center; flex-wrap:wrap; gap:8px; border-top:1px solid var(--border); padding-top:12px; }
.plan-stage-list span { margin-left:auto; color:var(--muted); font-variant-numeric:tabular-nums; }
.timeline-ticks { display:grid; grid-template-columns:230px minmax(300px,1fr); min-width:580px; margin:10px 0; color:var(--muted); font-size:13px; }
.timeline-ticks>div { display:flex; justify-content:space-between; gap:8px; padding:0 12px; }
.mobile-compare-label { display:none; }
.plan-field-changes { margin:12px 0 0; }
.plan-field-changes dt { color:var(--muted); margin-top:12px; }
.plan-field-changes dd { margin:4px 0 0; overflow-wrap:anywhere; }
@media(max-width:1100px) { .plan-summary-grid { grid-template-columns:minmax(0,1fr); gap:0; } }
@media(max-width:767px) {
  .plan-record-wrap { overflow:visible; }
  .plan-record-table { display:block; min-width:0; width:100%; }
  .plan-record-table thead { display:none; }
  .plan-record-table tbody { display:block; }
  .plan-record-table tr { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; padding:16px 0; border-bottom:1px solid var(--border); }
  .plan-record-table td { display:block; min-width:0; padding:0; border:0; overflow-wrap:anywhere; }
  .plan-record-table td:first-child { grid-column:1 / -1; background:var(--wash); border-radius:8px; padding:12px; }
  .mobile-compare-label { display:block; color:var(--muted); font-size:13px; margin-bottom:8px; }
  .timeline { overflow:visible; }
  .timeline>header,.timeline-ticks { display:none; }
  .timeline-row { display:block; min-width:0; }
  .timeline-row>div:first-child { margin-bottom:12px; overflow-wrap:anywhere; }
  .plan-stage-list span { margin-left:0; width:100%; padding-left:25px; }
}
</style>
