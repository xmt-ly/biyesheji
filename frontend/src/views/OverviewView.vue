<script setup>
import { inject, computed, ref } from 'vue'
import Checks from '../components/Checks.vue'
import { statusNames } from '../state.js'
const ws = inject('workspace'), s = ws.s
const mine = computed(() => s.data.tasks.filter(x => x.assignee_id === s.user.id))
const blocked = computed(() => s.data.tasks.filter(x => x.blocker || x.planning_risks?.length))
const edit = ref(false), busy = ref(false), error = ref(''), form = ref({})
function open() { form.value = { name: s.data.project.name, description: s.data.project.description, status: s.data.project.status }; edit.value = true }
async function save() { busy.value = true; error.value = ''; try { await ws.mutate(`/projects/${s.selectedId}`, form.value, 'PATCH'); await ws.loadBasics(); edit.value = false } catch (e) { error.value = e.message } finally { busy.value = false } }
</script>
<template>
<template v-if="s.data.project">
<div class="page-head">
<div>
<span class="eyebrow">项目概览 · {{ statusNames[s.data.project.status] }}</span>
<h1>{{ s.data.project.name }}</h1>
<p>{{ s.data.project.description }}</p>
</div>
<button v-if="s.data.project.role === 'leader'" class="button secondary" @click="open">维护项目信息</button>
</div>
<section class="stat-grid">
<article class="stat">
<small>任务完成比例</small>
<strong>{{ s.data.progress?.completion_percent || 0 }}<em>%</em>
</strong>
<span>按已完成任务数量计算</span>
</article>
<article class="stat">
<small>已完成 / 全部任务</small>
<strong>{{ s.data.progress?.done || 0 }}<em>/ {{ s.data.progress?.total || 0 }}</em>
</strong>
<span>不代表课程验收结果</span>
</article>
<article class="stat">
<small>计划版本</small>
<strong>{{ s.data.plans.at(-1)?.version || 0 }}</strong>
<span>保留每次发布的完整快照</span>
</article>
<article class="stat">
<small>团队成员</small>
<strong>{{ s.data.project.members.length }}</strong>
<span>按本人填写的容量协调</span>
</article>
</section>
<Checks :checks="s.data.progress?.planning_checks" />
<div class="two-column">
<section class="panel">
<header class="section-head">
<h3>{{ s.user.identity === 'student' ? '我的任务' : '任务进度' }}</h3>
<button class="link-button" @click="s.tab = 'tasks'">任务看板 →</button>
</header>
<div v-for="task in (s.user.identity === 'student' ? mine : s.data.tasks)" :key="task.id" class="task-summary">
<div>
<strong>{{ task.title }}</strong>
<small>{{ task.due_date }} 截止 · 剩余 {{ task.remaining_hours }}h</small>
</div>
<span class="pill">{{ statusNames[task.status] }}</span>
<div class="progress-track">
<i :style="{ width: `${task.progress}%` }">
</i>
</div>
</div>
<p v-if="!(s.user.identity === 'student' ? mine : s.data.tasks).length" class="empty">暂无任务记录</p>
</section>
<section class="panel">
<h3>阶段检查安排</h3>
<div v-for="(stage, index) in s.data.course?.stages" :key="index" class="stage-overview">
<span class="step-number">0{{ index + 1 }}</span>
<div>
<strong>{{ stage.name }}</strong>
<small>{{ stage.deadline }} 截止</small>
<p>{{ stage.deliverables.join('、') }}</p>
</div>
</div>
<button class="link-button" @click="s.tab = 'stages'">查看成果与检查意见 →</button>
</section>
</div>
<section v-if="blocked.length" class="panel">
<h3>当前阻碍与风险</h3>
<div v-for="task in blocked" :key="task.id" class="file-row">
<span>
<strong>{{ task.title }}</strong>
<small>{{ task.blocker || '规划存在风险，请查看实时约束检查' }}</small>
</span>
<button class="link-button" @click="s.tab = 'tasks'">查看任务</button>
</div>
</section>
<section v-if="edit" class="panel">
<h3>维护项目</h3>
<form @submit.prevent="save">
<div class="form-grid">
<label>项目名称<input v-model="form.name" required>
</label>
<label>项目状态<select v-model="form.status">
<option value="preparing">筹备中</option>
<option value="active">进行中</option>
<option value="archived">已归档</option>
</select>
</label>
</div>
<label>项目说明<textarea v-model="form.description" rows="3">
</textarea>
</label>
<p v-if="error" class="error">{{ error }}</p>
<div class="form-actions">
<button class="button secondary" type="button" @click="edit = false">取消</button>
<button class="button" :disabled="busy">保存项目信息</button>
</div>
</form>
</section>
</template>
<div v-else class="panel empty">{{ s.loading ? '正在加载项目…' : '请从工作台选择一个项目' }}</div>
</template>
