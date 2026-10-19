// 工作台只汇总当前项目的已加载数据，不改写任务或阶段状态。
export function buildWorkbench({ userId, tasks = [], cards = [], stages = [], submissions = [] }) {
  const myTasks = tasks.filter(task => task.assignee_id === userId)
  const activeTasks = myTasks.filter(task => task.status !== 'done')
  const blocked = task => Boolean(task.blocker?.trim() || task.planning_risks?.length)
  const nextTask = [...activeTasks].sort((a, b) =>
    Number(blocked(b)) - Number(blocked(a)) ||
    (a.due_date || '9999-12-31').localeCompare(b.due_date || '9999-12-31') || a.id - b.id
  )[0] || null
  const stageItems = stages.map((stage, index) => {
    const submission = submissions.filter(item => item.stage_index === index)
      .reduce((latest, item) => !latest || item.version > latest.version ? item : latest, null)
    return { index, stage, submission, status: submission?.status || 'unsubmitted' }
  })
  return {
    myTasks,
    activeTasks,
    nextTask,
    teamTasks: tasks.filter(task => task.assignee_id !== userId && task.status !== 'done'),
    pendingCards: cards.filter(card => ['pending', 'ready'].includes(card.status)),
    stageItems,
    nextStage: stageItems.find(item => item.status !== 'passed') || null,
  }
}
