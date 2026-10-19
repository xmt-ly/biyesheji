<script setup>
import { inject, ref } from 'vue'
import { canPublishCard, time, statusNames } from '../state.js'
import Checks from './Checks.vue'
import Modal from './Modal.vue'
import CardEditor from './CardEditor.vue'
import AppIcon from './AppIcon.vue'
const emit = defineEmits(['reply','source'])
const ws = inject('workspace'), s = ws.s, edit = ref(false), selected = ref(null), feedbackCard = ref(null), feedback = ref(''), confirmed = ref(false), publishCard = ref(null), acknowledge = ref(false), rejectCard = ref(null), rejectReason = ref(''), error = ref(''), busy = ref(false)
const name = id => s.data.project?.members.find(x => x.user_id === id)?.name || `成员 ${id}`
function start(card) { selected.value = card; edit.value = true; error.value = '' }
function blockedReason(card) {
  if (['published','rejected','failed','stale'].includes(card.status)) return `草案${statusNames[card.status]}${['failed','stale'].includes(card.status) ? '，请编辑并重新核对' : ''}`
  if (card.base_revision !== s.data.project.revision) return '基础版本已变化，请编辑并填写重新核对原因'
  if (card.questions?.length) return '存在未解决的追问，请先讨论并编辑草案'
  if (!card.tasks?.length) return '没有可发布的任务变更'
  if (!card.checks?.valid) return '规划约束未通过，请根据检查结果修改草案'
  return s.data.project.role !== 'leader' ? '由本项目组长最终确认发布' : ''
}
function editable(card) { return !['published','rejected'].includes(card.status) }
async function submitFeedback() { busy.value = true; error.value = ''; try { await ws.mutate(`/cards/${feedbackCard.value.id}/feedback`, { content:feedback.value, confirmed:confirmed.value }); feedbackCard.value = null } catch(e) { error.value = e.message } finally { busy.value = false } }
async function publish() { busy.value = true; error.value = ''; try { await ws.mutate(`/cards/${publishCard.value.id}/publish`); publishCard.value = null } catch(e) { error.value = e.message } finally { busy.value = false } }
async function reject() { busy.value = true; error.value = ''; try { await ws.mutate(`/cards/${rejectCard.value.id}`, { status:'rejected', reason:rejectReason.value }, 'PATCH'); rejectCard.value = null } catch(e) { error.value = e.message } finally { busy.value = false } }
</script>
<template>
<section class="cards-panel">
<header class="section-head">
<div>
<h2>分析与计划草案</h2>
</div>
<button class="button secondary small" @click="start(null)">＋ 人工草案</button>
</header>
<p class="caption">建议不会直接生效。成员核对，组长发布后写入任务与计划。</p>
<article v-for="card in [...s.data.cards].reverse()" :key="card.id" class="analysis-card">
<header>
<span :class="['pill', card.creator_id ? 'blue' : 'teal']">{{ card.creator_id ? '人工草案' : card.status === 'failed' ? '分析失败记录' : 'Agent 分析' }}</span>
<span :class="['pill', card.status === 'ready' ? 'green' : card.status === 'stale' || card.status === 'failed' ? 'amber' : '']">{{ statusNames[card.status] }}</span>
</header>
<h3>{{ card.title }}</h3>
<p class="pre-line">{{ card.summary }}</p>
<small class="caption">#{{ card.id }} · 基础修订 {{ card.base_revision }} · {{ time(card.created_at) }}</small>
<div v-if="card.questions?.length" class="questions">
<strong>待补充的信息</strong>
<ol>
<li v-for="(question,index) in card.questions" :key="index">{{ question }}</li>
</ol>
</div>
<div v-if="card.tasks?.length" class="draft-summary">
<div v-for="task in card.tasks" :key="task.key">
<strong>{{ task.title }}</strong>
<small>{{ name(task.assignee_id) }} · {{ task.remaining_hours }}h · {{ task.start_date }} → {{ task.due_date }} · 阶段 {{ task.stage_index + 1 }}</small>
<small v-if="task.dependencies?.length">前置：{{ task.dependencies.map(key => card.tasks.find(x => x.key === key)?.title || s.data.tasks.find(x => `task_${x.id}` === key)?.title || key).join('、') }}</small>
</div>
</div>
<Checks :checks="card.checks" compact />
<div v-if="card.source_message_ids?.length" class="source-links">
<strong>讨论依据</strong>
<button v-for="id in card.source_message_ids" :key="id" class="link-button" @click="ws.locateMessage(id); emit('source', id)"><AppIcon name="link" :size="16" />消息 #{{ id }}</button>
</div>
<details v-if="card.feedback?.length">
<summary>成员反馈与修改记录（{{ card.feedback.length }}）</summary>
<div v-for="(item,index) in card.feedback" :key="index" class="feedback-row">
<strong>{{ item.name || item.user_name || name(item.user_id) }} <span v-if="item.confirmed" class="pill green">已核对</span>
<span v-else-if="item.confirmation_invalidated_at" class="pill amber">确认已失效</span>
</strong>
<p>{{ item.content || item.reason || item.type || '更新记录' }}</p>
<small>{{ time(item.created_at || item.at) }}</small>
</div>
</details>
<p v-if="blockedReason(card)" class="caption publish-reason">{{ blockedReason(card) }}</p>
<div class="card-actions">
<button class="button secondary small" @click="emit('reply', { card, correction:false })">回复追问</button>
<button v-if="editable(card)" class="button secondary small" @click="emit('reply', { card, correction:true })">更正建议</button>
<button v-if="editable(card)" class="link-button" @click="start(card)">{{ card.status === 'stale' || card.base_revision !== s.data.project.revision ? '重新核对' : '编辑草案' }}</button>
<button v-if="editable(card)" class="link-button" @click="feedbackCard = card; feedback = ''; confirmed = false; error = ''">反馈核对</button>
<button v-if="s.data.project?.role === 'leader' && editable(card)" class="link-button danger-text" @click="rejectCard = card; rejectReason = ''; error = ''">拒绝</button>
<button v-if="s.data.project?.role === 'leader'" class="button small" :disabled="!canPublishCard(s.data.project.role,card,s.data.project.revision) || !card.tasks?.length" @click="publishCard = card; acknowledge = false; error = ''">发布计划</button>
</div>
</article>
<div v-if="!s.data.cards.length" class="empty cards-empty">
<span class="empty-symbol"><AppIcon name="checklist" :size="32" /></span>
<h3>把讨论整理成共同计划</h3>
<p>配置模型后持续分析讨论并主动追问，<br>人工按钮用于重试或专门规划；也可创建人工草案。</p>
</div>
<CardEditor v-if="edit" :card="selected" @close="edit = false" />
<Modal v-if="feedbackCard" title="反馈并核对草案" @close="feedbackCard = null">
<form @submit.prevent="submitFeedback">
<h3>{{ feedbackCard.title }}</h3>
<label>反馈意见<textarea v-model="feedback" required rows="4" placeholder="请核对本人分工、工时、依赖和日期">
</textarea>
</label>
<label class="checkbox-label">
<input v-model="confirmed" type="checkbox">我已核对当前草案并确认本人安排</label>
<p class="caption">后续草案编辑会撤销旧确认，保留反馈历史。</p>
<p v-if="error" class="error">{{ error }}</p>
<button class="button" :disabled="busy">保存反馈</button>
</form>
</Modal>
<Modal v-if="publishCard" title="最终确认发布计划" @close="publishCard = null">
<form @submit.prevent="publish">
<h3>{{ publishCard.title }}</h3>
<p>发布将保存一个完整计划版本，并更新任务分工与排期。请检查团队反馈和约束结果。</p>
<label class="checkbox-label">
<input v-model="acknowledge" type="checkbox" required>已查看成员反馈并确认分工与排期</label>
<p v-if="error" class="error">{{ error }}</p>
<div class="form-actions">
<button type="button" class="button secondary" @click="publishCard = null">返回核对</button>
<button class="button" :disabled="busy || !acknowledge">{{ busy ? '发布中…' : '确认发布计划' }}</button>
</div>
</form>
</Modal>
<Modal v-if="rejectCard" title="拒绝草案" @close="rejectCard = null">
<form @submit.prevent="reject">
<label>拒绝原因<textarea v-model="rejectReason" rows="3" required>
</textarea>
</label>
<p v-if="error" class="error">{{ error }}</p>
<button class="button" :disabled="busy">记录原因并拒绝</button>
</form>
</Modal>
</section>
</template>
