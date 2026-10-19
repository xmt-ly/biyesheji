<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import Modal from './Modal.vue'
import TaskFields from './TaskFields.vue'
import SafeLink from './SafeLink.vue'
import { canEditTask, time, safeUrl, statusNames, buildTaskPayload } from '../state.js'
const props = defineProps({ task: Object })
const emit = defineEmits(['close'])
const ws = inject('workspace'), s = ws.s, busy = ref(false), error = ref(''), comments = ref([]), comment = ref(''), kind = ref('comment'), commentLoading = ref(false)
const leader = computed(() => s.data.project?.role === 'leader')
const editable = computed(() => !props.task || canEditTask(s.user, s.data.project?.role, props.task))
// 保存对比打开表单时的快照，避免团队刷新把未编辑的旧值误判为修改。
const original = props.task ? { ...props.task, dependencies: [...props.task.dependencies] } : null
const form = ref(original ? { ...original, dependencies: [...original.dependencies] } : { title:'',description:'',requirement_id:0,acceptance:'',assignee_id:0,estimated_hours:0,remaining_hours:0,dependencies:[],start_date:'',due_date:'',stage_index:2,status:'todo',progress:0,artifact_url:'',blocker:'' })
const correction = ref('')
async function loadComments() {
  if (!props.task || s.user.identity !== 'student') return
  commentLoading.value = true
  try { comments.value = await ws.api.request(`/tasks/${props.task.id}/comments`) } catch (e) { error.value = e.message } finally { commentLoading.value = false }
}
async function save() {
  if (form.value.artifact_url && !safeUrl(form.value.artifact_url)) { error.value = '成果链接仅支持 http、https 或合法项目附件'; return }
  busy.value = true; error.value = ''
  const data = buildTaskPayload(form.value, original, s.data.project.role, correction.value)
  if (leader.value && props.task?.status === 'done') data.correction_reason = correction.value
  try { await ws.mutate(props.task ? `/tasks/${props.task.id}` : `/projects/${s.selectedId}/tasks`, data, props.task ? 'PATCH' : 'POST'); emit('close') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
async function postComment() {
  busy.value = true; error.value = ''
  try { await ws.mutate(`/tasks/${props.task.id}/comments`, { kind: kind.value, content: comment.value }, 'POST', { refresh: false }); comment.value = ''; await loadComments() } catch(e) { error.value = e.message } finally { busy.value = false }
}
async function upload(event) {
  const file = event.target.files?.[0]; if (!file) return
  busy.value = true; error.value = ''
  try { const result = await ws.upload(file); form.value.artifact_url = `/api/files/${result.id}` } catch(e) { error.value = e.message } finally { busy.value = false; event.target.value = '' }
}
onMounted(() => { if (s.user.identity === 'teacher' && !s.data.requirements.length) ws.loadRequirements(); else loadComments() })
</script>
<template>
<Modal :title="task ? task.title : '创建人工任务'" variant="drawer" @close="emit('close')">
<div class="task-detail-grid">
<section>
<div v-if="task" class="task-context">
<span class="pill">{{ statusNames[task.status] }}</span>
<p class="pre-line">{{ task.description }}</p>
<dl class="detail-list">
<dt>关联需求</dt>
<dd>{{ s.data.requirements.find(x => x.id === task.requirement_id)?.title || `需求 #${task.requirement_id}` }}</dd>
<dt>负责人</dt>
<dd>{{ s.data.project.members.find(x => x.user_id === task.assignee_id)?.name }}</dd>
<dt>排期</dt>
<dd>{{ task.start_date }} → {{ task.due_date }}</dd>
<dt>检查阶段</dt>
<dd>{{ s.data.course?.stages?.[task.stage_index]?.name || `阶段 ${task.stage_index + 1}` }}</dd>
<dt>工时</dt>
<dd>预计 {{ task.estimated_hours }}h · 剩余 {{ task.remaining_hours }}h</dd>
<dt>验收条件</dt>
<dd>{{ task.acceptance }}</dd>
<dt>进度</dt>
<dd>{{ task.progress }}%</dd>
<dt>前置依赖</dt>
<dd>{{ task.dependencies.map(id => s.data.tasks.find(x => x.id === id)?.title || `任务 ${id}`).join('、') || '无' }}</dd>
<dt>阻碍</dt>
<dd>{{ task.blocker || '暂无' }}</dd>
<dt>成果</dt>
<dd><SafeLink :value="task.artifact_url" /></dd>
</dl>
</div>
<form v-if="editable" @submit.prevent="save">
<TaskFields :form="form" :planning="leader" />
<label v-if="task?.status === 'done'">已完成任务纠正原因<textarea v-model="correction" required rows="2" placeholder="请记录纠正内容和原因">
</textarea>
</label>
<label class="button secondary upload-button" v-if="s.user.identity === 'student'">上传并关联任务成果<input type="file" :disabled="busy" @change="upload" aria-label="上传任务成果附件">
</label>
<p class="caption">完成状态会将进度归一化为 100%，剩余工时为 0。进度保存后仍会展示当前规划风险。</p>
<p v-if="error" class="error" role="alert">{{ error }}</p>
<div class="form-actions">
<button type="button" class="button secondary" @click="emit('close')">关闭</button>
<button class="button" :disabled="busy">{{ busy ? '保存中…' : '保存任务' }}</button>
</div>
</form>
<div v-if="task?.planning_risks?.length" class="checks checks-warning">
<strong>当前任务风险</strong>
<ul>
<li v-for="(risk, i) in task.planning_risks" :key="i">{{ risk.message }}</li>
</ul>
</div>
</section>
<section v-if="task && s.user.identity === 'student'" class="comment-panel">
<h3>任务协作记录</h3>
<p v-if="commentLoading" class="caption">正在读取评论…</p>
<article v-for="item in comments" :key="item.id" class="comment">
<header>
<strong>{{ item.author_name }}</strong>
<span class="pill">{{ { comment:'评论', blocker:'阻碍', artifact:'成果' }[item.kind] }}</span>
</header>
<p class="pre-line">{{ item.content }}</p>
<small>{{ time(item.created_at) }}</small>
</article>
<p v-if="!comments.length && !commentLoading" class="empty">暂无评论</p>
<form @submit.prevent="postComment">
<label>记录类型<select v-model="kind">
<option value="comment">评论</option>
<option value="blocker">阻碍</option>
<option value="artifact">成果</option>
</select>
</label>
<label>协作记录<textarea v-model="comment" required rows="3">
</textarea>
</label>
<p class="caption">评论记录不会替代任务的成果或阻碍字段，请同时保存相应任务信息。</p>
<button class="button secondary" :disabled="busy">发送记录</button>
<p v-if="error && !editable" class="error">{{ error }}</p>
</form>
</section>
</div>
</Modal>
</template>
