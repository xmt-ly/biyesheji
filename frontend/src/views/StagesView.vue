<script setup>
import { computed, inject, ref, watch } from 'vue'
import FilePanel from '../components/FilePanel.vue'
import SafeLink from '../components/SafeLink.vue'
import Modal from '../components/Modal.vue'
import Checks from '../components/Checks.vue'
import AppIcon from '../components/AppIcon.vue'
import { lines, safeUrl, statusNames, time } from '../state.js'

const ws = inject('workspace'), s = ws.s
const stageIndex = ref(0), selectedVersions = ref({}), submitting = ref(false)
const summary = ref(''), urls = ref(''), fileIds = ref([]), materials = ref({})
const busy = ref(false), error = ref(''), reviewSubmission = ref(null), reviewResult = ref('passed'), reviewComment = ref('')
const teacher = computed(() => s.user.identity === 'teacher')
const leader = computed(() => !teacher.value && s.data.project?.role === 'leader')
const stages = computed(() => s.data.course?.stages || [])
const stage = computed(() => stages.value[stageIndex.value])
const stageVersions = computed(() => versions(stageIndex.value))
const selectedSubmission = computed(() => stageVersions.value.find(item => item.id === selectedVersions.value[stageIndex.value]) || stageVersions.value[0])
const currentSubmission = computed(() => stageVersions.value[0])
const otherReviews = computed(() => stageVersions.value.filter(item => item.id !== selectedSubmission.value?.id && item.reviews?.length))
const materialEntries = computed(() => Object.entries(selectedSubmission.value?.materials || {}))
const urlList = computed(() => lines(urls.value))
const options = computed(() => [...urlList.value.map(value => ({ value, label: value })), ...s.data.files.filter(file => fileIds.value.includes(file.id)).map(file => ({ value: 'file:' + file.id, label: '附件：' + file.filename }))])

function versions(index) { return s.data.submissions.filter(item => item.stage_index === index).sort((a, b) => b.version - a.version) }
function latest(index) { return versions(index)[0] }
function stageStatus(status) { return status === 'pending' ? '待审核' : statusNames[status] || '未提交' }
function selectVersion(index, submission) { stageIndex.value = index; selectedVersions.value = { ...selectedVersions.value, [index]: submission.id } }

watch([stages, () => s.data.submissions], () => {
  if (!stages.value[stageIndex.value]) stageIndex.value = 0
  const next = { ...selectedVersions.value }
  stages.value.forEach((item, index) => {
    const list = versions(index)
    if (!list.some(submission => submission.id === next[index])) next[index] = list[0]?.id
  })
  selectedVersions.value = next
}, { immediate: true, deep: true })
watch(() => s.selectedId, () => {
  stageIndex.value = 0; selectedVersions.value = {}; submitting.value = false; reviewSubmission.value = null; error.value = ''
})
watch([stage, options], () => {
  const next = {}
  for (const deliverable of stage.value?.deliverables || []) next[deliverable] = (materials.value[deliverable] || []).filter(value => options.value.some(option => option.value === value))
  if (stage.value?.deliverables.length === 1) next[stage.value.deliverables[0]] = options.value.map(option => option.value)
  materials.value = next
}, { immediate: true })

function start() {
  if (!leader.value || !stage.value) return
  submitting.value = true; summary.value = ''; urls.value = ''; fileIds.value = []; materials.value = {}; error.value = ''
}
async function submit() {
  if (!leader.value || !stage.value || busy.value) return
  if (urlList.value.some(url => !safeUrl(url) || url.startsWith('/api/'))) { error.value = '阶段成果链接需使用完整的 http 或 https 地址，附件请从文件列表选择'; return }
  if (!options.value.length) { error.value = '请至少提供一个成果链接或附件'; return }
  if (stage.value.deliverables.some(name => !materials.value[name]?.length)) { error.value = '请逐项为每个必需交付物选择材料'; return }
  busy.value = true; error.value = ''
  try {
    await ws.mutate('/projects/' + s.selectedId + '/submissions', { stage_index: stageIndex.value, summary: summary.value, artifact_urls: urlList.value, file_ids: fileIds.value, materials: materials.value })
    submitting.value = false
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
function startReview() { if (!teacher.value || !selectedSubmission.value) return; reviewSubmission.value = selectedSubmission.value; reviewResult.value = 'passed'; reviewComment.value = ''; error.value = '' }
async function review() {
  if (!teacher.value || !reviewSubmission.value || busy.value) return
  busy.value = true; error.value = ''
  try { await ws.mutate('/submissions/' + reviewSubmission.value.id + '/review', { result: reviewResult.value, comment: reviewComment.value }); reviewSubmission.value = null }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
function filename(id) { return s.data.files.find(file => file.id === id)?.filename || '已提交附件（名称暂不可用）' }
async function download(id) { error.value = ''; try { await ws.download(id, filename(id)) } catch (e) { error.value = e.message } }
</script>

<template>
<div class="page-head">
  <div><h1>阶段成果{{ teacher ? '与审核' : '' }}</h1><p>按阶段查看提交材料、当时的计划与进度，以及教师反馈。</p></div>
</div>
<p v-if="error && !submitting && !reviewSubmission" class="banner danger" role="alert">{{ error }}</p>
<div v-if="stages.length" class="stages-workspace">
  <nav class="panel stages-navigation" aria-label="阶段与提交版本">
    <header class="section-head"><h2>课程检查阶段</h2><span class="pill">{{ stages.length }} 个阶段</span></header>
    <ol class="stages-timeline">
      <li v-for="(item, index) in stages" :key="index" :class="{ 'stage-selected': index === stageIndex }">
        <button class="stage-select-button" :aria-pressed="index === stageIndex" @click="stageIndex = index">
          <span class="stage-order">{{ index + 1 }}</span>
          <span class="stage-label"><strong>{{ item.name }}</strong><span class="caption"><AppIcon name="calendar" :size="16" />截止 {{ item.deadline }}</span><span class="stage-latest-status">当前状态：{{ stageStatus(latest(index)?.status) }}</span></span>
        </button>
        <div v-if="index === stageIndex" class="stage-expanded">
          <p class="caption">所需交付物</p>
          <ul class="stage-deliverables"><li v-for="deliverable in item.deliverables" :key="deliverable">{{ deliverable }}</li></ul>
          <div class="stage-version-list">
            <p class="caption">提交版本历史</p>
            <button v-for="submission in versions(index)" :key="submission.id" :class="['stage-version-button', { 'version-selected': selectedSubmission?.id === submission.id }]" :aria-label="'查看' + item.name + '提交 v' + submission.version" :aria-pressed="selectedSubmission?.id === submission.id" @click="selectVersion(index, submission)">
              <span class="stage-version-heading"><strong>v{{ submission.version }}{{ submission.id === latest(index)?.id ? ' · 最新提交' : '' }}</strong><span class="pill">{{ stageStatus(submission.status) }}</span></span>
              <time class="caption">{{ time(submission.created_at) }}</time>
              <span class="stage-version-summary">{{ submission.summary }}</span>
              <span class="caption">关联计划 {{ submission.plan_version ? 'v' + submission.plan_version : '尚无已发布计划' }}</span>
            </button>
            <p v-if="!versions(index).length" class="caption">尚无阶段提交。{{ teacher ? '等待团队准备成果材料。' : '成员可上传附件，由组长提交阶段成果。' }}</p>
          </div>
        </div>
      </li>
    </ol>
  </nav>

  <div class="stages-detail-column">
    <section class="panel stage-context">
      <div><h2>{{ stage?.name }}</h2><p class="caption">截止 {{ stage?.deadline }} · 当前状态：{{ stageStatus(currentSubmission?.status) }}<template v-if="currentSubmission"> · 最新提交 v{{ currentSubmission.version }}</template></p></div>
      <button v-if="leader" class="button" :disabled="busy" @click="start"><AppIcon name="upload" />{{ currentSubmission ? '准备新版本提交' : '提交阶段成果' }}</button>
      <p v-if="teacher" class="caption stage-role-note">检查提交成果并保留指导意见，阶段审核不会自动完成开发任务。</p>
      <p v-else-if="!leader" class="caption stage-role-note">你可以上传成果附件，由本项目组长组织阶段提交。</p>
    </section>

    <section v-if="selectedSubmission" class="panel selected-submission" aria-label="选中提交详情">
      <header class="section-head stage-submission-heading">
        <div><h2>{{ stage?.name }} · 提交 v{{ selectedSubmission.version }}</h2><p class="caption">{{ selectedSubmission.id === currentSubmission?.id ? '正在查看最新提交' : '正在查看历史版本；当前阶段状态依据最新提交' }}</p></div>
        <span class="pill">{{ stageStatus(selectedSubmission.status) }}</span>
      </header>
      <dl class="submission-meta">
        <div><dt>提交时间</dt><dd>{{ time(selectedSubmission.created_at) }}</dd></div>
        <div><dt>提交时的计划</dt><dd>{{ selectedSubmission.plan_version ? 'v' + selectedSubmission.plan_version : '尚无已发布计划' }}</dd></div>
      </dl>
      <section class="submission-section">
        <h3>提交说明</h3><p class="submission-summary pre-line">{{ selectedSubmission.summary }}</p>
      </section>
      <section class="submission-section">
        <h3>已提交交付材料</h3>
        <div v-if="materialEntries.length" class="stage-material-list">
          <article v-for="[deliverable, values] in materialEntries" :key="deliverable" class="stage-material-group">
            <h4>{{ deliverable }}</h4>
            <ul><li v-for="value in values" :key="value"><template v-if="value.startsWith('file:')"><AppIcon name="file" :size="18" /><span>{{ filename(Number(value.slice(5))) }}</span><button class="button secondary" @click="download(Number(value.slice(5)))"><AppIcon name="download" :size="18" />下载文件</button></template><SafeLink v-else :value="value" /></li></ul>
          </article>
        </div>
        <ul v-else class="stage-legacy-materials">
          <li v-for="url in selectedSubmission.artifact_urls" :key="url"><SafeLink :value="url" /></li>
          <li v-for="id in selectedSubmission.file_ids" :key="id"><AppIcon name="file" :size="18" /><span>{{ filename(id) }}</span><button class="button secondary" @click="download(id)"><AppIcon name="download" :size="18" />下载文件</button></li>
        </ul>
        <p class="caption">材料属于这个提交版本，可逐项查看或下载。</p>
      </section>

      <section class="submission-section stage-snapshot">
        <h3>提交时的项目进度快照</h3>
        <p class="snapshot-count">完成 {{ selectedSubmission.progress_snapshot?.done ?? selectedSubmission.progress_snapshot?.completed ?? '—' }} / {{ selectedSubmission.progress_snapshot?.total ?? selectedSubmission.progress_snapshot?.tasks?.length ?? '—' }} 项 · 完成比例 {{ selectedSubmission.progress_snapshot?.completion_percent == null ? '—' : selectedSubmission.progress_snapshot.completion_percent + '%' }}</p>
        <p class="caption">按提交时已完成任务数量计算；之后任务推进不会改写本快照，完成比例不代表验收结论。</p>
        <Checks :checks="selectedSubmission.progress_snapshot?.planning_checks" compact />
        <div v-if="selectedSubmission.progress_snapshot?.tasks?.length" class="snapshot-task-list">
          <div v-for="task in selectedSubmission.progress_snapshot.tasks" :key="task.id" class="snapshot-task-row"><span>{{ task.title }}</span><span class="caption">{{ statusNames[task.status] }} · {{ task.progress }}%</span></div>
        </div>
      </section>

      <section class="submission-section">
        <header class="section-head"><h3>本版本教师意见</h3><button v-if="teacher" class="button" :disabled="busy" @click="startReview">提交审核意见</button></header>
        <article v-for="(item, index) in selectedSubmission.reviews" :key="index" class="stage-review">
          <header><strong>{{ item.reviewer_name || '课程教师' }}</strong><span class="pill">{{ statusNames[item.result] }}</span><time class="caption">{{ time(item.created_at) }}</time></header>
          <p class="pre-line">{{ item.comment }}</p>
        </article>
        <p v-if="!selectedSubmission.reviews?.length" class="caption">这个版本尚无教师意见。</p>
      </section>
      <section v-if="otherReviews.length" class="submission-section">
        <h3>本阶段其他版本的审核记录</h3>
        <details v-for="submission in otherReviews" :key="submission.id" class="stage-review-history">
          <summary>提交 v{{ submission.version }} · {{ submission.reviews.length }} 条意见</summary>
          <article v-for="(item, index) in submission.reviews" :key="index" class="stage-review"><header><strong>{{ item.reviewer_name || '课程教师' }}</strong><span class="pill">{{ statusNames[item.result] }}</span><time class="caption">{{ time(item.created_at) }}</time></header><p class="pre-line">{{ item.comment }}</p></article>
        </details>
      </section>
    </section>
    <section v-else class="panel empty"><AppIcon name="stages" :size="28" /><h3>这个阶段还没有提交记录</h3><p>{{ teacher ? '团队提交后，材料、进度快照和审核入口会显示在这里。' : '先整理本阶段所需交付物，上传附件或准备成果链接，再由组长提交。' }}</p></section>
    <FilePanel v-if="!teacher" />
  </div>
</div>
<p v-else class="panel empty">课程尚未设置检查阶段</p>

<Modal v-if="submitting && leader" :title="'提交 ' + stage?.name" @close="submitting = false">
  <form @submit.prevent="submit">
    <label>阶段说明<textarea v-model="summary" rows="3" required placeholder="说明已完成内容、材料和当前问题"></textarea></label>
    <label>成果链接，每行一个<textarea v-model="urls" rows="3" placeholder="https://..."></textarea></label>
    <fieldset><legend>选择团队已上传附件</legend><label v-for="file in s.data.files" :key="file.id" class="checkbox-label"><input type="checkbox" v-model="fileIds" :value="file.id">{{ file.filename }} · {{ (file.size / 1024).toFixed(1) }} KiB</label><p v-if="!s.data.files.length" class="caption">尚无附件，请先在团队成果附件区上传。</p></fieldset>
    <fieldset v-for="deliverable in stage?.deliverables" :key="deliverable"><legend>{{ deliverable }} · 必需材料</legend><label v-for="option in options" :key="option.value" class="checkbox-label"><input type="checkbox" v-model="materials[deliverable]" :value="option.value">{{ option.label }}</label><p v-if="!options.length" class="caption">先添加成果链接或选择附件，再逐项映射交付材料。</p></fieldset>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="form-actions"><button type="button" class="button secondary" @click="submitting = false">取消</button><button class="button" :disabled="busy">{{ busy ? '提交中…' : '保存新的提交版本' }}</button></div>
  </form>
</Modal>
<Modal v-if="reviewSubmission && teacher" title="教师阶段检查" @close="reviewSubmission = null">
  <form @submit.prevent="review">
    <h3>{{ stages[reviewSubmission.stage_index]?.name }} · v{{ reviewSubmission.version }}</h3>
    <label>检查结果<select v-model="reviewResult"><option value="passed">通过</option><option value="needs_changes">需要修改</option></select></label>
    <label>检查意见<textarea v-model="reviewComment" rows="4" required placeholder="说明验收情况或需补充内容"></textarea></label>
    <p class="caption">审核仅记录阶段结果，不会自动标记开发任务完成。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <button class="button" :disabled="busy">{{ busy ? '保存中…' : '保存审核意见' }}</button>
  </form>
</Modal>
</template>

<style scoped>
.stages-workspace { display:grid; grid-template-columns:minmax(260px, 1fr) minmax(0, 2fr); align-items:start; gap:24px }
.stages-navigation,.stages-detail-column { min-width:0 }
.stages-workspace .panel { margin-bottom:0 }
.stages-detail-column { display:grid; gap:24px }
.stages-navigation h2 { margin:0 }
.stages-timeline { list-style:none; padding:0; margin:16px 0 0 }
.stages-timeline > li { margin:16px 0 0; border:1px solid var(--border); border-radius:12px; overflow:hidden }
.stages-timeline > li:first-child { margin-top:0 }
.stages-timeline > li.stage-selected { border-color:var(--teal); background:var(--selected) }
.stage-select-button { display:flex; width:100%; align-items:flex-start; gap:12px; padding:16px; text-align:left; color:var(--ink); border:0; background:transparent; min-height:44px }
.stage-order { display:grid; place-items:center; width:28px; height:28px; border:1px solid var(--border); border-radius:50%; flex-shrink:0; font-size:14px }
.stage-selected .stage-order { color:var(--teal); border-color:var(--teal); background:var(--surface) }
.stage-label { display:grid; gap:8px; min-width:0; overflow-wrap:anywhere }
.stage-label .caption { display:flex; align-items:center; gap:6px; flex-wrap:wrap }
.stage-label svg { flex-shrink:0 }
.stage-latest-status { font-size:14px; color:var(--teal) }
.stage-expanded { padding:0 16px 16px }
.stage-expanded > p { margin-bottom:6px }
.stage-deliverables { margin:0 0 16px; color:var(--muted); font-size:14px; overflow-wrap:anywhere }
.stage-version-list { border-top:1px solid var(--border); padding-top:16px }
.stage-version-list > p { margin-bottom:8px }
.stage-version-button { display:grid; width:100%; text-align:left; gap:8px; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; margin-top:12px; color:var(--ink); min-height:44px; overflow-wrap:anywhere }
.stage-version-button.version-selected { border-color:var(--teal) }
.stage-version-heading { display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:8px }
.stage-version-summary { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; font-size:14px }
.stage-context { display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px }
.stage-context > div { min-width:0 }
.stage-context h2 { margin-bottom:8px; overflow-wrap:anywhere }
.stage-context p { margin:0 }
.stage-role-note { flex-basis:100% }
.stage-submission-heading h2 { margin-bottom:8px; overflow-wrap:anywhere }
.stage-submission-heading p { margin:0 }
.submission-meta { display:flex; flex-wrap:wrap; gap:16px 32px; margin:16px 0 24px; padding-bottom:20px; border-bottom:1px solid var(--border) }
.submission-meta dt { color:var(--muted); font-size:14px; margin-bottom:4px }
.submission-meta dd { margin:0; font-size:14px }
.submission-section + .submission-section { margin-top:24px; padding-top:24px; border-top:1px solid var(--border) }
.submission-section h3 { margin-bottom:12px }
.submission-summary { padding:16px; border:1px solid var(--border); border-radius:8px; background:var(--wash); margin:0 }
.stage-material-group { border:1px solid var(--border); border-radius:8px; overflow:hidden; margin-top:12px }
.stage-material-group h4 { margin:0; padding:12px 16px; font-size:14px; background:var(--wash); overflow-wrap:anywhere }
.stage-material-group ul,.stage-legacy-materials { list-style:none; padding:0; margin:0 }
.stage-material-group li,.stage-legacy-materials li { display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:12px 16px; margin:0; overflow-wrap:anywhere; min-width:0 }
.stage-material-group li + li { border-top:1px solid var(--border) }
.stage-material-group li > span,.stage-legacy-materials li > span { flex:1; min-width:0 }
.stage-material-group li > svg,.stage-legacy-materials li > svg { color:var(--teal); flex-shrink:0 }
.stage-material-list + .caption { margin-top:12px }
.stage-legacy-materials { border:1px solid var(--border); border-radius:8px }
.stage-legacy-materials + .caption { margin-top:12px }
.snapshot-count { font-weight:600; font-variant-numeric:tabular-nums }
.snapshot-task-list { border:1px solid var(--border); border-radius:8px; overflow:hidden; margin-top:16px }
.snapshot-task-row { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; padding:12px 16px; overflow-wrap:anywhere }
.snapshot-task-row + .snapshot-task-row { border-top:1px solid var(--border) }
.stage-review { margin-top:12px; padding:16px; background:var(--wash); border:1px solid var(--border); border-radius:8px }
.stage-review header { display:flex; align-items:center; gap:12px; flex-wrap:wrap }
.stage-review p { margin:12px 0 0 }
.stage-review-history { padding:12px 0; border-bottom:1px solid var(--border) }
.stage-review-history summary { min-height:44px; display:flex; align-items:center; cursor:pointer; overflow-wrap:anywhere }
.selected-submission :is(p,strong,time,dd) { overflow-wrap:anywhere }
@media (max-width:1000px) { .stages-workspace { grid-template-columns:minmax(240px, 1fr) minmax(0, 1.7fr) } }
@media (max-width:767px) { .stages-workspace { grid-template-columns:minmax(0, 1fr) } .stage-context { gap:12px } .stage-context > .button { width:100% } .stage-material-group li,.stage-legacy-materials li { padding:12px } .stage-material-group .button,.stage-legacy-materials .button { flex-basis:100% } .submission-meta { display:grid; gap:16px } }
</style>
