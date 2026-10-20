# P1：学生仪表盘与交互可视化实现计划

> **面向 AI 代理的工作者：** 使用 subagent-driven-development 或 executing-plans 逐任务实现；P0退出检查通过后开始。本批全部功能当前待开发。

**目标：** 提供个人和团队两类行动入口，将任务、负荷、排期、需求、风险和历史趋势连接到具体业务操作。

**架构：** 服务端提供统一统计和对象集合，前端只组织展示与交互。共用筛选状态与任务下钻事件，ECharts封装在可替换组件内，甘特SVG复用真实计划快照。

**技术栈：** Vue 3、JavaScript、既有CSS、Apache ECharts 6.1.0、Node内置测试、现有Vue行为测试工具；不引入整套UI框架。

---

覆盖VIS-01—VIS-07、VIS-09基础和UX-01；VIS-08及待互审/求助/实际工时由P2补入同一面板，不另复制页面。

## 文件职责

| 创建/修改 | 路径 | 职责 |
| --- | --- | --- |
| 创建 | `frontend/src/analytics/filters.js`、`drilldown.js`、`chartOptions.js`、`chartController.js` | 筛选序列化、对象跳转、图表配置和生命周期 |
| 创建 | `frontend/src/components/charts/AnalyticsChart.vue`、`ChartDataTable.vue`、`TaskGantt.vue` | 标准图表、对应数据表、任务与依赖SVG |
| 创建 | `frontend/src/components/analytics/MetricCard.vue`、`RiskList.vue`、`RequirementMatrix.vue`、`TrendPanel.vue` | 有口径/空态/下钻入口的分析组件 |
| 创建 | `frontend/src/views/DashboardView.vue`、`ActivityView.vue` | 团队驾驶舱和事件时间线 |
| 修改 | `frontend/src/views/HomeView.vue`、`PlansView.vue`、`TasksView.vue`、`StagesView.vue` | 增强原入口，接收筛选/定位，不破坏已有任务编辑 |
| 修改 | `frontend/src/workspace.js`、`App.vue`、`styles/responsive.css` | 带scope的数据加载、角色导航和移动布局 |
| 修改 | `frontend/package.json`、`package-lock.json` | 精确增加echarts 6.1.0 |
| 创建 | `frontend/tests/chartController.test.mjs`、`studentAnalytics.test.mjs`、`dashboardViews.test.mjs`、`ganttNavigation.test.mjs` | 规则、生命周期、越权加载、交互及项目切换 |

## 任务1：图表组件与生命周期

计划实施时才执行依赖安装：

```bash
npm --prefix frontend install --save-exact echarts@6.1.0
```

按需注册LineChart、BarChart、PieChart、HeatmapChart、Grid/Tooltip/Legend/DataZoom/Aria组件及CanvasRenderer。甘特依赖线使用项目SVG；所有标准图表旁保留同口径数据表，不只提供颜色和鼠标悬浮。

- [ ] **步骤1：写失败测试。** 注入假的chart factory与ResizeObserver，断言容器尺寸变化会resize、组件卸载dispose、监听器解绑、项目切换后的旧点击被忽略。
- [ ] **步骤2：运行。** `node --test frontend/tests/chartController.test.mjs`，预期新控制器缺失导致失败。
- [ ] **步骤3：实现。** `createChartController({init, observeResize})`提供mount/update/dispose，组件只在挂载后初始化；隐藏页重新显示时调整尺寸，dispose后不再setOption。Tooltip对任务/成员文本使用安全文本模式，不拼接未转义HTML。
- [ ] **步骤4：验证。** 空数据、0、null、不足宽度和高对比/数据表模式可用；`npm --prefix frontend run build`通过且未全量引入无用图表。
- [ ] **步骤5：提交。** `feat(图表): 添加可释放且具数据表替代的图表组件`。

## 任务2：统一筛选与业务下钻

筛选值明确为`projectId/from/to/memberId/stageIndex/status/riskCode`，无值与全部是不同状态。日历日期保持服务器业务日，不受浏览器时区改变。

```javascript
// frontend/tests/studentAnalytics.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { drilldownTarget } from '../src/analytics/drilldown.js'

test('风险卡按当前项目及真实任务集合定位，不把图表文本当API路径', () => {
  const target = drilldownTarget({
    projectId: 1, type: 'risk', riskCode: 'overdue', taskIds: [11, 12],
  })
  assert.equal(target.tab, 'tasks')
  assert.deepEqual(target.filter.taskIds, [11, 12])
  assert.equal(target.filter.projectId, 1)
})
```

- [ ] **步骤1：扩展失败测试。** 连续切项目、取消请求、退出登录、请求乱序和过期图表点击都不能覆盖当前项目；重置筛选恢复明确范围。
- [ ] **步骤2：运行。** `node --test frontend/tests/studentAnalytics.test.mjs`，预期新映射与分析加载方法缺失。
- [ ] **步骤3：实现。** 新分析请求沿用workspace的epoch/scope保护，任务定位保存projectId及任务ID；TasksView打开当前项目抽屉。历史计划点击只读历史快照，不把旧任务编辑到当前版本。
- [ ] **步骤4：验证。** 卡片、饼图、热力格和列表使用相同ID集合；成员、阶段、日期筛选可组合；键盘操作可达且焦点有返回位置。
- [ ] **步骤5：提交。** `feat(分析): 贯通图表筛选与任务明细操作`。

## 任务3：个人面板和团队驾驶舱

个人首页保留当前“我的下一步”和本人任务，增加近期截止、本人阻碍、待核对草案和阶段提醒；P2未接入时不虚构“待我互审/求助”。团队驾驶舱包含状态分布、剩余工时、课程/需求覆盖、阶段状态和风险入口。

- [ ] **步骤1：写失败测试。** 同一项目中本人2项、他人3项时个人计数只得2；done不进待办；阶段旧退回/新通过采用新版本；教师不请求内部分析API。
- [ ] **步骤2：运行。** `node --test frontend/tests/dashboardViews.test.mjs frontend/tests/homeStages.test.mjs`，预期新增入口与行为失败，原首页测试继续作为回归。
- [ ] **步骤3：实现。** HomeView消费personal接口；DashboardView消费overview；每个数值带时间、筛选、单位/分母和解释。加载失败保留重试，不将错误值显示成0；新内部导航仅对学生可见。
- [ ] **步骤4：验证。** 空项目、未选项目、指标部分失败和刷新后更新；每张可行动卡都能到正确页面。原教师工作台及课程/项目公开概览保持原权限。
- [ ] **步骤5：提交。** `feat(学生端): 建设个人行动面板与团队驾驶舱`。

## 任务4：热力图、甘特与风险

- [ ] **步骤1：写失败测试。** 12h/8h格子显示超量4h，容量0不计算百分比；甘特跨月日期、任务依赖、阶段截止线和选中计划版本正确；规划风险与面板指向相同任务。
- [ ] **步骤2：运行。** `node --test frontend/tests/ganttNavigation.test.mjs frontend/tests/studentAnalytics.test.mjs`，预期新热力/依赖交互断言失败。
- [ ] **步骤3：实现。** 热力图按成员×周显示服务器allocated/capacity，旁有数值表。甘特支持日期缩放、负责人/阶段筛选、依赖高亮和点击定位；本批不通过拖拽直接改排期，修改回到组长计划表单并沿用确认。风险面板按规则列出逾期/依赖/容量/阶段及材料缺口。
- [ ] **步骤4：验证。** 长标题、重叠依赖、0任务、历史计划与当前进度不同、390px横向浏览和键盘列表替代；不能只以SVG坐标存在判通过。
- [ ] **步骤5：提交。** `feat(排期): 增加周负荷热力与可追踪甘特风险交互`。

## 任务5：需求矩阵与活动时间线

- [ ] **步骤1：写失败测试。** 草稿需求不计覆盖；一个需求对应多个任务不重复分母；任务全done的标签为“关联任务已完成”，不写“教师已验收”。活动列表稳定分页、无重复，隐藏原始Audit.detail及私有凭据字段。
- [ ] **步骤2：运行。** `node --test frontend/tests/dashboardViews.test.mjs`及`python -m pytest backend/tests/test_analytics_permissions.py -q`，预期新矩阵和时间线交互断言失败。
- [ ] **步骤3：实现。** Matrix列出课程功能、已确认需求、任务、成果、缺口；缺口点击精确对象。Timeline按白名单事件显示操作者/时间/对象/变更摘要，每页50项支持游标加载，不能原样输出整条审计JSON。
- [ ] **步骤4：验证。** 相同秒多个事件、任务改名、阶段退回重提、跨项目切换、学生/教师隔离及移动长文本；来源对象不可访问时显示权限提示，不泄漏正文。
- [ ] **步骤5：提交。** `feat(追踪): 增加需求覆盖矩阵与协作活动时间线`。

## 任务6：真实趋势与无障碍验收

- [ ] **步骤1：写失败测试。** 无采样数据是空态、两采样日之间缺失为null且不连线、范围增加有标记、切换基线不覆盖原观测；无工作日志时实际工时未知。
- [ ] **步骤2：运行。** `node --test frontend/tests/studentAnalytics.test.mjs frontend/tests/chartController.test.mjs`，预期新趋势配置断言失败。
- [ ] **步骤3：实现。** TrendPanel提供剩余工时燃尽、累计完成、每周新增/完成，并说明采集起点/缺口/基线。P2日志接口接入后增加实际与预计对比。图表支持数据表、可读标题、非纯颜色编码及减少动画偏好。
- [ ] **步骤4：完成实际验证。** 全部前端测试和生产构建通过；桌面/390px实际检查筛选、下钻、浮层、图表重排、键盘和屏幕可读数据表；入口不可用就保留浏览器待验状态。
- [ ] **步骤5：提交。** `feat(趋势): 展示真实进度历史与数据缺口`，写入本批版本、截图/日志范围和P1验收记录。

## P1退出检查

- [ ] VIS-01—VIS-07、VIS-09基础及UX-01有可操作入口，并能解释数据来源。
- [ ] 图表数值、筛选和下钻集合一致；日期、容量0、空态及缺口处理正确。
- [ ] 旧页面与教师流程保持可用，真实浏览器结果与组件测试分开记录。
- [ ] P2新增业务指标有明确接入位置，没有显示尚不存在的成果/工时记录。

技术依据：2026-10-19通过Context7核对[Apache ECharts按需导入](https://echarts.apache.org/handbook/en/basics/import/)、[容器尺寸与生命周期](https://echarts.apache.org/handbook/en/concepts/chart-size/)和[交互事件](https://echarts.apache.org/handbook/en/concepts/event/)。依赖安装和实现仅在本批实际启动后执行。
