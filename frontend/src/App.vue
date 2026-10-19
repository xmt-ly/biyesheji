<script setup>
import { computed, nextTick, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { createWorkspace } from './workspace.js'
import AppIcon from './components/AppIcon.vue'
import LoginView from './views/LoginView.vue'
import HomeView from './views/HomeView.vue'
import OverviewView from './views/OverviewView.vue'
import CourseView from './views/CourseView.vue'
import MembersView from './views/MembersView.vue'
import RequirementsView from './views/RequirementsView.vue'
import TasksView from './views/TasksView.vue'
import CollaborationView from './views/CollaborationView.vue'
import PlansView from './views/PlansView.vue'
import StagesView from './views/StagesView.vue'

const ws = createWorkspace(), s = ws.s
provide('workspace', ws)
const role = computed(() => s.data.project?.role)
const view = computed(() => ({ home: HomeView, overview: OverviewView, courses: CourseView, members: MembersView, requirements: RequirementsView, tasks: TasksView, collaboration: CollaborationView, plans: PlansView, stages: StagesView }[s.tab] || HomeView))
const title = computed(() => ({ home: s.user?.identity === 'teacher' ? '教师工作台' : '学生工作台', overview: '项目概览', courses: '课程要求', members: '团队成员', requirements: '需求清单', tasks: '任务看板', collaboration: '团队协作', plans: '计划与排期', stages: '阶段成果' }[s.tab]))
const avatarLabel = computed(() => {
  const name = s.user?.name || ''
  if (s.user?.identity === 'teacher') return '师'
  if (name.includes('组长')) return '长'
  return name.match(/成员([甲乙])$/)?.[1] || name.slice(0, 1)
})
const nav = computed(() => [
  { key: 'overview', name: '项目概览', icon: 'overview' },
  ...(s.user?.identity === 'student' ? [{ key: 'collaboration', name: '团队协作', icon: 'chat' }] : []),
  { key: 'requirements', name: s.user?.identity === 'teacher' ? '已确认需求' : '需求清单', icon: 'checklist' },
  { key: 'tasks', name: '任务看板', icon: 'tasks' },
  { key: 'plans', name: '计划与排期', icon: 'calendar' },
  { key: 'stages', name: '阶段成果', icon: 'stages' },
  ...(s.user?.identity === 'student' ? [{ key: 'members', name: '团队成员', icon: 'members' }] : []),
  { key: 'courses', name: '课程要求', icon: 'book' },
])
const pendingCards = computed(() => s.data.cards.filter(card => ['ready', 'pending'].includes(card.status)).length)
const menuOpen = ref(false), compactNavigation = ref(false), sidebar = ref(null), menuTrigger = ref(null), menuClose = ref(null)
let navigationMedia, previousOverflow

async function openNavigation() {
  menuOpen.value = true
  await nextTick()
  menuClose.value?.focus()
}
function closeNavigation(restoreFocus = true) {
  const wasOpen = menuOpen.value
  menuOpen.value = false
  if (wasOpen && restoreFocus) nextTick(() => menuTrigger.value?.focus())
}
function syncNavigation(event) {
  compactNavigation.value = event.matches
  if (!event.matches) closeNavigation(false)
}
function onMenuKeydown(event) {
  if (!compactNavigation.value || !menuOpen.value) return
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeNavigation(); return }
  if (event.key !== 'Tab') return
  const items = [...sidebar.value.querySelectorAll('button:not(:disabled), select:not(:disabled), a[href]')]
    .filter(item => item.getClientRects().length)
  const first = items[0], last = items.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
function navigate(key) {
  s.tab = key
  closeNavigation()
  if (key === 'requirements' && s.user.identity === 'teacher') ws.loadRequirements()
}
function selectProject(id) { closeNavigation(); ws.selectProject(id) }
function logout() { closeNavigation(); ws.logout() }
watch(() => menuOpen.value && compactNavigation.value, open => {
  if (open) { previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden' }
  else if (previousOverflow !== undefined) { document.body.style.overflow = previousOverflow; previousOverflow = undefined }
})
onMounted(() => {
  navigationMedia = window.matchMedia('(max-width: 1023px)')
  syncNavigation(navigationMedia)
  navigationMedia.addEventListener('change', syncNavigation)
  ws.init()
})
onUnmounted(() => {
  navigationMedia?.removeEventListener('change', syncNavigation)
  if (previousOverflow !== undefined) document.body.style.overflow = previousOverflow
  ws.dispose()
})
</script>

<template>
  <div v-if="s.booting" class="boot">
    <div class="brand-mark"><AppIcon name="brand" :size="24" /></div>
    <p>正在恢复工作区…</p>
  </div>
  <LoginView v-else-if="!s.user" />
  <div v-else :class="['app-shell', { 'menu-open': menuOpen }]">
    <div v-if="compactNavigation && menuOpen" class="sidebar-mask" @click="closeNavigation()" />
    <aside id="project-navigation" ref="sidebar" class="sidebar" :role="compactNavigation && menuOpen ? 'dialog' : undefined" :aria-modal="compactNavigation && menuOpen ? 'true' : undefined" aria-label="项目导航" :aria-hidden="compactNavigation && !menuOpen ? true : undefined" :inert="compactNavigation && !menuOpen ? true : undefined" @keydown="onMenuKeydown">
      <div class="sidebar-brand-row">
        <div class="brand">
          <span class="brand-mark"><AppIcon name="brand" :size="22" /></span>
          <div><strong>课协</strong><small>课程项目协作</small></div>
        </div>
        <button ref="menuClose" class="icon-button sidebar-close" aria-label="关闭导航菜单" @click="closeNavigation()"><AppIcon name="close" /></button>
      </div>
      <div class="sidebar-project">
        <label for="project-selector">当前项目</label>
        <select id="project-selector" :value="s.selectedId || ''" @change="selectProject($event.target.value)">
          <option value="" disabled>选择团队项目</option>
          <option v-for="project in s.projects" :key="project.id" :value="project.id">{{ project.name }}</option>
        </select>
      </div>
      <button :class="['nav-item', { active: s.tab === 'home' }]" :aria-current="s.tab === 'home' ? 'page' : undefined" @click="navigate('home')"><AppIcon name="home" />项目工作台</button>
      <nav aria-label="项目页面">
        <button v-for="item in nav" :key="item.key" :disabled="!s.selectedId && item.key !== 'courses'" :class="['nav-item', { active: s.tab === item.key }]" :aria-current="s.tab === item.key ? 'page' : undefined" @click="navigate(item.key)">
          <AppIcon :name="item.icon" />{{ item.name }}<small v-if="item.key === 'collaboration' && pendingCards" :aria-label="pendingCards + '项待核对建议'">{{ pendingCards }}</small>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <span class="avatar">{{ avatarLabel }}</span>
        <div><strong>{{ s.user.name }}</strong><small>{{ s.user.identity === 'teacher' ? '课程教师' : role === 'leader' ? '当前项目组长' : '学生成员' }}</small></div>
        <button class="icon-button" @click="logout" aria-label="退出登录" title="退出登录"><AppIcon name="logout" /></button>
      </div>
    </aside>
    <main class="main-workspace" :inert="compactNavigation && menuOpen ? true : undefined">
      <header class="topbar">
        <div class="topbar-location">
          <button ref="menuTrigger" class="icon-button menu-trigger" aria-label="打开导航菜单" aria-controls="project-navigation" :aria-expanded="menuOpen" @click="openNavigation"><AppIcon name="menu" /></button>
          <div class="breadcrumb"><span class="breadcrumb-project">{{ s.data.project?.name || '课程项目智能协作系统' }}</span><span class="breadcrumb-separator" aria-hidden="true">/</span><strong>{{ title }}</strong></div>
        </div>
        <div class="topbar-actions">
          <span v-if="s.config?.demo_data" class="demo-label">演示数据</span>
          <button v-if="s.selectedId" class="button secondary small refresh-button" :aria-label="s.loading ? '同步中…' : '刷新数据'" :disabled="s.loading" @click="ws.refreshProject()"><AppIcon name="refresh" :size="18" /><span>{{ s.loading ? '同步中…' : '刷新数据' }}</span></button>
          <span class="avatar light" :aria-label="s.user.name">{{ avatarLabel }}</span>
        </div>
      </header>
      <div class="page-area">
        <div v-if="s.tab === 'collaboration' && s.config && !s.config.ai_ready && s.user.identity === 'student'" class="banner warning"><AppIcon name="info" /><span>智能分析尚未配置。你仍可讨论、维护任务和创建人工草案。</span></div>
        <div v-else-if="s.tab === 'collaboration' && s.config?.ai_ready && s.user.identity === 'student'" class="banner info"><AppIcon name="info" /><span>智能分析已就绪，分析结果会在本次请求完成后显示。</span></div>
        <div v-if="s.error" class="banner danger" role="alert"><AppIcon name="alert" /><span>{{ s.error }}</span><button aria-label="关闭错误提示" class="icon-button" @click="s.error = ''"><AppIcon name="close" /></button></div>
        <div v-if="s.notice" class="banner success" role="status"><AppIcon name="check" /><span>{{ s.notice }}</span><button aria-label="关闭操作提示" class="icon-button" @click="s.notice = ''"><AppIcon name="close" /></button></div>
        <div v-for="(error, resource) in s.resourceErrors" :key="resource" class="banner danger" role="alert">{{ ({ tasks:'任务', progress:'进度', plans:'计划', submissions:'阶段成果', requirements:'需求', cards:'分析卡片', files:'附件', messages:'聊天历史', runs:'分析记录', course:'课程', courses:'课程列表', projects:'项目列表', config:'配置状态' })[resource] || resource }}加载失败：{{ error }}</div>
        <component :is="view" :key="s.selectedId + '-' + s.tab" />
      </div>
    </main>
  </div>
</template>

