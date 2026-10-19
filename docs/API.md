# 后端 API 契约

版本：1.0.0。基础路径 `/api`，JSON 请求使用 `Content-Type: application/json`。除登录和健康检查外使用 `Authorization: Bearer <access_token>`。ID 为整数；日期为 `YYYY-MM-DD`；时间为 UTC ISO 8601，界面按 `Asia/Shanghai` 展示。成功请求通常返回 200，Agent 排队返回 202；无登录 401、无权限 403、不存在 404、旧版本/不允许状态变更 409、输入或规划冲突 422、附件过大 413、AI 未配置 503。

所有列表直接返回数组。错误体是 `{"detail":"中文提示"}`，字段校验时 `detail` 为包含 `loc/msg/type` 的数组，规划校验时 `detail` 为检查结果对象。所有请求拒绝未声明字段；PATCH 未传字段保持原值，显式 `null` 不接受。路径和资源引用 ID 范围为 1–9223372036854775807，越界返回 422；消息游标 after_id 另外允许 0。无效或越界 JWT sub 返回 401。模型凭据不会通过 API 返回。

## 1. 启动、数据和模型配置

从 `backend/` 启动 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log`。首次使用显式执行 `python -m app.seed`，正常启动不自动初始化演示账号。默认数据库和附件在项目根 `data/`，测试可使用 `create_app(Settings(database_url=..., data_dir=...), provider=...)` 注入独立数据库与外部模型测试替身。生产前端 `frontend/dist` 已存在时自动提供静态页面，未定义的 `/api/*` 保持 404。

配置只读取当前服务进程中的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，不读取其他项目的密钥或全局 `OPENAI_API_KEY`。示例地址带 `/v1`。模型使用真实 `AsyncOpenAI`、Chat Completions 和工具调用，最多六轮，每轮最多五个工具，默认模型分析总超时 60 秒。工具请求不叠加 JSON 输出模式，最终内容仍按 JSON 解析，并通过 Pydantic、来源与项目引用校验；无效输出不生效。新运行标记提示协议版本 `v2-tools`，历史记录保持原标签。没有密钥或模型时人工功能照常可用，显式分析返回 503。默认使用随机持久化的 `data/jwt.key`，也可设置至少 32 字符的 `JWT_SECRET`。

`GET /health` 无需登录，返回 `{"status":"ok"}`。`GET /config/status` 返回：

```json
{"ai_ready":false,"ai_status":"not_configured","storage":"sqlite","realtime":"single_process","demo_data":true}
```

AI 就绪只表示配置齐全，不能保证供应商接口此刻可用。该初版必须单进程运行；使用多 worker 需要替换广播与项目 worker 协调存储。

## 2. 登录与演示账号

`POST /auth/login`：

```json
{"username":"leader","password":"Demo2026!"}
```

响应：

```json
{"access_token":"<JWT>","token_type":"bearer","user":{"id":2,"username":"leader","name":"一组组长","identity":"student"}}
```

`GET /auth/me` 返回同样的 user 对象。令牌默认 12 小时有效。演示账号为 `teacher`、`leader`、`member1`、`member2`、`leader2`、`member3`，密码均为 `Demo2026!`。一组包含前三名学生，二组包含后两名学生；演示数据在课程、项目名称及初始计划中明确标注。

## 3. 课程

`GET /courses`：教师仅自己课程；学生仅已发布课程。`GET /courses/{id}` 同样校验。`POST /courses` 仅教师创建；`PATCH /courses/{id}` 仅所属教师维护，支持下列字段的子集：

```json
{
  "title":"软件工程课程项目","description":"团队完成课程协作系统",
  "acceptance_criteria":"必做功能、权限、测试、文档和演示均通过课程验收",
  "required_features":["账号权限","协作工作区"],"optional_features":["智能助手"],"references":[],
  "status":"published",
  "stages":[
    {"name":"需求与计划检查","deadline":"2026-10-25","deliverables":["需求清单与开发计划"]},
    {"name":"开发中期检查","deadline":"2026-11-15","deliverables":["中期成果与调整说明"]},
    {"name":"最终验收","deadline":"2026-12-06","deliverables":["代码、报告、测试与演示材料"]}
  ]
}
```

返回以上字段，加 `id, teacher_id, version, history`。状态 `draft/published/archived`。草稿允许未填写阶段与 acceptance_criteria；填写阶段时必须三个且日期严格递增。发布要求说明、非空课程验收标准、必做功能、三个阶段及每阶段交付物。课程一经 published 或 archived 后不能退回 draft，返回 409 且整个 PATCH 不写入；仍可维护公开要求、归档或再次公开。课程修改保存旧版快照并递增 version，同时递增相关项目 revision 并失效未发布草案。学生 history 只含曾经发布的版本，教师未发布草稿不会通过课程历史泄露。项目上下文、规划与 Agent 工具共用公开课程校验；历史非法关联未发布课程的项目也不能泄露私有课程内容。已归档项目使用之前公开的课程要求。

## 4. 项目和成员

`GET /projects` 按用户权限返回项目；`GET /projects/{id}` 返回单项目。学生 `POST /projects`：

```json
{"course_id":1,"name":"我们的小组项目","description":"课程开发项目"}
```

创建者成为该项目组长。`PATCH /projects/{id}` 仅本项目组长，接受 `name, description, status`；status 为 `preparing/active/archived`。项目返回：

```json
{"id":1,"course_id":1,"name":"示例","description":"说明","status":"active","revision":1,
 "created_at":"2026-10-11T00:00:00+00:00","role":"leader",
 "members":[{"user_id":2,"username":"leader","name":"组长","role":"leader","skills":["Python"],"weekly_hours":12}]}
```

`POST /projects/{id}/members` 仅组长，`{"username":"member1"}`，已加入时幂等返回 member。`PATCH /projects/{id}/members/me` 仅更新本人：`{"skills":["Python","Vue"],"weekly_hours":12}`。容量范围 0–168 小时。组长权限按当前项目成员关系判断，另一个项目的组长不会获得此项目组长权限。

`GET /projects/{id}/progress` 返回 `total, done, completion_percent, calculation, tasks, planning_checks`。完成比例是本项目完成任务数占全部任务数，不能作为功能验收或成员贡献分数。planning_checks 是当前完整项目的实时规划风险，和历史计划快照分别保留。

## 5. 需求

`GET /projects/{id}/requirements`，教师仅看到已确认需求。`POST /projects/{id}/requirements` 成员提出，组长可直接确认：

```json
{"title":"登录和项目权限","description":"按团队隔离业务数据","acceptance":"跨组访问被拒绝",
 "course_feature":"账号权限","priority":"must","status":"draft"}
```

返回以上字段加 `id, project_id, creator_id, created_at`。priority 为 `must/should/could`；status 为 `draft/confirmed`。`course_feature` 可省略或空字符串；非空必须来自本课程必做或选做功能。规划检查时，课程必做功能须关联到已确认需求，再关联到任务；未填写 course_feature 时允许需求 title 与课程功能完全同名。

`PATCH /requirements/{id}` 支持上述字段子集。普通成员只能修改本人未确认需求；组长确认和维护需求。每次业务变更递增项目 revision。

## 6. 任务、评论与成果

`GET /projects/{id}/tasks`；`POST /projects/{id}/tasks` 组长手工创建：

```json
{"title":"实现登录","description":"完成登录接口","requirement_id":1,"acceptance":"登录与权限测试通过",
 "assignee_id":3,"estimated_hours":6,"remaining_hours":6,"dependencies":[],
 "start_date":"2026-10-12","due_date":"2026-10-16","stage_index":0,
 "status":"todo","progress":0,"artifact_url":"","blocker":""}
```

返回以上字段加 `id, key:"task_<id>", project_id, creator_id, created_at, updated_at, planning_risks`。stage_index 可省略，默认最终验收阶段 2。status 为 `todo/doing/done`。工时为有限非负数；进度 0–100。依赖使用本项目任务整数 ID。GET tasks/progress 使用当前课程、需求、成员容量及完整任务集合重算一次风险；成员容量恢复后不再返回旧容量冲突。历史计划和阶段提交仍保留当时的快照。

`PATCH /tasks/{id}` 支持上述字段子集。普通成员只能更新本人任务的 `status, progress, remaining_hours, artifact_url, blocker`。实际进度、剩余工时与阻碍必须能保存，即使现有计划已超容量；响应中的 planning_risks 明确显示冲突，并触发后台 adjust 分析，不需先发聊天消息。新建任务或修改规划字段仍硬性检查约束。组长可维护全部任务规划字段。状态 done 自动归一化为 progress=100、remaining_hours=0；已完成任务的纠正须由组长额外提供 `correction_reason`，保存审计历史，Agent 草案始终不能修改已完成任务。任务创建与规划字段调整会同步建立人工计划快照；普通进度更新不新增排期版本，但递增业务 revision。

`GET /tasks/{id}/comments` 和 `POST /tasks/{id}/comments` 仅项目学生成员：

```json
{"kind":"blocker","content":"依赖接口尚未完成，请协助确认"}
```

kind 为 `comment/blocker/artifact`。响应含 `id, task_id, user_id, author_name, kind, content, created_at`。评论用于协作记录，持久化 blocker 字段或成果仍需本人任务 PATCH。

## 7. 消息与 WebSocket

`GET /projects/{id}/messages?after_id=0&limit=200` 返回按 id 升序的持久化消息。limit 范围 1–500；重连后逐页读取，直到小于 limit。教师和其他团队无法访问。

`POST /projects/{id}/messages`：

```json
{"content":"我来完成登录接口，预计 6 小时。","client_id":"browser-generated-uuid",
 "related_type":"task","related_id":1,"supersedes_card_ids":[]}
```

related_type/related_id 可同时省略；类型 `task/requirement/card`，必须引用本项目资源。supersedes_card_ids 可省略，用于明确更正本项目旧建议，未发布旧卡片会被标为 stale。client_id 在项目+用户范围幂等，重复发送返回原消息且不重复创建分析意图。消息、更正记录与分析意图在同一事务中持久化，提交后只唤醒后台 worker 并广播；广播中断不丢失待处理分析，等待模型不阻塞人类消息。

Message 响应：

```json
{"id":1,"project_id":1,"user_id":2,"sender_name":"一组组长","kind":"human","content":"讨论内容",
 "created_at":"2026-10-11T00:00:00+00:00","client_id":"browser-generated-uuid","related_type":"task","related_id":1}
```

Agent 消息 kind 为 agent、user_id 和 client_id 为 null。WebSocket 地址 `ws://127.0.0.1:8000/api/projects/1/ws?token=<JWT>`，仅本项目学生成员，未授权连接以 1008 关闭。可发送 `{"type":"ping"}` 得到 pong，发送聊天仍用 HTTP 接口。

事件：`{"type":"message","message":<Message>}`、`{"type":"cards_changed"}`、`{"type":"project_changed"}`、`{"type":"agent_status","status":"analyzing|completed|failed","run_id":1,"message":"失败时的安全提示"}`。成员关系和令牌有效期在每次广播与客户端输入时复核。

## 8. Agent、草案和发布

`POST /projects/{id}/agent/analyze`：`{"mode":"discussion"}`，mode 为 `discussion/plan/adjust`，返回 202 `{"status":"queued","mode":"discussion"}`。一个项目只运行一个 worker；默认静默约 3 秒、最多 15 秒合并输入。消息游标与 AgentIntent 待处理意图分别持久保存，意图记录 mode/requested/status/消息边界。无聊天消息的显式 plan/adjust 与实际进度触发也可恢复：quiet 期间 queued 不丢失，running 中断重新 queued，分析中的新 pending 记录不被前一轮完成吞掉。重启按最新项目数据分析，聚合时采用最近显式或业务模式。成功分析保留消息游标和意图完成检查点；失败保留未处理输入与 failed 意图，等待显式重试或新的业务输入，启动不会无限自动调用模型重试。AI 未配置时人工业务触发的意图也保存，配置后启动可处理。模型输出必须通过 Pydantic 和消息/资源作用域检查，失败写入安全错误卡片，保留已有任务和计划。

任务实际更新与 adjust 意图共享同一数据库事务，显式分析请求也先提交意图再唤醒。业务提交后、首次广播前发生取消或停机时，已保存意图仍可恢复，不依赖之后的通知步骤。worker 完成检查点提交后若仅广播被取消，完成状态不会反向改成未处理。

`GET /projects/{id}/agent/runs` 仅项目学生，返回最近 50 次运行的 `id, project_id, base_revision, source_message_ids, mode, intent_ids, model, prompt_version, status, error, elapsed_ms, tokens, tool_results, created_at`。intent_ids 指向该轮合并处理的持久意图；用量未知返回 null。教师禁止读取。

`GET /projects/{id}/cards` 返回内部卡片。`POST /projects/{id}/cards` 允许学生创建明确标注 creator_id 的人工草案，无需 AI 配置：

```json
{"kind":"plan","title":"人工排期草案","summary":"团队核对排期","questions":[],"source_message_ids":[],
 "tasks":[{"key":"new_login","existing_id":null,"title":"登录接口","description":"接口实现",
 "requirement_id":1,"acceptance":"测试通过","assignee_id":3,"estimated_hours":6,"remaining_hours":6,
 "dependencies":[],"start_date":"2026-10-12","due_date":"2026-10-16","stage_index":0,
 "status":"todo","progress":0,"artifact_url":"","blocker":""}]}
```

草案 key 稳定且不可重复。现有任务使用 `key:"task_1", existing_id:1`；新任务 key 不得以 task_ 开头。dependencies 是 key 字符串数组，可引用同草案新任务或已有 task_1。POST、PATCH 和工具一次变更最多 300 项任务；依赖最多 200 项、key 最长 80 字符、问题最多 100 项且每项最长 2000 字符、消息来源最多 200 项。草案是变更列表，检查与发布都会叠加全部现有任务，不删除未提到的任务；依赖使用迭代检查，已有长链不会受 Python 递归栈限制。任务开始与结束跨度最多 3660 天，日历上限 date.max 与最后不完整周也安全处理。来源只允许本项目真实人类消息。

Card 返回 `id, project_id, kind, title, summary, questions, source_message_ids, supersedes_card_ids, tasks, checks, status, base_revision, feedback, creator_id, created_at, published_plan_id`。kind 为 discussion/plan/adjust，status 为 pending/ready/published/rejected/stale/failed。更正关系保存在 supersedes_card_ids 和旧卡 feedback 中，指向更正消息或新卡，服务重启后仍可追溯。消息历史也返回 supersedes_card_ids。

检查结果示例：

```json
{"valid":false,"violations":[{"code":"weekly_capacity","message":"该成员当周剩余工作量超过所填容量",
 "task_keys":["task_1"],"user_id":3,"week":"2026-10-12","allocated_hours":18,"capacity_hours":12}],
 "calculation":"剩余工时按任务日期范围内的周一至周五均匀分配到各周；纯周末任务计入开始日所在周；已完成任务不占容量"}
```

其他 code 包括 requirement_coverage、course_feature_coverage、invalid_requirement、invalid_assignee、invalid_hours、date_order、invalid_date、invalid_dependency、dependency_cycle、dependency_time、stage_deadline、completed_task、duplicate_key。前置任务未完成时，其截止日须早于后续任务开始日。

`PATCH /cards/{id}` 支持 `title, summary, questions, tasks, status:"rejected", reason`。已发布/已拒绝草案不可直接改写。编辑会清除旧反馈中的 confirmed 标记并记录失效时间。失效草案重新核对须填写 reason，操作记录当前 revision，再重新检查；原反馈和修改轨迹保留。成员可以编辑草案与反馈，但不能发布。Agent 捕获卡片内容、状态和反馈指纹，仅能失效尚未更新的同一快照；旧项目 revision 或中途编辑/反馈的卡片不会被旧模型结果覆盖。

`POST /cards/{id}/feedback`：`{"content":"我确认这个分工和工时","confirmed":true}`，追加姓名、用户与时间。`POST /cards/{id}/publish` 无请求体，只允许本项目组长。该操作代表组长在查看团队反馈后做出的最终人工确认，服务端不强制每位成员逐一 confirmed。必须没有未解决 questions、存在 tasks、所有约束通过且 base_revision 等于当前 revision。发布时再次校验并通过 CAS，在同一事务中映射新 task key 为整数 ID、更新任务、保存计划与变更，失败全部回滚。重复发布返回原计划；其他旧草案变 stale。

`GET /projects/{id}/plans` 学生与所属教师可读，按 version 升序。Plan 返回 `id, project_id, version, created_at, created_by, summary, tasks, changes`；tasks 是发布当时完整快照；changes 包含 task_id/action/before/after。新版本 tasks 与变更 before/after 中的规划风险按发布时真实课程、成员容量和任务重算，旧版历史不会重写。教师计划响应不包含卡片正文、消息来源或原始运行记录。

## 9. 阶段材料与审核

`GET /projects/{id}/submissions` 所属学生及教师读取全部历史版本。`POST /projects/{id}/submissions` 仅组长：

```json
{"stage_index":0,"summary":"第一阶段需求和计划已整理","artifact_urls":["https://example.com/report"],
 "file_ids":[1],"materials":{"需求清单与开发计划":["https://example.com/report","file:1"]}}
```

stage_index 为 0–2。至少一个成果链接或本项目已上传附件；材料引用只能来自本次 artifact_urls 或 file:<id>。课程某阶段只有一项交付物时可省略 materials，服务端自动映射；多项交付物须逐项映射，缺项返回 422。每次提交创建新 version，保留 plan_version、结构化 progress_snapshot 和全部历史审核，不覆盖旧材料。

返回上述字段，加 `id, project_id, version, status, created_at, created_by, plan_version, progress_snapshot, reviews`。status 为 pending/passed/needs_changes。

`POST /submissions/{id}/review` 仅所属课程教师：

```json
{"result":"needs_changes","comment":"请补充权限测试记录"}
```

result 为 passed/needs_changes；评论必填。追加 `reviewer_id, reviewer_name, result, comment, created_at`。审核不自动完成开发任务，修改后重新提交仍能查看旧版本和意见。

## 10. 文件

`GET /projects/{id}/files` 仅本项目学生成员，返回本项目全部已上传文件 metadata 数组，便于组长选择成员材料用于阶段提交。响应不含磁盘 storage_name；教师禁止读取内部附件目录。

`POST /projects/{id}/files` 使用 multipart 字段 `file`，仅项目学生成员；返回 `id, project_id, user_id, filename, content_type, size, created_at`。默认上限 20 MiB。扩展名白名单：txt/md/pdf/docx/xlsx/csv/png/jpg/jpeg/webp/zip/py/js/html/css/json/pptx。原名仅存 metadata，实际磁盘文件使用 UUID，返回下载以 attachment/octet-stream 防止 HTML 执行，不允许路径遍历。

`GET /files/{id}` 使用 Bearer 下载二进制；`GET /files/{id}/metadata` 返回上述 metadata。学生须当前项目成员。教师须负责该项目课程，且附件已关联该项目某个阶段提交；教师不能猜 ID 下载未提交的聊天室或任务私有附件。跨项目附件和提交引用均拒绝。

## 11. 前端实施要点

1. 登录后从 `/auth/me` 和 `/projects` 判断身份及当前项目 role，按钮权限仍由服务端再次校验。
2. 学生加载 requirements/tasks/messages/cards/plans/submissions；教师加载 courses/projects/progress/tasks/plans/submissions，不请求内部 messages/cards/runs/comments。
3. 发送消息生成新 client_id；失败重试复用同一 client_id，收到 HTTP 响应和 WebSocket 同 ID 合并。
4. WebSocket 重连先拉 `after_id` 补漏；收到 cards_changed/project_changed 后重拉相关资源。
5. AI 未配置时显示服务端状态并保留人工聊天、需求、任务和手工草案；不使用预制分析伪装模型结果。
6. 创建/编辑草案使用完整 draft task 字段，已有任务保留 key、existing_id 和 stage_index；更新任务引用使用整数 ID，草案依赖使用 key。
7. 分页历史、计划快照、阶段版本及审核意见均来自持久化 API；不能在前端覆盖或模拟历史。

## 12. 初版限制

SQLite + 单进程内存广播；大规模部署需要数据库迁移、共享广播及分布式 worker。账号初始化通过显式演示 CLI，无自助注册与账号管理界面。上传使用扩展名和大小约束，没有在线病毒扫描。课程日期可设置与变更，Agent 不能修改教师截止日。容量按日期范围均摊计算，不读取个人跨项目日程。真实模型输出质量、提供商兼容性及费用需使用用户的服务端配置进行在线验收；当前自动测试只在外部提供者边界注入受控替身。


## 2026 年 10 月 18 日 Agent 行为补充

本次未改变公共请求或卡片字段。新增任务负责人、工时和日期缺少可核对来源时，分析可能返回 tasks 为空及具体问题；成员补充后可再分析。finalize_analysis 与 task_evidence 仅用于服务端模型交互，不是可供前端绕过确认的发布 API。组长发布仍受原权限、修订号和约束校验保护。
