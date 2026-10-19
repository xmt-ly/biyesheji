<script setup>
import { inject, computed, ref } from 'vue'
import Modal from '../components/Modal.vue'
import { statusNames } from '../state.js'
const ws = inject('workspace'), s = ws.s, edit = ref(false), editingId = ref(null), busy = ref(false), error = ref(''), form = ref({})
const student = computed(() => s.user.identity === 'student'), leader = computed(() => s.data.project?.role === 'leader')
const features = computed(() => [...(s.data.course?.required_features || []), ...(s.data.course?.optional_features || [])])
function start(requirement) { editingId.value = requirement?.id || null; form.value = { title: requirement?.title || '', description: requirement?.description || '', acceptance: requirement?.acceptance || '', course_feature: requirement?.course_feature || '', priority: requirement?.priority || 'must', status: requirement?.status || 'draft' }; error.value = ''; edit.value = true }
function canEdit(item) { return leader.value || (student.value && item.creator_id === s.user.id && item.status === 'draft') }
async function save() {
  busy.value = true; error.value = ''
  try { await ws.mutate(editingId.value ? `/requirements/${editingId.value}` : `/projects/${s.selectedId}/requirements`, form.value, editingId.value ? 'PATCH' : 'POST'); edit.value = false }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
async function confirm(item) { busy.value = true; error.value = ''; try { await ws.mutate(`/requirements/${item.id}`, { status: 'confirmed' }, 'PATCH') } catch(e) { error.value = e.message } finally { busy.value = false } }
</script>
<template>
<div class="page-head">
<div>
<span class="eyebrow">从课程要求到团队需求</span>
<h1>需求清单</h1>
<p>{{ student ? '每位成员都可以提出建议，由组长整理并确认。' : '查看团队已确认需求及其课程功能关联。' }}</p>
</div>
<button v-if="student" class="button" @click="start(null)">＋ 提出需求</button>
</div>
<div class="feature-coverage">
<span v-for="feature in s.data.course?.required_features" :key="feature" :class="['tag', { covered: s.data.requirements.some(x => x.status === 'confirmed' && (x.course_feature === feature || (!x.course_feature && x.title === feature))) }]">{{ s.data.requirements.some(x => x.status === 'confirmed' && (x.course_feature === feature || (!x.course_feature && x.title === feature))) ? '✓' : '○' }} {{ feature }}</span>
</div>
<p v-if="error && !edit" class="banner danger">{{ error }}</p>
<section v-for="item in s.data.requirements" :key="item.id" class="panel requirement-card">
<header class="section-head">
<div>
<span class="eyebrow">REQ-{{ String(item.id).padStart(3, '0') }}</span>
<h3>{{ item.title }}</h3>
</div>
<div class="row-actions">
<span class="pill">{{ {must:'必做',should:'应做',could:'可选'}[item.priority] }}</span>
<span :class="['pill', item.status === 'confirmed' ? 'green' : 'amber']">{{ statusNames[item.status] }}</span>
<button v-if="canEdit(item)" class="button secondary small" @click="start(item)">编辑</button>
<button v-if="leader && item.status === 'draft'" class="button small" :disabled="busy" @click="confirm(item)">确认需求</button>
</div>
</header>
<p class="pre-line">{{ item.description }}</p>
<div class="acceptance">
<strong>验收条件</strong>
<p>{{ item.acceptance }}</p>
</div>
<footer class="caption">关联课程功能：{{ item.course_feature || '未显式关联' }} · 关联任务 {{ s.data.tasks.filter(x => x.requirement_id === item.id).length }} 项</footer>
</section>
<div v-if="!s.data.requirements.length" class="panel empty">暂无{{ student ? '' : '已确认' }}需求，学生可提出课程功能细化建议。</div>
<Modal v-if="edit" :title="editingId ? '编辑需求' : '提出需求建议'" @close="edit = false">
<form @submit.prevent="save">
<label>需求名称<input v-model="form.title" required>
</label>
<label>需求说明<textarea v-model="form.description" rows="3" required>
</textarea>
</label>
<label>验收条件<textarea v-model="form.acceptance" rows="3" required>
</textarea>
</label>
<div class="form-grid">
<label>课程功能关联<select v-model="form.course_feature">
<option value="">未显式关联</option>
<option v-for="feature in features" :key="feature" :value="feature">{{ feature }}</option>
</select>
</label>
<label>优先级<select v-model="form.priority">
<option value="must">必做</option>
<option value="should">应做</option>
<option value="could">可选</option>
</select>
</label>
</div>
<label v-if="leader">确认状态<select v-model="form.status">
<option value="draft">待讨论草稿</option>
<option value="confirmed">已确认</option>
</select>
</label>
<p v-if="error" class="error" role="alert">{{ error }}</p>
<div class="form-actions">
<button class="button secondary" type="button" @click="edit = false">取消</button>
<button class="button" :disabled="busy">{{ busy ? '保存中…' : '保存需求' }}</button>
</div>
</form>
</Modal>
</template>
