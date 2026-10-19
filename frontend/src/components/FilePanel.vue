<script setup>
import { inject, ref } from 'vue'
import { time } from '../state.js'
const ws = inject('workspace'), error = ref(''), busy = ref(false)
async function upload(event) {
  const file = event.target.files?.[0]; if (!file) return
  busy.value = true; error.value = ''
  try { await ws.upload(file) } catch (e) { error.value = e.message } finally { busy.value = false; event.target.value = '' }
}
async function download(file) {
  error.value = ''
  try { await ws.download(file.id, file.filename) } catch (e) { error.value = e.message }
}
</script>
<template>
<section class="panel">
<header class="section-head">
<div>
<h3>团队成果附件</h3>
<p class="caption">成员上传后，组长可在阶段提交中选择。单文件最多 20 MiB。</p>
</div>
<label v-if="ws.s.user.identity === 'student'" class="button secondary upload-button">{{ busy ? '上传中…' : '上传附件' }}<input type="file" :disabled="busy" @change="upload" accept=".txt,.md,.pdf,.docx,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.zip,.py,.js,.html,.css,.json,.pptx" aria-label="选择并上传成果文件">
</label>
</header>
<p v-if="error" role="alert" class="error">{{ error }}</p>
<div class="file-list">
<div v-for="file in ws.s.data.files" :key="file.id" class="file-row">
<span>
<strong>{{ file.filename }}</strong>
<small>{{ (file.size / 1024).toFixed(1) }} KiB · {{ time(file.created_at) }}</small>
</span>
<button class="link-button" @click="download(file)">下载 {{ file.filename }}</button>
</div>
<p v-if="!ws.s.data.files.length" class="empty">暂无已上传附件</p>
</div>
</section>
</template>
