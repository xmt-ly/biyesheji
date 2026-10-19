<script setup>
import { computed, inject } from 'vue'
const props = defineProps({ form: Object, planning: Boolean, draft: Boolean, choices: Array })
const ws = inject('workspace'), s = ws.s
const dependencies = computed(() => (props.choices || s.data.tasks).filter(task => props.draft ? task.key !== props.form.key : task.id !== props.form.id))
</script>
<template>
<template v-if="planning">
<label>任务名称<input v-model="form.title" required>
</label>
<label>任务说明<textarea v-model="form.description" rows="2" required>
</textarea>
</label>
<div class="form-grid">
<label>关联需求<select v-model.number="form.requirement_id" required>
<option :value="0" disabled>请选择已确认需求</option>
<option v-for="requirement in s.data.requirements.filter(x => x.status === 'confirmed')" :key="requirement.id" :value="requirement.id">{{ requirement.title }}</option>
</select>
</label>
<label>负责人<select v-model.number="form.assignee_id" required>
<option :value="0" disabled>请选择成员</option>
<option v-for="member in s.data.project?.members" :key="member.user_id" :value="member.user_id">{{ member.name }} · {{ member.weekly_hours }}h/周</option>
</select>
</label>
</div>
<label>任务验收条件<textarea v-model="form.acceptance" rows="2" required>
</textarea>
</label>
<div class="form-grid">
<label>预计工时（小时）<input v-model.number="form.estimated_hours" type="number" min="0" step="0.5" required>
</label>
<label>对应阶段<select v-model.number="form.stage_index">
<option v-for="(stage, index) in s.data.course?.stages" :key="index" :value="index">{{ stage.name }} · {{ stage.deadline }}</option>
</select>
</label>
<label>开始日期<input v-model="form.start_date" type="date" required>
</label>
<label>截止日期<input v-model="form.due_date" type="date" required>
</label>
</div>
<fieldset>
<legend>前置依赖</legend>
<label v-for="task in dependencies" :key="task.key || task.id" class="checkbox-label">
<input type="checkbox" v-model="form.dependencies" :value="draft ? task.key || `task_${task.id}` : task.id">{{ task.title }}<small>{{ task.due_date }}</small>
</label>
<p v-if="!dependencies.length" class="caption">没有可选前置任务</p>
</fieldset>
</template>
<div class="form-grid">
<label>任务状态<select v-model="form.status">
<option value="todo">待开始</option>
<option value="doing">进行中</option>
<option value="done">已完成</option>
</select>
</label>
<label>实际进度（%）<input v-model.number="form.progress" type="number" min="0" max="100" step="1" required>
</label>
<label>剩余工时（小时）<input v-model.number="form.remaining_hours" type="number" min="0" step="0.5" required>
</label>
</div>
<label>成果链接<input v-model="form.artifact_url" placeholder="https://... 或上传后使用附件链接">
</label>
<label>当前阻碍<textarea v-model="form.blocker" rows="2" placeholder="说明影响推进的问题，解除后可清空">
</textarea>
</label>
</template>
