import { computed, reactive, ref, watch } from 'vue'

export function useMemberDraft(getMember) {
  const form = reactive({ skillsText:'',weeklyHours:0 })
  const baseline = ref(null)
  const dirty = computed(() => baseline.value !== null && (form.skillsText !== baseline.value.skillsText || Number(form.weeklyHours) !== baseline.value.weeklyHours))
  function syncSaved(member) {
    if (!member) return
    const next = { skillsText:member.skills.join('\n'),weeklyHours:member.weekly_hours }
    Object.assign(form,next)
    baseline.value = next
  }
  watch(getMember, member => { if (member && !dirty.value) syncSaved(member) }, { immediate:true })
  return { form,dirty,syncSaved }
}
