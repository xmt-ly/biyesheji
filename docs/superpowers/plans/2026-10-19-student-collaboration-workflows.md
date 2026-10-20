# P2：学生协作业务深化实现计划

> **面向 AI 代理的工作者：** 使用 subagent-driven-development 或 executing-plans 逐任务实现；P0完成后开始，P1提供工作台和图表联动。本批功能均为待开发。

**目标：** 让普通成员持续参与交付、验收、求助、投入记录和复盘，形成可追溯的团队协作过程。

**架构：** 新业务表保存版本和状态转换，既有Task保留todo/doing/done和计划发布协议。业务服务在事务中检查角色、版本与幂等，追加P0事件，再使工作台与分析刷新。

**技术栈：** 现有FastAPI、SQLAlchemy、SQLite、Vue；沿用原文件下载和项目权限，不新建外部消息服务。

---

覆盖STU-01、STU-02、STU-03和VIS-08，并补全VIS-01、VIS-06、VIS-07、VIS-09的数据。

## 文件职责与持久化

| 创建/修改 | 路径 | 职责 |
| --- | --- | --- |
| 创建 | `backend/app/student_models.py`、`student_schemas.py` | ProjectCollaborationPolicy、TaskDelivery、DeliveryReview、SupportIssue、IssueEvent、WorkLog、WorkLogRevision、StudentReport |
| 创建 | `backend/app/services/__init__.py`、`deliveries.py`、`issues.py`、`worklogs.py`、`student_reports.py` | 状态转换、版本核对、日志和报告快照 |
| 创建 | `backend/app/routers/deliveries.py`、`issues.py`、`worklogs.py`、`student_reports.py` | 内部协作接口和本人操作 |
| 创建 | `backend/app/migrations/versions/v003_student_workflows.py` | 只增扩展表，不改旧任务状态枚举 |
| 修改 | `backend/app/routers/tasks.py`、`cards.py`、`files.py`、`main.py`、`analytics/metrics.py` | 所有完成入口的共同约束、文件引用、路由和数据接入 |
| 创建 | `frontend/src/views/DeliveriesView.vue`、`IssuesView.vue`、`WorklogsView.vue` | 交付、求助、本人工作记录入口 |
| 创建 | `frontend/src/components/DeliveryReview.vue`、`IssueDetails.vue`、`StudentReportEditor.vue` | 验收、解决确认和可核对复盘 |
| 修改 | `frontend/src/components/TaskDetails.vue`、`views/HomeView.vue`、`StagesView.vue`、`workspace.js`、`App.vue` | 复用任务、阶段与个人面板，不复制数据源 |
| 创建 | `backend/tests/test_student_deliveries.py`、`test_student_issues.py`、`test_student_worklogs.py`、`test_student_reports.py` | 状态、权限、旧数据与竞态 |
| 创建 | `frontend/tests/studentDeliveries.test.mjs`、`studentIssues.test.mjs`、`studentWorklogs.test.mjs`、`studentReports.test.mjs` | 对应用户操作、错误恢复和项目切换 |

所有新增关联均验证project_id，附件只引用本项目可访问文件。版本唯一键、幂等键与并发检查在服务端及数据库共同约束。

## 任务1：成果版本与验收清单

交付记录绑定task_id、version、提交者、说明、file_ids/artifact_urls、验收项快照、验收条件指纹、指定验收人、状态和时间。指纹覆盖任务ID、需求ID、验收条件、负责人；改负责人/需求/验收标准后旧通过不再批准新交付。日期变化保留历史，仍执行计划风险检查。

状态为`draft → submitted → approved/changes_requested`；作者可撤回尚未通过版本为withdrawn。退回后的重提必须建立更高version，已审核内容与意见不可覆盖。判断完成只看最大版本，不因新版本撤回而自动恢复旧通过。

- [ ] **步骤1：写失败测试。** 提交v1、退回、提交v2时v1附件/验收清单/意见保持原值；重复同一client_id只创建一个版本；并发创建不能重复version；跨项目附件拒绝。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_student_deliveries.py -q`，预期新模型/接口缺失失败。
- [ ] **步骤3：实现。** 增加v003迁移及`POST /api/tasks/{task_id}/deliveries`、`GET /api/tasks/{task_id}/deliveries`、`POST /api/deliveries/{id}/submit`；只允许当前负责人创建/提交，文件与链接沿用安全校验。提审不自动写100%、99%或实际工时，也不立即替换Task对教师可见的成果链接。
- [ ] **步骤4：前端验证。** 任务详情展示当前交付和版本列表；失败重试保持client_id，上传失败不丢说明。运行`node --test frontend/tests/studentDeliveries.test.mjs`，验证原任务评论/附件仍可用。
- [ ] **步骤5：提交。** `feat(交付): 保存成果版本与验收清单快照`。

## 任务2：同伴验收和完成约束

由组长配置项目`peer_review_required`，旧项目默认false；至少两名有效学生才能启用。未启用时可以保存交付草稿，submit接口返回409并提示先由组长启用，任务沿用原成果/完成流程。已完成的旧任务保留历史完成状态，启用后尚未完成任务的所有置done入口必须验证最新交付通过。互审人是本项目另一名有效学生，提交者不能自审；教师不进入该内部验收流程。

接口：`POST /api/deliveries/{id}/reviews`接收`decision=approve/request_changes`、验收项结果、意见、expected_version和client_id。退回必须有意见；通过要求必检项全部通过。

- [ ] **步骤1：写失败测试。** 自审403、另一组403、教师403、旧版本409、重复审核幂等、两名验收者竞态仅一个有效结果；提审后验收标准改变使审核失效。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_student_deliveries.py -k review -q`，预期新互审约束断言失败。
- [ ] **步骤3：实现统一完成守卫。** 手动PATCH、手工创建done任务及草案发布统一调用完成检查。互审通过时原子更新done/100%/remaining0、有效成果链接及事件；退回保留任务原进度，由成员填写新的剩余工作。已完成任务改验收基准时要求组长给原因并重新打开后提审，不能沿用旧批准。
- [ ] **步骤4：贯通工作台。** “待我验收”只统计指定给本人的当前submitted版本；验收通过/退回后实时刷新。覆盖旧项目无需互审的原有完成路径、教师公开成果访问及未通过版本文件不可见。
- [ ] **步骤5：提交。** `feat(互审): 增加同伴验收与任务完成保护`。

## 任务3：求助接手、解决与重开

SupportIssue关联任务、发起者、可选指定协助人、问题、影响说明、状态、当前处理人、version和时间。状态：`open → accepted → in_progress → resolved → closed`；发起者可对resolved/closed带原因重开为open。无人接手而无需协助时，发起者可以带原因关闭，保留记录。

指定协助人时只有该成员可接手；未指定时其他有效学生可接手，先到者通过CAS确定。处理人给出解决说明，发起者确认关闭；组长代确认或更换协助人必须记录理由。求助操作不赋予修改他人任务排期的权限。

- [ ] **步骤1：写失败测试。** 双人同时接手只有一人成功；其他项目成员拒绝；非处理人不能报解决；无说明拒绝；重复关闭/重开可核对版本，旧操作409。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_student_issues.py -q`，预期新求助接口缺失。
- [ ] **步骤3：实现接口与状态表。** `POST/GET /api/projects/{id}/issues`、`GET /api/issues/{id}`及`accept/start/resolve/confirm/reopen/close`动作使用version、client_id和审计。旧Task.blocker不猜测来源；提供负责人确认后同步更新本人阻碍的入口，不自动覆盖其他未解决问题。Task.blocker可能进入公开项目进度，同步前明确可见范围，只保存本人确认的公开摘要，不原样复制私有求助正文、讨论或附件。
- [ ] **步骤4：验证使用流程。** IssuesView可从任务/风险卡发起并定位，展示“我发起/待我接手/我处理中/待我确认”。超时未处理在站内列表提示，不自动外发消息。`node --test frontend/tests/studentIssues.test.mjs`覆盖失败、重试和切换项目。
- [ ] **步骤5：提交。** `feat(求助): 实现成员协助与问题解决闭环`。

## 任务4：实际工作日志与可追溯修订

WorkLog身份记录归本人；WorkLogRevision保存业务日、分钟数、关联任务、类型own_task/support/review、完成内容和私人反思，以及修订原因与时间。已保存记录不物理抹除，作废和更正保留版本。每人每个业务日跨项目有效记录合计不超过1440分钟，不能填未来日期；这仍是本人填报，不是自动测得的真实劳动量。

详细日志及私人反思只对本人开放；本项目成员可看按人汇总工时和本人明确发布的摘要。阶段共享的报告是用户确认后另存的快照，不能通过更新个人日志改写旧阶段材料。

- [ ] **步骤1：写失败测试。** 90分钟显示1.5h；无记录为未知，不根据remaining变化倒推；本人可修订、他人/教师不可读私密正文或修改；0/负数/未来日期/日总量超限拒绝；旧报告引用旧日志版本仍可追踪。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_student_worklogs.py -q`，预期新数据模型缺失。
- [ ] **步骤3：实现。** `GET/POST /api/projects/{id}/worklogs/me`、`POST /api/worklogs/{id}/revisions`与`void`接口；同任务协助记录不改变负责人，统计只纳入有效最新日志。团队汇总只返回汇总值，不附内部备注。
- [ ] **步骤4：接入前端和图表。** 本人工作台提供快速记录，WorklogsView展示日期、任务、分钟及历史；趋势面板显示原估时/最新计划估时/填报实际值。`node --test frontend/tests/studentWorklogs.test.mjs`验证修订、隐私、空态及计数一致。
- [ ] **步骤5：提交。** `feat(日志): 增加实际投入记录与修订留痕`。

## 任务5：个人贡献证据与阶段复盘

StudentReport保存作者、项目、阶段/日期范围、引用记录ID及版本、生成依据、可编辑摘要、发布范围和版本。证据包括本人交付、协助解决、同伴验收、有效日志和公开计划变化；不按聊天条数或耗时生成能力排名。

- [ ] **步骤1：写失败测试。** 汇总只含所选项目/成员/阶段/日期；本人协助和主责交付分开；未确认草案不算成果；旧提交退回/新提交通过正确；私密正文不泄漏到团队或教师报告。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_student_reports.py -q`，预期新报告接口缺失。
- [ ] **步骤3：实现。** `POST /api/projects/{id}/student-reports`先生成可核对草案，`POST /api/student-reports/{id}/publish`由本人确认字段后存共享快照；只有明确附入原阶段提交流程的允许材料教师可见。P2先提供规则模板，AI润色留给P3。
- [ ] **步骤4：接入VIS-08。** 阶段复盘面板区分教师退回、同伴退回、任务延期和范围调整，按证据跳转；个人总结可编辑后保存，生成记录不能当本人已确认。`node --test frontend/tests/studentReports.test.mjs`验证范围与来源。
- [ ] **步骤5：提交。** `feat(复盘): 生成可核对的个人与阶段协作报告`。

## 任务6：联动与完整协作验收

- [ ] **步骤1：写联调失败场景。** 成员甲提交登录页v1，成员乙按清单退回；甲发起接口求助，乙接手解决，甲确认并记录90分钟；甲提交v2，乙通过；个人待办、风险、矩阵、事件和阶段报告分别更新。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_student_deliveries.py backend/tests/test_student_issues.py backend/tests/test_student_worklogs.py backend/tests/test_student_reports.py -q`，先确认新流程缺项的失败。
- [ ] **步骤3：补齐联动。** 各业务完成与P0事件、当天快照在同一事务提交；广播后前端刷新时沿用scope保护，不为新功能重建全部工作区状态逻辑。
- [ ] **步骤4：完整回归。** 原任务、聊天、计划发布、文件、教师阶段流程及Windows/Linux适用检查通过；桌面和390px执行上述场景，未有真实浏览器工具时明确缺口。提交和审核的重复请求不产生双任务或双版本。
- [ ] **步骤5：提交。** `test(协作): 验证交付求助日志与复盘贯通`，记录新表版本、数据使用范围和P2退出结果。

## P2退出检查

- [ ] 普通成员能完成提交、互审、求助、协助、记录和复盘的持续流程。
- [ ] STU-01—STU-03及VIS-08有独立验收，原仪表盘补齐对应待办与数值。
- [ ] 状态变更有权限、幂等、版本和事务保护，不能绕过验收完成任务。
- [ ] 个人私密日志、团队内部数据和教师公开材料的边界有API反例测试。
