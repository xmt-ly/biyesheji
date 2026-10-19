<script setup>
defineProps({ checks: Object, compact: Boolean })
</script>
<template>
<div v-if="checks" :class="['checks', checks.valid ? 'checks-ok' : 'checks-warning']">
<strong>{{ checks.valid ? '约束检查通过' : '当前规划存在待处理事项' }}</strong>
<ul v-if="checks.violations?.length">
<li v-for="(item, index) in checks.violations" :key="index">{{ item.message }}<span v-if="item.week"> · {{ item.week }} 周 / {{ item.allocated_hours }}h / 容量 {{ item.capacity_hours }}h</span>
<span v-if="item.task_keys?.length"> · {{ item.task_keys.join('、') }}</span>
</li>
</ul>
<p v-if="!compact && checks.calculation" class="caption">{{ checks.calculation }}</p>
</div>
</template>
