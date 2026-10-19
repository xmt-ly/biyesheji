<script setup>
import { inject, computed, ref, watch } from 'vue'
import Modal from '../components/Modal.vue'
import AppIcon from '../components/AppIcon.vue'
import TaskDetails from '../components/TaskDetails.vue'
import { statusNames } from '../state.js'
import { buildWorkbench } from '../workbench.js'

const ws = inject('workspace'), s = ws.s
const create = ref(false), busy = ref(false), error = ref(''), form = ref({ course_id: '', name: '', description: '' }), taskId = ref(null)
const teacher = computed(() => s.user.identity === 'teacher')
const currentProject = computed(() => s.selectedId ? s.data.project : null)
const workbench = computed(() => buildWorkbench({ userId: s.user.id, tasks: s.data.tasks, cards: teacher.value ? [] : s.data.cards, stages: s.data.course?.stages, submissions: s.data.submissions }))
const selectedTask = computed(() => teacher.value ? null : s.data.tasks.find(task => task.id === taskId.value))
watch(() => s.selectedId, () => { taskId.value = null })
function stageStatus(status) { return status === 'pending' ? '待审核' : status === 'unsubmitted' ? '未提交' : statusNames[status] || status }
function memberName(id) { return currentProject.value?.members?.find(member => member.user_id === id)?.name || '待分配' }
function requirementName(id) { return s.data.requirements?.find(item => item.id === id)?.title || '未关联需求' }
async function submit() {
  const isCurrent = ws.captureScope()
  busy.value = true; error.value = ''
  try { await ws.createProject({ ...form.value, course_id: Number(form.value.course_id) }); if (isCurrent()) create.value = false }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>

<template>
<div class="page-head">
  <div>
    <h1>{{ teacher ? '教学工作台' : '我的工作台' }}</h1>
    <p>{{ s.user.name }}，{{ teacher ? '查看课程安排、指导项目和阶段成果。' : '从本人任务继续推进，及时核对团队安排。' }}</p>
  </div>
  <button v-if="!teacher" class="button secondary" @click="create = true"><AppIcon name="plus" />创建团队项目</button>
  <button v-else class="button" @click="s.tab = 'courses'"><AppIcon name="book" />管理课程任务</button>
</div>

<template v-if="currentProject && !teacher">
  <div class="home-project-context">
    <div><strong>{{ currentProject.name }}</strong><span class="caption">当前项目 · {{ { leader: '组长', member: '成员' }[currentProject.role] }}</span></div>
    <span v-if="s.data.progress" class="caption">任务完成 {{ s.data.progress.done }} / {{ s.data.progress.total }} 项 · {{ s.data.progress.completion_percent }}% <small>按完成数量计算</small></span>
  </div>
  <div class="home-workbench">
    <div class="home-primary">
      <section class="panel home-next" aria-label="我的下一步">
        <header class="section-head">
          <div class="home-icon-heading"><span class="home-feature-icon"><AppIcon name="checklist" /></span><h2>我的下一步</h2></div>
          <button class="button secondary" @click="s.tab = 'collaboration'"><AppIcon name="chat" />去讨论</button>
        </header>
        <template v-if="workbench.nextTask">
          <h3>{{ workbench.nextTask.title }}</h3>
          <p class="caption">截止 {{ workbench.nextTask.due_date || '未设置' }} · 剩余 {{ workbench.nextTask.remaining_hours }} 小时</p>
          <p v-if="workbench.nextTask.blocker" class="home-blocker"><AppIcon name="alert" /><span>阻碍：{{ workbench.nextTask.blocker }}</span></p>
          <p v-else-if="workbench.nextTask.planning_risks?.length" class="home-blocker"><AppIcon name="info" /><span>这项任务存在规划待处理事项，请查看任务依据。</span></p>
          <button class="button" @click="taskId = workbench.nextTask.id">继续本人任务<AppIcon name="arrow-right" /></button>
        </template>
        <template v-else>
          <h3>{{ workbench.myTasks.length ? '本人任务已完成' : '还没有分配给你的任务' }}</h3>
          <p class="caption">{{ workbench.myTasks.length ? '可查看团队进展、核对安排和阶段反馈。' : '先参与团队讨论，核对分工后由组长发布计划。' }}</p>
          <button class="button secondary" @click="s.tab = 'tasks'">查看任务看板<AppIcon name="arrow-right" /></button>
        </template>
      </section>

      <section aria-label="本人任务">
        <header class="section-head home-list-heading">
          <div><h2>我的任务 <span class="pill">{{ workbench.myTasks.length }}</span></h2><p class="caption">仅本人负责 · {{ workbench.activeTasks.length }} 项待推进</p></div>
          <button class="link-button" @click="s.tab = 'tasks'">任务看板<AppIcon name="arrow-right" :size="16" /></button>
        </header>
        <article v-for="task in workbench.myTasks" :key="task.id" class="panel home-task">
          <header class="section-head"><h3>{{ task.title }}</h3><span class="pill">{{ statusNames[task.status] }} · {{ task.progress }}%</span></header>
          <p v-if="task.description" class="caption pre-line">{{ task.description }}</p>
          <div class="progress-track" :aria-label="task.title + '进度 ' + task.progress + '%'"><i :style="{ width: task.progress + '%' }"></i></div>
          <p v-if="task.blocker" class="home-blocker"><AppIcon name="alert" /><span>阻碍：{{ task.blocker }}</span></p>
          <p v-else-if="task.planning_risks?.length" class="home-blocker"><AppIcon name="info" /><span>规划存在待处理事项，请查看任务依据。</span></p>
          <dl class="home-task-basis">
            <div><dt>关联需求</dt><dd>{{ requirementName(task.requirement_id) }}</dd></div>
            <div><dt>验收条件</dt><dd>{{ task.acceptance || '尚未填写' }}</dd></div>
          </dl>
          <footer class="home-task-footer">
            <span class="caption"><AppIcon name="calendar" :size="16" />{{ task.due_date || '未设置截止日期' }} · 剩余 {{ task.remaining_hours }} 小时</span>
            <button class="link-button" @click="taskId = task.id">{{ task.status === 'done' ? '查看任务详情' : '保存本人进度' }}<AppIcon name="arrow-right" :size="16" /></button>
          </footer>
        </article>
        <p v-if="!workbench.myTasks.length" class="panel empty">分工发布后，本人任务会显示在这里。</p>
      </section>

      <section aria-label="协同关注">
        <header class="section-head home-list-heading"><div><h2>协同关注 <span class="pill">{{ workbench.teamTasks.length }}</span></h2><p class="caption">其他成员的未完成任务，不计入本人任务数</p></div></header>
        <div class="panel home-team-list">
          <article v-for="task in workbench.teamTasks" :key="task.id" class="home-team-row">
            <div><h3>{{ task.title }}</h3><p class="caption">{{ memberName(task.assignee_id) }} · {{ statusNames[task.status] }} · 截止 {{ task.due_date || '未设置' }}</p><p v-if="task.blocker" class="caption">阻碍：{{ task.blocker }}</p></div>
            <button class="link-button" @click="taskId = task.id">查看详情<AppIcon name="arrow-right" :size="16" /></button>
          </article>
          <p v-if="!workbench.teamTasks.length" class="empty">其他成员暂无待推进任务。</p>
        </div>
      </section>
    </div>

    <aside class="home-secondary">
      <section class="panel home-card-reminder">
        <header class="section-head"><h2>待核对安排</h2><span class="pill">{{ workbench.pendingCards.length }}</span></header>
        <p class="caption">成员反馈和核对后，由组长最终确认并发布。</p>
        <div v-for="card in workbench.pendingCards" :key="card.id" class="home-card-preview">
          <strong>{{ card.title || '团队安排草案' }}</strong><span class="pill">{{ statusNames[card.status] }}</span><p v-if="card.summary" class="caption pre-line">{{ card.summary }}</p>
        </div>
        <p v-if="!workbench.pendingCards.length" class="caption">暂无待核对草案。团队讨论中的安排可在协作页整理。</p>
        <button class="button full" @click="s.tab = 'collaboration'">{{ workbench.pendingCards.length ? '进入团队协作核对' : '进入团队协作' }}<AppIcon name="arrow-right" /></button>
      </section>
      <section class="panel home-stage-reminder">
        <header class="section-head"><h2>课程检查阶段</h2><AppIcon name="stages" /></header>
        <p class="caption"><template v-if="workbench.nextStage">下一项：{{ workbench.nextStage.stage.name }}</template><template v-else>{{ workbench.stageItems.length ? '各阶段最新提交均已通过' : '课程尚未设置检查阶段' }}</template></p>
        <ol class="home-stage-list">
          <li v-for="item in workbench.stageItems" :key="item.index" :class="{ 'home-stage-next': item.index === workbench.nextStage?.index }">
            <div><strong>{{ item.index + 1 }}. {{ item.stage.name }}</strong><span class="pill">{{ stageStatus(item.status) }}</span></div>
            <p class="caption">截止 {{ item.stage.deadline }}<template v-if="item.submission"> · 最新提交 v{{ item.submission.version }}</template></p>
          </li>
        </ol>
        <button class="button secondary full" @click="s.tab = 'stages'">查看阶段成果<AppIcon name="arrow-right" /></button>
        <p class="caption home-footnote">成员上传材料，组长组织阶段提交；教师意见保留在各提交版本中。</p>
      </section>
    </aside>
  </div>
</template>

<div v-else-if="teacher" class="home-teaching">
  <section class="panel">
    <header class="section-head"><h2>我的课程 <span class="pill">{{ s.courses.length }}</span></h2><button class="link-button" @click="s.tab = 'courses'">查看课程要求<AppIcon name="arrow-right" :size="16" /></button></header>
    <div v-for="course in s.courses" :key="course.id" class="home-course-row"><strong>{{ course.title }}</strong><span class="pill">{{ statusNames[course.status] || '课程' }}</span></div>
    <p v-if="!s.courses.length" class="caption">先创建课程任务并发布课程要求。</p>
  </section>
  <section v-if="currentProject" class="panel">
    <header class="section-head"><div><h2>{{ currentProject.name }} · 阶段安排</h2><p v-if="s.data.progress" class="caption">任务完成 {{ s.data.progress.done }} / {{ s.data.progress.total }} 项 · {{ s.data.progress.completion_percent }}%（按完成数量计算）</p></div></header>
    <ol class="home-stage-list">
      <li v-for="item in workbench.stageItems" :key="item.index"><div><strong>{{ item.index + 1 }}. {{ item.stage.name }}</strong><span class="pill">{{ stageStatus(item.status) }}</span></div><p class="caption">截止 {{ item.stage.deadline }}<template v-if="item.submission"> · 最新提交 v{{ item.submission.version }}</template></p></li>
    </ol>
    <p v-if="!workbench.stageItems.length" class="caption">课程尚未设置检查阶段。</p>
    <button class="button secondary" @click="s.tab = 'stages'">查看成果与审核意见<AppIcon name="arrow-right" /></button>
  </section>
  <section v-else class="panel empty"><h3>选择一个指导项目</h3><p>进入项目后，可查看公开任务进度、已发布计划和阶段提交。</p></section>
</div>
<section v-else class="panel home-selection-hint"><AppIcon name="home" /><div><h2>{{ s.loading ? '正在加载当前项目…' : '先选择一个团队项目' }}</h2><p class="caption">选择后，在工作台查看本人任务、待核对安排和阶段反馈。</p></div></section>

<section class="home-projects">
  <header class="section-head"><h2>{{ teacher ? '我的指导项目' : '我的团队项目' }} <span class="pill">{{ s.projects.length }}</span></h2><button class="link-button" @click="ws.loadBasics()">刷新项目列表</button></header>
  <div class="project-grid">
    <button v-for="project in s.projects" :key="project.id" :class="['project-tile', { 'home-project-selected': project.id === s.selectedId }]" @click="ws.selectProject(project.id)">
      <div class="project-tile-top"><span class="project-symbol"><AppIcon name="members" /></span><span class="pill">{{ { leader: '组长', member: '成员', teacher: '指导教师' }[project.role] }}</span></div>
      <h3>{{ project.name }}</h3><p>{{ project.description || '进入项目查看团队进度与成果' }}</p>
      <footer><span>{{ project.members?.length || 0 }} 位成员</span><strong>{{ project.id === s.selectedId ? '当前项目' : '进入工作区' }}<AppIcon name="arrow-right" :size="16" /></strong></footer>
    </button>
  </div>
  <div v-if="!s.projects.length" class="panel empty"><h3>暂无可访问的项目</h3><p>{{ teacher ? '发布课程后，学生创建的项目将在这里展示。' : '可以从已发布课程创建项目，或请组长按用户名邀请你加入。' }}</p></div>
</section>

<TaskDetails v-if="selectedTask" :key="selectedTask.id" :task="selectedTask" @close="taskId = null" />
<Modal v-if="create" title="创建团队项目" @close="create = false">
  <form @submit.prevent="submit">
    <label>关联已发布课程<select v-model="form.course_id" required><option value="" disabled>请选择课程</option><option v-for="course in s.courses" :key="course.id" :value="course.id">{{ course.title }}</option></select></label>
    <label>项目名称<input v-model="form.name" required maxlength="200"></label>
    <label>项目说明<textarea v-model="form.description" rows="3"></textarea></label>
    <p class="caption">创建后你将成为此项目的组长，可按用户名邀请成员。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="form-actions"><button type="button" class="button secondary" @click="create = false">取消</button><button class="button" :disabled="busy">{{ busy ? '创建中…' : '创建并进入' }}</button></div>
  </form>
</Modal>
</template>

<style scoped>
.home-project-context { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:24px }
.home-project-context > div { display:flex; align-items:center; flex-wrap:wrap; gap:12px }
.home-project-context small { display:inline-block; margin-left:8px }
.home-workbench { display:grid; grid-template-columns:minmax(0, 2fr) minmax(280px, 1fr); gap:24px; align-items:start }
.home-primary,.home-secondary { display:grid; gap:24px; min-width:0 }
.home-workbench .panel,.home-teaching .panel { margin-bottom:0 }
.home-primary :is(h3,p,dd,strong),.home-secondary :is(strong,p) { overflow-wrap:anywhere }
.home-icon-heading { display:flex; gap:12px; align-items:center }
.home-icon-heading h2 { margin:0 }
.home-feature-icon { display:grid; place-items:center; width:44px; height:44px; color:var(--teal); background:var(--selected); border:1px solid var(--border); border-radius:8px }
.home-next > h3 { font-size:18px; margin-top:20px }
.home-blocker { display:flex; align-items:flex-start; gap:8px; padding:12px; border:1px solid var(--border); border-radius:8px; background:var(--wash); margin:16px 0 }
.home-blocker svg { flex-shrink:0; margin-top:2px }
.home-list-heading h2 { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:4px }
.home-list-heading p { margin:0 }
.home-task + .home-task { margin-top:16px }
.home-task h3 { margin:0 }
.home-task .progress-track { margin:16px 0 }
.home-task-basis { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:20px 0; padding:16px 0; border-top:1px solid var(--border); border-bottom:1px solid var(--border) }
.home-task-basis dt { color:var(--muted); font-size:14px; margin-bottom:4px }
.home-task-basis dd { margin:0; font-size:14px }
.home-task-footer { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px }
.home-task-footer > span { display:flex; align-items:center; flex-wrap:wrap; gap:6px }
.home-task-footer svg { flex-shrink:0 }
.home-team-row { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 0 }
.home-team-row:first-child { padding-top:0 }
.home-team-row:last-child { padding-bottom:0 }
.home-team-row + .home-team-row { border-top:1px solid var(--border) }
.home-team-row h3 { margin-bottom:4px }
.home-team-row p { margin-bottom:0 }
.home-team-row .link-button { flex-shrink:0 }
.home-card-preview { border-top:1px solid var(--border); padding:16px 0 }
.home-card-preview > strong { display:block; margin-bottom:8px }
.home-card-preview .pill { margin-bottom:8px }
.home-card-preview p { margin:0 }
.home-card-reminder .full { margin-top:8px }
.home-stage-list { list-style:none; padding:0; margin:16px 0 }
.home-stage-list li { padding:16px 12px; border:1px solid var(--border); border-radius:8px; margin:12px 0; background:var(--wash) }
.home-stage-list li.home-stage-next { background:var(--selected); border-color:var(--teal) }
.home-stage-list li > div { display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:8px }
.home-stage-list p { margin:8px 0 0 }
.home-footnote { margin:20px 0 0; padding-top:16px; border-top:1px solid var(--border) }
.home-teaching { display:grid; grid-template-columns:minmax(0, 1fr) minmax(0, 1.2fr); gap:24px; margin-bottom:24px }
.home-course-row { display:flex; gap:12px; justify-content:space-between; padding:16px 0; border-top:1px solid var(--border) }
.home-course-row strong { overflow-wrap:anywhere }
.home-selection-hint { display:flex; align-items:flex-start; gap:16px; margin-bottom:24px }
.home-selection-hint > svg { color:var(--teal); flex-shrink:0; margin-top:4px }
.home-selection-hint h2 { margin-bottom:4px }
.home-selection-hint p { margin:0 }
.home-projects { margin-top:32px; min-width:0 }
.home-project-selected { border-color:var(--teal) }
.project-tile footer strong { display:inline-flex; align-items:center; gap:6px }
.link-button { display:inline-flex; align-items:center; gap:6px; min-height:44px }
@media (max-width:1000px) { .home-workbench { grid-template-columns:minmax(0, 1.6fr) minmax(260px, 1fr) } }
@media (max-width:767px) { .home-workbench,.home-teaching { grid-template-columns:minmax(0, 1fr) } .home-task-basis { grid-template-columns:minmax(0, 1fr) } .home-team-row { flex-wrap:wrap } .home-next .section-head { align-items:flex-start } .home-project-context { align-items:flex-start } }
</style>
