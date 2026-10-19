# 课程项目智能协作系统

面向学生课程项目团队的本科毕业设计。学生在项目工作区维护需求、推进任务、讨论问题和提交阶段成果；教师发布课程任务、查看公开进度并审核三个阶段。Agent 根据小组讨论和项目数据生成分析与计划草案，由组长确认后发布。

技术栈为 Python 3.12、FastAPI、SQLAlchemy、SQLite、Vue 3、JavaScript 和 Vite。初版采用单进程服务，数据库与附件持久化在本项目内。

## 快速启动

在 PowerShell 中运行：

```powershell
Set-Location D:\DevelopTools\biyesheji
& D:\Anaconda3\envs\face_env\python.exe -m pip install -r .\backend\requirements.txt
& .\scripts\Run-Demo.ps1 -DisableAI
```

打开 <http://127.0.0.1:8000>。`Run-Demo.ps1` 构建前端、显式初始化演示数据并启动后端，首次构建需要 npm 下载依赖。按 `Ctrl+C` 停止服务。若本机 PowerShell 阻止脚本执行，可以只为本次进程运行 `Set-ExecutionPolicy -Scope Process Bypass` 后重试。

后续数据已经初始化时，直接运行 `& .\scripts\Start-Backend.ps1`。请勿用演示初始化替代业务数据迁移。

| 演示身份 | 用户名 | 密码 |
| --- | --- | --- |
| 教师 | `teacher` | `Demo2026!` |
| 一组组长 | `leader` | `Demo2026!` |
| 一组成员 | `member1`、`member2` | `Demo2026!` |
| 二组组长 | `leader2` | `Demo2026!` |
| 二组成员 | `member3` | `Demo2026!` |

演示数据明确标注用途，两组项目数据相互隔离。不同账号可以使用不同浏览器标签页登录。

## 接入模型

根目录没有 `.env` 时，从 `.env.example` 创建；已有配置直接编辑，避免覆盖密钥。在本机填写 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。服务支持 OpenAI 兼容的 Chat Completions 与工具调用；服务地址通常包含 `/v1`，模型名称按供应商实际配置。填写后重启后端，不传 `-DisableAI`。

配置由启动脚本加载，密钥仅在服务端使用。配置齐全只表示可以尝试调用，实际兼容性和可用性需连接供应商验证。未配置或调用失败时，人工聊天、任务操作和阶段审核仍可使用。无模型演示可通过“手工计划草案”展示校验、确认发布和版本比较；这类草案会标明人工来源。

## 开发与验证

```powershell
# 两个 PowerShell 窗口分别运行
& .\scripts\Start-Backend.ps1 -Reload
& .\scripts\Start-Frontend.ps1

# 后端、备份与前端测试，以及生产构建
& .\scripts\Test.ps1

# 数据备份
& D:\Anaconda3\envs\face_env\python.exe .\scripts\backup.py
```

开发前端地址为 Vite 输出的本地地址（默认 <http://127.0.0.1:5173>），通过代理访问后端。生产构建使用 `Build-Frontend.ps1`，由 FastAPI 在 8000 端口提供页面。备份与恢复操作详见下方启动说明。

## 项目资料

- [需求规格说明书](docs/需求规格说明书.md)：角色、功能、权限与验收标准。
- [系统设计](docs/系统设计.md)：模块、数据模型、Agent 流程和约束校验。
- [API 契约](docs/API.md)：请求字段、响应与错误约定。
- [启动与演示说明](docs/启动与演示说明.md)：环境、模型配置、演示路线、备份恢复和常见问题。
- [前端使用说明](docs/前端使用说明.md)：各角色页面与操作。
- [测试与验收记录](docs/测试与验收记录.md)：实际验证结果、页面截图和待完成的模型实验。
- [真实模型联调记录](docs/模型联调记录.md)：OpenRouter 实际闭环、接口兼容修复、耗时与原始结果。
- [后续验收记录](docs/后续验收记录.md)：独立数据目录的 50 项实时消息、阶段历史和恢复检查。
- [固定实验结果与分析](docs/实验结果与分析.md)：60 项真实分析、84 次请求、原始记录及评分边界。
- [Agent 可靠性改进](docs/Agent可靠性改进说明.md)与[独立复验](docs/Agent可靠性复验.md)：v3 来源核对、结束协议以及同口径的新旧版本比较。
- [连贯答辩演示](docs/答辩演示脚本.md)：独立数据目录、两版计划、三阶段五次提交，人工备用草案明确标注。
- [完整论文初稿](docs/thesis/论文初稿.md)及[可编辑 Word](docs/thesis/论文初稿.docx)：8 章正文、实际实验、图表与原始参考资料。
- [交付与答辩说明](docs/交付与答辩说明.md)：无凭据打包、新目录启动与约 7 分钟演示路线。
- [GitHub 使用说明](docs/GitHub使用说明.md)：仓库内容、换电脑获取项目和后续提交方法。
- [云端接续说明](docs/云端接续说明.md)：脱敏项目上下文、云端安装建议和待完成事项。
- [交付修订版复验结果](docs/交付修订版复验结果.md)：新一轮 24 项分析、46 次请求的完整结果与限制。

源码在 `backend/` 和 `frontend/`，辅助脚本在 `scripts/`。默认 `data/` 保存业务数据，`work/` 保存测试和备份材料；`.env`、数据与构建产物均已列入忽略规则。

当前交付为本地可运行初版，包含历史 60 项固定评价、独立 v3 评价、交付修订版独立复验、连贯答辩数据与完整论文初稿。修订后的新一轮共 24 项分析、46 次请求，归档 v2 的业务输出成功为 8/12，交付修订版为 4/12；模型仍有超时和语义偏差，AI 可靠性尚未通过验收。历史 Agent 严格成功 7/20 保留，不同轮次指标不能直接相减或声称统计显著优势。新版桌面/手机浏览器验收仍待完成。初版不包含自助注册、邮件邀请、自动接入代码仓库或多进程部署；账号通过显式初始化提供，成果可上传文件或填写链接。

实验默认离线，不请求模型：`scripts/Run-Experiments.ps1`；真实调用需显式增加 `-Live`，并通过所选免费型号、剩余额度、请求预算与冻结哈希预检。当前默认入口为[独立 v3 评价](experiments/reliability_v3/README.md)；旧框架步骤见 `experiments/README.md`，历史复现使用 10 月 15 日交付包，不覆盖旧锁。

连贯答辩演示使用 `scripts/seed_defense_demo.py` 创建全新隔离库，再用 `scripts/Start-DefenseDemo.ps1 -DataDir '<输出目录>'` 在 8001 端口启动，默认关闭 AI。已有业务数据不需要重新初始化，演示详情与公开账号见答辩脚本。
