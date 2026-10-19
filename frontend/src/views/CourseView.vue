<script setup>
import { computed, inject, ref } from 'vue'
import { lines, statusNames, time } from '../state.js'
import SafeLink from '../components/SafeLink.vue'
const ws = inject('workspace'), s = ws.s
const teacher = computed(() => s.user.identity === 'teacher')
const selected = ref(s.data.course?.id || s.courses[0]?.id || '')
const course = computed(() => s.courses.find(x => x.id === Number(selected.value)) || s.data.course)
const edit = ref(false), busy = ref(false), error = ref(''), draft = ref({}), editingId = ref(null), publishedBefore = ref(false)
const stages = ['需求与计划检查', '开发中期检查', '最终验收']
function start(value) {
  editingId.value = value?.id || null
  publishedBefore.value = value?.status === 'published' || value?.history?.some(x => x.snapshot?.status === 'published') || false
  draft.value = { title: value?.title || '', description: value?.description || '', acceptance_criteria: value?.acceptance_criteria || '', required_features: value?.required_features?.join('\n') || '', optional_features: value?.optional_features?.join('\n') || '', references: value?.references?.join('\n') || '', status: value?.status || 'draft', stages: stages.map((name, index) => ({ name: value?.stages?.[index]?.name || name, deadline: value?.stages?.[index]?.deadline || '', deliverables: value?.stages?.[index]?.deliverables?.join('\n') || '' })) }
  edit.value = true; error.value = ''
}
async function save(status) {
  busy.value = true; error.value = ''
  const data = { ...draft.value, status, required_features: lines(draft.value.required_features), optional_features: lines(draft.value.optional_features), references: lines(draft.value.references), stages: draft.value.stages.some(x => x.deadline || x.deliverables) ? draft.value.stages.map(x => ({ ...x, deliverables: lines(x.deliverables) })) : [] }
  try { const result = await ws.mutate(editingId.value ? `/courses/${editingId.value}` : '/courses', data, editingId.value ? 'PATCH' : 'POST'); await ws.loadBasics(); selected.value = result.id; edit.value = false }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
<div class="page-head">
<div>
<span class="eyebrow">课程要求与检查标准</span>
<h1>{{ teacher ? '我的课程任务' : '课程任务' }}</h1>
<p>项目需求和成果验收的共同依据。</p>
</div>
<button v-if="teacher" class="button" @click="start(null)">＋ 新建课程任务</button>
</div>
<label class="inline-field">选择课程<select v-model="selected">
<option v-for="item in s.courses" :key="item.id" :value="item.id">{{ item.title }} · {{ statusNames[item.status] }}</option>
</select>
</label>
<template v-if="course && !edit">
<section class="panel">
<header class="section-head">
<div>
<span class="pill">{{ statusNames[course.status] }} · v{{ course.version }}</span>
<h2>{{ course.title }}</h2>
</div>
<button v-if="teacher" class="button secondary" @click="start(course)">编辑课程</button>
</header>
<p class="pre-line">{{ course.description }}</p>
<div class="acceptance">
<strong>课程验收标准</strong>
<p class="pre-line">{{ course.acceptance_criteria || '草稿尚未填写' }}</p>
</div>
<div class="two-column">
<div>
<h3>必做功能</h3>
<ul>
<li v-for="feature in course.required_features" :key="feature">{{ feature }}</li>
</ul>
</div>
<div>
<h3>选做功能</h3>
<ul>
<li v-for="feature in course.optional_features" :key="feature">{{ feature }}</li>
</ul>
<p v-if="!course.optional_features?.length" class="muted">未设置选做功能</p>
</div>
</div>
<h3 v-if="course.references?.length">参考资料</h3>
<ul>
<li v-for="reference in course.references" :key="reference">
<SafeLink :value="reference" />
</li>
</ul>
</section>
<div class="stage-grid">
<article v-for="(stage, index) in course.stages" :key="index" class="panel">
<span class="eyebrow">阶段 0{{ index + 1 }}</span>
<h3>{{ stage.name }}</h3>
<p class="date-label">{{ stage.deadline }}</p>
<ul>
<li v-for="deliverable in stage.deliverables" :key="deliverable">{{ deliverable }}</li>
</ul>
</article>
</div>
<section class="panel">
<h3>课程版本历史</h3>
<p class="caption">已发布要求变化会让团队重新核对未发布计划。</p>
<details v-for="(history, index) in course.history" :key="index">
<summary>v{{ history.version || index + 1 }} · {{ history.title || history.snapshot?.title || '课程快照' }} <span class="muted">{{ history.updated_at ? time(history.updated_at) : '' }}</span>
</summary>
<p class="pre-line">{{ history.description || history.snapshot?.description }}</p>
<p>验收：{{ history.acceptance_criteria || history.snapshot?.acceptance_criteria }}</p>
<p>必做：{{ (history.required_features || history.snapshot?.required_features || []).join('、') }}</p>
<div v-for="(stage, i) in (history.stages || history.snapshot?.stages || [])" :key="i">{{ stage.name }} · {{ stage.deadline }} · {{ stage.deliverables.join('、') }}</div>
</details>
<p v-if="!course.history?.length" class="empty">暂无旧版本</p>
</section>
</template>
<section v-if="edit" class="panel course-editor">
<h2>{{ editingId ? '编辑课程任务' : '新建课程任务' }}</h2>
<form @submit.prevent="save(draft.status)">
<label>课程名称<input v-model="draft.title" required maxlength="200">
</label>
<label>背景与项目说明<textarea v-model="draft.description" rows="3">
</textarea>
</label>
<label>课程验收标准<textarea v-model="draft.acceptance_criteria" rows="3" placeholder="发布时必填：说明功能、权限、测试和交付验收条件">
</textarea>
</label>
<div class="form-grid">
<label>必做功能，每行一项<textarea v-model="draft.required_features" rows="4">
</textarea>
</label>
<label>选做功能，每行一项<textarea v-model="draft.optional_features" rows="4">
</textarea>
</label>
</div>
<label>参考链接，每行一项<textarea v-model="draft.references" rows="2" placeholder="https://...">
</textarea>
</label>
<div class="stage-grid">
<fieldset v-for="(stage, index) in draft.stages" :key="index">
<legend>阶段 {{ index + 1 }}</legend>
<label>阶段名称<input v-model="stage.name">
</label>
<label>截止日期<input v-model="stage.deadline" type="date">
</label>
<label>交付物，每行一项<textarea v-model="stage.deliverables" rows="3">
</textarea>
</label>
</fieldset>
</div>
<label>保存状态<select v-model="draft.status">
<option value="draft" :disabled="publishedBefore">草稿</option>
<option value="published">发布</option>
<option value="archived">归档</option>
</select>
</label>
<p v-if="publishedBefore" class="caption">已发布课程可继续修改或归档，不能退回草稿。保存失败时会保留当前输入。</p>
<p class="caption">发布必须包含项目说明、验收标准、必做功能、三个阶段和交付物；三个截止日期须依次递增。</p>
<p v-if="error" class="error" role="alert">{{ error }}</p>
<div class="form-actions">
<button type="button" class="button secondary" @click="edit = false">取消</button>
<button v-if="!publishedBefore" type="button" class="button secondary" :disabled="busy" @click="save('draft')">保存草稿</button>
<button class="button" :disabled="busy">{{ busy ? '保存中…' : draft.status === 'published' ? '保存并发布' : '保存课程' }}</button>
</div>
</form>
</section>
<div v-if="!course && !edit" class="panel empty">暂无可访问课程</div>
</template>
