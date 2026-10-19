<script setup>
import { inject, ref } from 'vue'
const ws = inject('workspace'), username = ref(''), password = ref('')
const accounts = [{ id: 'teacher', text: '课程教师' }, { id: 'leader', text: '一组组长' }, { id: 'member1', text: '一组成员' }, { id: 'member2', text: '一组成员' }, { id: 'leader2', text: '二组组长' }, { id: 'member3', text: '二组成员' }]
function demo(account) { username.value = account; password.value = 'Demo2026!' }
</script>
<template>
<main class="login-page">
<section class="login-intro">
<div class="brand">
<span class="brand-mark">协</span>
<strong>课协 · 课程项目协作</strong>
</div>
<span class="eyebrow">从讨论，到共同完成</span>
<h1>让团队的每一步<br>都有清晰的方向。</h1>
<p>把课程要求、团队讨论、任务分工与阶段成果放在同一个工作区。</p>
<div class="login-flow">
<span>讨论需求</span>
<b>→</b>
<span>核对计划</span>
<b>→</b>
<span>交付成果</span>
</div>
<div class="login-note">智能助手提出建议，团队核对并确认；教师依据成果进行阶段检查。</div>
</section>
<section class="login-panel">
<span class="eyebrow">欢迎回来</span>
<h2>登录你的工作区</h2>
<p class="muted">使用课程项目账号继续协作。</p>
<form @submit.prevent="ws.login(username, password)">
<label>用户名<input v-model="username" required autocomplete="username" placeholder="输入用户名">
</label>
<label>密码<input v-model="password" required type="password" autocomplete="current-password" placeholder="输入密码">
</label>
<p v-if="ws.s.error" class="error" role="alert">{{ ws.s.error }}</p>
<button class="button full" :disabled="ws.s.busy">{{ ws.s.busy ? '正在登录…' : '登录工作区 →' }}</button>
</form>
<div class="demo-accounts">
<strong>演示账号</strong>
<p class="caption">初始化演示数据后可用。统一密码：Demo2026!</p>
<div class="demo-grid">
<button v-for="account in accounts" :key="account.id" class="demo-account" type="button" @click="demo(account.id)">
<strong>{{ account.id }}</strong>
<span>{{ account.text }}</span>
</button>
</div>
</div>
</section>
</main>
</template>
