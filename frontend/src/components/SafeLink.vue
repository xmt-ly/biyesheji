<script setup>
import { computed, inject, ref } from 'vue'
import { safeUrl } from '../state.js'
const props = defineProps({ value: String, label: String })
const ws = inject('workspace')
const url = computed(() => safeUrl(props.value))
const error = ref(''), busy = ref(false)
async function download() {
  busy.value = true; error.value = ''
  try { await ws.download(url.value.split('/').at(-1), props.label) } catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
<span class="safe-link">
<button v-if="url.startsWith('/api/files/')" class="link-button" :disabled="busy" @click="download">{{ busy ? '下载中…' : label || '下载附件' }}</button>
<a v-else-if="url" :href="url" target="_blank" rel="noopener noreferrer">{{ label || value }}</a>
<span v-else>{{ value ? '链接格式无效' : '未填写' }}</span>
<small v-if="error" class="error">{{ error }}</small>
</span>
</template>
