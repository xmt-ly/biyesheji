<script setup>
import { inject, computed, ref, onMounted } from 'vue'
import TaskDetails from '../components/TaskDetails.vue'
import Checks from '../components/Checks.vue'
import AppIcon from '../components/AppIcon.vue'
const ws = inject('workspace'), s = ws.s, selected = ref(null), opened = ref(false), onlyMine = ref(false), search = ref('')
const mobileStatus = ref('all')
const tasks = computed(() => s.data.tasks.filter(x => (!onlyMine.value || x.assignee_id === s.user.id) && (!search.value || x.title.includes(search.value))))
const columns = [{ id:'todo',name:'待开始',hint:'已确认，等待执行' }, { id:'doing',name:'进行中',hint:'跟进实际进度与阻碍' }, { id:'done',name:'已完成',hint:'保留成果和验收记录' }]
function open(task) { selected.value = task; opened.value = true }
const name = id => s.data.project?.members.find(x => x.user_id === id)?.name || '未分配'
const requirement = id => s.data.requirements.find(x => x.id === id)?.title || `需求 #${id}`
const avatar = id => name(id).match(/成员([甲乙])$/)?.[1] || (name(id).includes('组长') ? '长' : name(id).slice(0,1))
onMounted(() => { if (s.user.identity === 'teacher' && !s.data.requirements.length) ws.loadRequirements() })
</script>
<template>
<div class="page-head">
<div>
<h1>任务看板</h1>
<p>进度由本人更新，分工和排期由组长协调。</p>
</div>
<button v-if="s.data.project?.role === 'leader'" class="button" @click="open(null)"><AppIcon name="plus" />创建任务</button>
</div>
<div class="toolbar">
<label class="search-field">搜索任务<input v-model="search" placeholder="输入任务名称">
</label>
<label v-if="s.user.identity === 'student'" class="checkbox-label">
<input v-model="onlyMine" type="checkbox">只看本人任务</label>
<span class="muted">{{ tasks.length }} 项任务</span>
</div>
<Checks :checks="s.data.progress?.planning_checks" compact />
<nav class="task-state-filters" aria-label="按任务状态筛选">
<button :class="{active:mobileStatus === 'all'}" :aria-pressed="mobileStatus === 'all'" @click="mobileStatus = 'all'">全部<span>{{ tasks.length }}</span></button>
<button v-for="column in columns" :key="column.id" :class="{active:mobileStatus === column.id}" :aria-pressed="mobileStatus === column.id" @click="mobileStatus = column.id">{{ column.name }}<span>{{ tasks.filter(task => task.status === column.id).length }}</span></button>
</nav>
<div class="kanban">
<section v-for="column in columns" :key="column.id" :class="['kanban-column', column.id, { 'phone-hidden':mobileStatus !== 'all' && mobileStatus !== column.id }]">
<header>
<div>
<span class="status-dot">
</span>
<h3>{{ column.name }}</h3>
<span class="column-count">{{ tasks.filter(x => x.status === column.id).length }}</span>
</div>
<p>{{ column.hint }}</p>
</header>
<button v-for="task in tasks.filter(x => x.status === column.id)" :key="task.id" class="task-card" @click="open(task)">
<div class="task-card-top">
<span>TASK-{{ String(task.id).padStart(3,'0') }}</span>
<span v-if="task.blocker || task.planning_risks?.length" class="pill amber">{{ task.blocker ? '有阻碍' : '规划风险' }}</span>
</div>
<h3>{{ task.title }}</h3>
<p>{{ task.description }}</p>
<span class="task-requirement"><AppIcon name="link" :size="15" />{{ requirement(task.requirement_id) }}</span>
<div class="task-meta">
<span>{{ task.due_date }}</span>
<span>{{ task.remaining_hours }}h 剩余</span>
</div>
<div class="progress-track">
<i :style="{ width: `${task.progress}%` }">
</i>
</div>
<footer>
<span class="mini-avatar">{{ avatar(task.assignee_id) }}</span>
<span>{{ name(task.assignee_id) }}</span>
<span v-if="s.user.identity === 'student' && task.assignee_id === s.user.id" class="own-task-label">本人</span>
<strong>{{ task.progress }}%</strong>
</footer>
</button>
<p v-if="!tasks.some(x => x.status === column.id)" class="column-empty">暂无{{ column.name }}任务</p>
</section>
</div>
<TaskDetails v-if="opened" :task="selected" @close="opened = false" />
</template>
<style scoped>
.task-requirement { display:flex; align-items:flex-start; gap:6px; color:var(--teal); font-size:13px; padding:7px 0 10px; overflow-wrap:anywhere; }
.task-requirement .app-icon { flex-shrink:0; margin-top:3px; }
.own-task-label { color:var(--teal); font-size:12px; }
.task-state-filters { display:none; }
@media(max-width:767px) {
  .task-state-filters { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-bottom:16px; }
  .task-state-filters button { display:flex; flex-direction:column; align-items:center; justify-content:center; min-width:0; min-height:44px; border:1px solid var(--border); border-radius:8px; background:var(--surface); color:var(--muted); padding:6px; font-size:14px; }
  .task-state-filters button.active { background:var(--selected); border-color:var(--teal); color:var(--teal); }
  .task-state-filters button span { font-size:12px; }
  .kanban-column.phone-hidden { display:none; }
}
</style>
