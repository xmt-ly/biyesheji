<script setup>
import { computed, inject, ref } from 'vue'
import { useMemberDraft } from '../memberDraft.js'
const ws = inject('workspace'), s = ws.s, busy = ref(false), error = ref(''), username = ref('')
const mine = computed(() => s.data.project?.members.find(x => x.user_id === s.user.id))
const { form,dirty,syncSaved } = useMemberDraft(() => mine.value)
async function run(path, data, after) { if (busy.value) return; busy.value = true; error.value = ''; try { const result = await ws.mutate(path, data, path.endsWith('/me') ? 'PATCH' : 'POST'); after?.(result) } catch (e) { error.value = e.message } finally { busy.value = false } }
</script>
<template>
<div class="page-head">
<div>
<span class="eyebrow">团队协调</span>
<h1>成员与投入时间</h1>
<p>本人填写技能和每周容量，用于排期约束检查。</p>
</div>
</div>
<div class="member-grid">
<article v-for="member in s.data.project?.members" :key="member.user_id" class="panel member-card">
<span class="avatar light large">{{ member.name.slice(0,1) }}</span>
<h3>{{ member.name }} <span class="pill">{{ member.role === 'leader' ? '组长' : '成员' }}</span>
</h3>
<p class="muted">@{{ member.username }}</p>
<div class="tags">
<span v-for="skill in member.skills" :key="skill" class="tag">{{ skill }}</span>
<span v-if="!member.skills.length" class="muted">尚未填写技能</span>
</div>
<strong class="capacity">{{ member.weekly_hours }} <small>小时 / 周</small>
</strong>
</article>
</div>
<div class="two-column">
<section v-if="mine" class="panel">
<h3>我的协作信息</h3>
<form @submit.prevent="run(`/projects/${s.selectedId}/members/me`, { skills: form.skillsText.split('\n').map(x => x.trim()).filter(Boolean), weekly_hours: Number(form.weeklyHours) }, syncSaved)">
<label>技能标签，每行一项<textarea v-model="form.skillsText" :disabled="busy" rows="4" placeholder="Python&#10;Vue">
</textarea>
</label>
<label>可投入时间（小时 / 周）<input v-model.number="form.weeklyHours" :disabled="busy" type="number" min="0" max="168" step="0.5" required>
</label>
<button class="button" :disabled="busy">保存本人信息</button>
<p v-if="dirty" class="caption">有尚未保存的修改。团队实时刷新会保留当前输入。</p>
</form>
</section>
<section v-if="s.data.project?.role === 'leader'" class="panel">
<h3>邀请学生加入项目</h3>
<p class="caption">使用学生的准确用户名；重复邀请已有成员会返回原成员记录。</p>
<form @submit.prevent="run(`/projects/${s.selectedId}/members`, { username }, () => username = '')">
<label>学生用户名<input v-model="username" required autocomplete="off" placeholder="例如 member1">
</label>
<button class="button secondary" :disabled="busy">邀请加入</button>
</form>
</section>
</div>
<p v-if="error" class="banner danger" role="alert">{{ error }}</p>
</template>
