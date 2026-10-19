<script setup>
import { computed, inject, ref } from 'vue'
import Modal from './Modal.vue'
import TaskFields from './TaskFields.vue'
import { lines, safeUrl } from '../state.js'
const props = defineProps({ card: Object })
const emit = defineEmits(['close'])
const ws = inject('workspace'), s = ws.s, error = ref(''), busy = ref(false), selectedTask = ref(''), reason = ref('')
const taskFields = ['key','existing_id','title','description','requirement_id','acceptance','assignee_id','estimated_hours','remaining_hours','dependencies','start_date','due_date','stage_index','status','progress','artifact_url','blocker']
const draft = ref({ kind: props.card?.kind || 'plan', title: props.card?.title || '人工排期草案', summary: props.card?.summary || '', questions: (props.card?.questions || []).join('\n'), source_message_ids: [...(props.card?.source_message_ids || [])], tasks: structuredClone(props.card ? JSON.parse(JSON.stringify(props.card.tasks || [])) : []) })
const available = computed(() => s.data.tasks.filter(x => x.status !== 'done' && !draft.value.tasks.some(t => t.existing_id === x.id)))
const choices = computed(() => [...s.data.tasks.filter(x => !draft.value.tasks.some(t => t.existing_id === x.id)).map(x => ({ ...x, key: `task_${x.id}` })), ...draft.value.tasks])
const needsReason = computed(() => props.card && (['stale','failed'].includes(props.card.status) || props.card.base_revision !== s.data.project.revision))
function newTask() { draft.value.tasks.push({ key:`new_${crypto.randomUUID().replaceAll('-','')}`,existing_id:null,title:'',description:'',requirement_id:0,acceptance:'',assignee_id:0,estimated_hours:0,remaining_hours:0,dependencies:[],start_date:'',due_date:'',stage_index:2,status:'todo',progress:0,artifact_url:'',blocker:'' }) }
function addExisting() {
  const task = s.data.tasks.find(x => x.id === Number(selectedTask.value)); if (!task) return
  draft.value.tasks.push(Object.fromEntries(taskFields.map(key => [key, key === 'existing_id' ? task.id : key === 'key' ? `task_${task.id}` : key === 'dependencies' ? task.dependencies.map(id => `task_${id}`) : task[key]])))
  selectedTask.value = ''
}
async function save() {
  if (draft.value.tasks.some(x => x.artifact_url && !safeUrl(x.artifact_url))) { error.value = '任务成果链接格式无效'; return }
  busy.value = true; error.value = ''
  const data = { title:draft.value.title, summary:draft.value.summary, questions:lines(draft.value.questions), tasks:draft.value.tasks.map(task => Object.fromEntries(taskFields.map(key => [key, task[key]]))) }
  if (props.card && (needsReason.value || reason.value)) data.reason = reason.value
  if (!props.card) { data.kind = draft.value.kind; data.source_message_ids = draft.value.source_message_ids }
  try { await ws.mutate(props.card ? `/cards/${props.card.id}` : `/projects/${s.selectedId}/cards`, data, props.card ? 'PATCH' : 'POST'); emit('close') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
<Modal :title="card ? '编辑并重新检查草案' : '创建人工草案'" @close="emit('close')">
<form @submit.prevent="save">
<p class="banner info">{{ card?.creator_id ? '这是一份人工草案。' : !card ? '人工草案由团队填写，不代表模型分析结果。' : '编辑后服务端重新校验规划，并撤销旧反馈的确认标记。' }} 草案是任务变更列表，未列出的现有任务会保留。</p>
<label>草案标题<input v-model="draft.title" required>
</label>
<label>草案说明<textarea v-model="draft.summary" required rows="3">
</textarea>
</label>
<label v-if="!card">草案类型<select v-model="draft.kind">
<option value="plan">初始计划</option>
<option value="adjust">计划调整</option>
<option value="discussion">讨论整理</option>
</select>
</label>
<label>未解决的问题，每行一项<textarea v-model="draft.questions" rows="2" placeholder="讨论解决后删除对应问题；存在未解决问题时不能发布">
</textarea>
</label>
<label v-if="needsReason">重新核对原因<textarea v-model="reason" rows="2" required placeholder="说明过期数据已如何重新核对">
</textarea>
</label>
<div class="draft-add-bar">
<label>加入现有未完成任务<select v-model="selectedTask">
<option value="">选择要调整的任务</option>
<option v-for="task in available" :key="task.id" :value="task.id">{{ task.title }}</option>
</select>
</label>
<button type="button" class="button secondary" :disabled="!selectedTask" @click="addExisting">加入草案</button>
<button type="button" class="button secondary" @click="newTask">＋ 新任务</button>
</div>
<details v-for="(task, index) in draft.tasks" :key="task.key" class="draft-task" open>
<summary>
<strong>{{ index + 1 }}. {{ task.title || '未命名任务' }}</strong>
<span class="caption">{{ task.existing_id ? '调整现有任务' : '新增任务' }}</span>
</summary>
<p class="caption">稳定标识：{{ task.key }}</p>
<TaskFields :form="task" :planning="true" :draft="true" :choices="choices" />
<button type="button" class="link-button danger-text" @click="draft.tasks.splice(index,1)">从草案移除此项</button>
</details>
<fieldset v-if="!card && s.data.messages.some(x => x.kind === 'human')">
<legend>可选：关联真实讨论来源</legend>
<div class="source-picker">
<label v-for="message in s.data.messages.filter(x => x.kind === 'human')" :key="message.id" class="checkbox-label">
<input type="checkbox" v-model="draft.source_message_ids" :value="message.id">{{ message.sender_name }}：{{ message.content }}</label>
</div>
</fieldset>
<p class="caption">草案依赖使用稳定任务标识；发布时由服务端转换成任务 ID。阶段、工时、依赖和日期由服务端统一检查。</p>
<p v-if="error" class="error" role="alert">{{ error }}</p>
<div class="form-actions">
<button type="button" class="button secondary" @click="emit('close')">取消</button>
<button class="button" :disabled="busy">{{ busy ? '校验并保存中…' : '保存并检查草案' }}</button>
</div>
</form>
</Modal>
</template>
