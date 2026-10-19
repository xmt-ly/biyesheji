<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
defineProps({ title: String, variant: { type: String, default: 'modal', validator: value => ['modal', 'drawer'].includes(value) } })
const emit = defineEmits(['close'])
const panel = ref(null)
const previous = typeof document === 'undefined' ? null : document.activeElement
let previousOverflow
function key(event) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); emit('close') }
  if (event.key === 'Tab') {
    const items = [...panel.value.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])')]
      .filter(item => !item.closest('[hidden], [inert]') && item.getClientRects().length)
    const first = items[0], last = items.at(-1)
    if (!first) { event.preventDefault(); panel.value.focus(); return }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value || !panel.value.contains(document.activeElement))) { event.preventDefault(); last.focus() }
    if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.value || !panel.value.contains(document.activeElement))) { event.preventDefault(); first.focus() }
  }
}
onMounted(() => { previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; panel.value.focus(); document.addEventListener('keydown', key) })
onUnmounted(() => { document.removeEventListener('keydown', key); document.body.style.overflow = previousOverflow; if (previous?.isConnected !== false) previous?.focus() })
</script>
<template>
<div :class="['modal-mask', { 'drawer-mask': variant === 'drawer' }]" @click.self="emit('close')">
<section ref="panel" :class="['modal', { 'modal-drawer': variant === 'drawer' }]" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
<header class="section-head">
<h2>{{ title }}</h2>
<button class="icon-button" aria-label="关闭对话框" @click="emit('close')"><AppIcon name="close" /></button>
</header>
<slot />
</section>
</div>
</template>
