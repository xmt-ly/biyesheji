# 课程项目智能协作系统实现计划

> 面向实现代理：按 subagent-driven-development 分任务实现，并在各模块后进行规格与质量审查；关键权限、约束和发布流程使用 test-driven-development。用户已授权在指定新项目目录开发，当前目录没有 Git 仓库。

## 目标、架构与技术栈

实现需求规格说明书中的 FR-01—FR-10，提供可启动的学生工作区与教师检查端、真实模型接入、可核验的演示数据及自动化测试。后端采用现有 Python 3.12 环境、FastAPI、SQLAlchemy 2 与 SQLite，前端使用 Vue 3、JavaScript 和 Vite。单后端进程维护 WebSocket 连接与项目级 Agent 调度，消息、运行状态、计划及阶段快照持久化；数据库文件默认放在项目 data 目录。

模型通过 AsyncOpenAI 接入 OpenAI 兼容云端接口，三个参数 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL 从服务端项目配置读取。未配置时业务与聊天可运行，并明确显示 AI 未配置；不能用规则生成的内容冒充模型分析。模型具备读项目上下文、查询任务、检查完整计划的工具，循环次数和调用时间有界。

## 任务 1：后端与关键测试

文件范围为 backend/、backend/tests/ 和 backend/requirements.txt。按配置、数据模型、身份权限、业务路由、规划检查、消息广播、Agent 接入和演示初始化分模块。

- [x] 先写登录、项目隔离、教师不能访问聊天室、普通成员不能发布计划、循环依赖、成员容量、发布幂等与过期草案测试。
- [x] 使用指定 Python 执行测试，确认未实现行为失败，再实现最小业务与权限逻辑。
- [x] 提供下述接口，返回 Pydantic 验证后的 JSON；字段与接口实际定义保存到 docs/API.md。
- [x] 实现云端模型工具调用及项目级自动分析；以测试替身验证错误恢复、持续输入、公平调度和过期建议，真实接口凭据不入库、不输出。
- [x] 演示初始化只在空数据库显式执行，不在服务启动时自动植入业务数据。
- [x] 运行后端测试并进行规格审查，再进行代码质量审查，修复查出的具体问题。

## 接口约定

所有业务接口位于 /api，登录后使用 Bearer token；WebSocket 可用短期登录 token 建立项目连接，日志不记录 token。

| 接口 | 行为 |
| --- | --- |
| POST /api/auth/login；GET /api/auth/me | 用户名、密码登录；查询当前身份 |
| GET/POST /api/courses；PATCH /api/courses/{id} | 发布教师管理课程任务，学生查看已发布任务 |
| GET/POST /api/projects；GET /api/projects/{id} | 项目列表、创建与结构化详情，教师详情不包含聊天与内部卡片 |
| POST /api/projects/{id}/members；PATCH /api/projects/{id}/members/me | 组长邀请成员；本人更新技能和周容量 |
| GET/POST /api/projects/{id}/requirements；PATCH /api/requirements/{id} | 需求建议、组长确认和需求修改 |
| GET/POST /api/projects/{id}/tasks；PATCH /api/tasks/{id} | 任务和进度，分工排期修改由组长控制 |
| GET/POST /api/tasks/{id}/comments | 协作评论、阻碍和成果链接 |
| GET/POST /api/projects/{id}/messages；WS /api/projects/{id}/ws | 历史消息、幂等发送、实时广播和重连 |
| GET /api/projects/{id}/cards；POST /api/projects/{id}/agent/analyze | 项目内部卡片；显式重试、初始规划或延期调整入口 |
| PATCH /api/cards/{id}；POST /api/cards/{id}/feedback | 草案编辑、成员核对、拒绝；修改后重新检查约束 |
| POST /api/cards/{id}/publish | 组长核对后事务发布；重复确认幂等、旧版本拒绝 |
| GET /api/projects/{id}/plans | 历史快照与计划变更，可比较版本 |
| GET/POST /api/projects/{id}/submissions；POST /api/submissions/{id}/review | 阶段材料及历史，教师审核并保留意见 |
| POST /api/projects/{id}/files；GET /api/files/{id} | 项目附件上传与鉴权下载 |
| GET /api/health；GET /api/config/status | 健康检查、仅返回模型配置是否就绪和非敏感状态 |

统一实体使用整数 id、ISO 日期和时刻。课程包含 acceptance_criteria 验收标准和长度为 3 的 stages 列表，阶段字段为 name、deadline、deliverables。项目包含 course_id、name、description、status、revision、role、members。任务包含 title、description、requirement_id、acceptance、assignee_id、estimated_hours、remaining_hours、dependencies、start_date、due_date、status。成员 weekly_hours 是当前项目每周容量，skills 为字符串列表。进度反馈保存实际数据并展示规划风险；规划修改才执行硬约束拒绝。

消息包含 id、project_id、user_id、sender_name、kind、content、created_at、client_id、related_type、related_id。卡片包含 id、kind、title、summary、questions、source_message_ids、tasks、checks、status、base_revision、feedback、created_at。卡片任务用稳定 key 区分新任务，existing_id 标识调整的原任务，dependencies 引用任务 key，不能跨项目引用。发布接口返回发布结果及计划版本。实时事件使用 type 为 message、cards_changed、project_changed、agent_status 的 JSON。

## 任务 2：前端工作区

文件范围为 frontend/。后端通过首任务提供的实际 docs/API.md 校对契约。

- [x] 实现 JavaScript API 客户端、登录、身份路由、统一错误与空状态。
- [x] 学生项目首页显示本人任务、项目状态和待核对事项；项目工作区提供讨论、需求、任务、计划与阶段成果。
- [x] 聊天区显示连接状态、消息来源和 Agent 追问，右侧分析卡片支持来源定位、反馈、编辑、检查与组长发布。
- [x] 任务看板和表单支持本人进度、工时、阻碍、成果链接与附件；计划页面显示依赖、时间及版本差异。
- [x] 教师端提供课程任务编辑、项目进度及三阶段提交审核，界面不提供聊天室入口。
- [x] 用组件与客户端行为测试验证错误状态、消息去重、权限按钮和草案确认逻辑；运行 npm build。
- [x] 完成规格与质量审查后修复问题，避免将后端错误当作空列表或成功提示。

## 任务 3：运行、演示和集成验证

文件范围为 README.md、scripts/ 和 docs/启动与演示说明.md。

- [x] 提供使用 face_env 的 PowerShell 后端、前端开发和生产演示启动方式；依赖锁定及 .env.example 保留空凭据。
- [x] 显式创建一名教师、两个隔离团队和可用任务，演示账号与样例数据标注用途。
- [x] 提供模型配置说明、SQLite 备份恢复说明及模型未配置时的真实状态说明。
- [x] 运行后端完整测试、前端测试与构建；本机多账号检查教师隔离、聊天室及任务更新。
- [x] 保存实际测试输出、验收覆盖与已知限制；截图和演示脚本使用实际页面和数据。

## 完成条件

前后端均能由文档中的命令启动；真实接口未配置时清楚提示且人工流程可使用。自动化验证覆盖关键权限、约束、幂等、历史及模型异常；实际构建与测试通过后才报告对应结果。论文、付费模型实验及正式学校格式在代码可运行后使用实际材料开展，本次不预设实验性能改善。


## 本阶段验证结果（2026-10-11）

后端 68 项、前端 25 项、备份 3 项测试通过；前端生产构建成功。本机 API 验收 15/15，实际双账号聊天、成员进度、草案反馈与发布、计划对比、教师修改与重提审核已验证，备份恢复到新目录验证通过。独立规格/质量审查已闭环。真实云模型、对比实验与论文尚待后续完成；详见 docs/测试与验收记录.md。
