<script setup>
import { computed, inject, nextTick, onMounted, ref, watch } from 'vue'
import CardsPanel from '../components/CardsPanel.vue'
import AppIcon from '../components/AppIcon.vue'
import { time, statusNames } from '../state.js'
const ws = inject('workspace'), s = ws.s, content = ref(''), sending = ref(false), mode = ref('discussion'), analyzing = ref(false), error = ref(''), chat = ref(null), relatedType = ref(''), relatedId = ref(''), supersedes = ref([]), composer = ref(null)
const mobilePane = ref('discussion')
const relationChoices = computed(() => relatedType.value === 'task' ? s.data.tasks : relatedType.value === 'requirement' ? s.data.requirements : relatedType.value === 'card' ? s.data.cards : [])
async function send() {
  if (!content.value.trim() || sending.value) return
  sending.value = true
  const payload = { content: content.value.trim(), supersedes_card_ids:supersedes.value }
  if (relatedType.value && relatedId.value) { payload.related_type = relatedType.value; payload.related_id = Number(relatedId.value) }
  content.value = ''; relatedType.value = ''; relatedId.value = ''; supersedes.value = []
  try { await ws.sendMessage(payload) } finally { sending.value = false }
  nextTick(() => { if (chat.value) chat.value.scrollTop = chat.value.scrollHeight })
}
async function reply({ card, correction }) {
  mobilePane.value = 'discussion'
  relatedType.value = 'card'; relatedId.value = card.id; supersedes.value = correction ? [card.id] : []
  await nextTick()
  composer.value?.focus()
}
function source() { mobilePane.value = 'discussion'; scrollFocus() }
function avatar(message) { return message.kind === 'agent' ? 'AI' : message.sender_name?.match(/成员([甲乙])$/)?.[1] || (message.sender_name?.includes('组长') ? '长' : message.sender_name?.slice(0,1)) }
async function analyze() {
  const isCurrent = ws.captureScope()
  analyzing.value = true; error.value = ''
  try { await ws.analyze(mode.value) }
  catch(e) { if (isCurrent()) error.value = e.message }
  finally { analyzing.value = false }
}
async function scrollFocus() {
  await nextTick()
  const element = s.focusMessage ? document.getElementById(`message-${s.focusMessage}`) : null
  if (element) element.scrollIntoView({ behavior:'smooth', block:'center' })
}
watch(() => s.focusMessage, source)
watch(() => s.data.messages.length, () => { nextTick(() => { if (!s.focusMessage && chat.value) chat.value.scrollTop = chat.value.scrollHeight }); scrollFocus() })
onMounted(() => nextTick(() => { if (s.focusMessage) scrollFocus(); else if (chat.value) chat.value.scrollTop = chat.value.scrollHeight }))
</script>
<template>
<div class="page-head compact">
<div>
<h1>团队协作</h1>
<p>讨论任务、报告阻碍，核对团队的下一步安排。</p>
</div>
<div class="connection-status">
<i :class="{ online:s.connection === '已连接' }">
</i>{{ s.connection }}</div>
</div>
<nav class="collaboration-tabs" aria-label="协作内容">
<button :class="{active:mobilePane === 'discussion'}" :aria-pressed="mobilePane === 'discussion'" @click="mobilePane = 'discussion'"><AppIcon name="chat" />讨论</button>
<button :class="{active:mobilePane === 'analysis'}" :aria-pressed="mobilePane === 'analysis'" @click="mobilePane = 'analysis'"><AppIcon name="checklist" />建议与草案 <span v-if="s.data.cards.length">{{ s.data.cards.length }}</span></button>
</nav>
<div class="collaboration-grid">
<section :class="['chat-panel panel',{'mobile-pane-hidden':mobilePane !== 'discussion'}]">
<header class="chat-header">
<div>
<h2>小组聊天室</h2>
<span class="caption">{{ s.data.project?.members.length }} 位成员 · 消息持续保存</span>
</div>
<span class="pill teal">项目内部</span>
</header>
<div ref="chat" class="chat-messages" role="log" aria-label="团队聊天消息" aria-live="polite">
<div v-for="message in s.data.messages" :id="`message-${message.id}`" :key="message.id" :class="['message', { mine:message.user_id === s.user.id, agent:message.kind === 'agent', highlighted:message.id === s.focusMessage }]">
<span class="avatar message-avatar">{{ avatar(message) }}</span>
<div class="message-body">
<header>
<strong>{{ message.sender_name || '智能助手' }}</strong>
<time>{{ time(message.created_at) }}</time>
</header>
<p>{{ message.content }}</p>
<small v-if="message.related_type">关联{{ {task:'任务',requirement:'需求',card:'卡片'}[message.related_type] }} #{{ message.related_id }}<span v-if="message.supersedes_card_ids?.length"> · 更正卡片 {{ message.supersedes_card_ids.join('、') }}</span>
</small>
</div>
</div>
<div v-for="entry in s.outbox" :key="entry.payload.client_id" class="message pending mine">
<div class="message-body">
<p>{{ entry.payload.content }}</p>
<small>{{ entry.sending ? '发送中…' : '发送失败' }}</small>
<p v-if="entry.error" class="error">{{ entry.error }}</p>
<button v-if="!entry.sending" class="link-button" @click="ws.sendMessage(null, entry)">重试发送</button>
</div>
</div>
<div v-if="!s.data.messages.length && !s.outbox.length" class="empty chat-empty">
<span class="empty-symbol"><AppIcon name="chat" :size="32" /></span>
<h3>开始团队讨论</h3>
<p>说说你准备做什么、需要谁协助，<br>以及预计工时和完成日期。</p>
</div>
</div>
<div v-if="s.agentStatus" class="agent-status" role="status">
<span class="status-dot">
</span>{{ s.agentStatus }}</div>
<form class="chat-composer" @submit.prevent="send">
<div class="relation-bar">
<label>关联对象<select v-model="relatedType" @change="relatedId = ''; supersedes = []">
<option value="">普通讨论</option>
<option value="task">任务</option>
<option value="requirement">需求</option>
<option value="card">分析卡片</option>
</select>
</label>
<label v-if="relatedType">选择{{ {task:'任务',requirement:'需求',card:'卡片'}[relatedType] }}<select v-model="relatedId" required>
<option value="" disabled>请选择</option>
<option v-for="item in relationChoices" :key="item.id" :value="item.id">#{{ item.id }} {{ item.title }}</option>
</select>
</label>
<span v-if="supersedes.length" class="pill amber">正在更正旧建议</span>
</div>
<label class="composer-label" for="message-content">团队消息</label>
<textarea ref="composer" id="message-content" v-model="content" rows="3" placeholder="输入讨论内容，例如：我可以负责接口，本周可投入 12 小时…" required maxlength="10000" @keydown.ctrl.enter.prevent="send">
</textarea>
<footer>
<span class="caption">Ctrl + Enter 发送 · 失败消息可重试</span>
<button class="button" :disabled="sending || !content.trim()">{{ sending ? '发送中…' : '发送消息 ↑' }}</button>
</footer>
</form>
</section>
<div :class="['analysis-column',{'mobile-pane-hidden':mobilePane !== 'analysis'}]">
<CardsPanel @reply="reply" @source="source" />
<details class="analysis-controls panel">
<summary>请求智能分析</summary>
<p class="caption">整理讨论、补问缺失信息，或明确请求生成和调整计划。</p>
<div class="analysis-control-row">
<label>分析模式<select v-model="mode">
<option value="discussion">讨论整理与追问</option>
<option value="plan">生成初始计划</option>
<option value="adjust">分析计划调整</option>
</select>
</label>
<button class="button" :disabled="analyzing" @click="analyze">{{ analyzing ? '请求中…' : '请求分析' }}</button>
</div>
<p v-if="error" class="error" role="alert">{{ error }}</p>
</details>
<details class="panel runs">
<summary>最近分析运行记录（{{ s.data.runs.length }}）</summary>
<article v-for="run in s.data.runs" :key="run.id" class="run-row">
<strong>#{{ run.id }} · {{ statusNames[run.status] || run.status }}</strong>
<span>{{ run.model || '模型未提供' }} · {{ run.elapsed_ms == null ? '耗时未知' : `${run.elapsed_ms} ms` }} · 用量 {{ run.tokens == null ? '未知' : typeof run.tokens === 'object' ? JSON.stringify(run.tokens) : run.tokens }}</span>
<small>{{ time(run.created_at) }}</small>
<p v-if="run.error" class="error">{{ run.error }}</p>
</article>
<p v-if="!s.data.runs.length" class="empty">暂无分析运行记录</p>
</details>
</div>
</div>
</template>
<style scoped>
.collaboration-tabs { display:none; }
@media(max-width:767px) {
  .collaboration-tabs { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:16px; }
  .collaboration-tabs button { display:flex; justify-content:center; align-items:center; gap:8px; min-height:44px; border:1px solid var(--border); background:#fff; border-radius:8px; color:var(--muted); }
  .collaboration-tabs button.active { color:var(--teal); background:#eef5f3; border-color:var(--teal); }
  .mobile-pane-hidden { display:none; }
}
</style>
