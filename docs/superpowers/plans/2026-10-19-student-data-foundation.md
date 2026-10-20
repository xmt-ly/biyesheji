# P0：学生协作数据与指标基础实现计划

> **面向 AI 代理的工作者：** 使用 subagent-driven-development 或 executing-plans 逐任务实现。步骤复选框仅在有实际结果后勾选；本文编写时均未开始。

**目标：** 在保留既有业务和历史实验的前提下，为学生端深化提供可迁移、可追溯、权限隔离的数据基础。

**架构：** 纯函数负责筛选与指标；数据库服务负责快照和业务事件；API负责授权与参数边界。新增扩展表按显式版本迁移，旧业务表和历史JSON快照不批量重写。

**技术栈：** 现有 Python、FastAPI、SQLAlchemy、SQLite、pytest；不为本批引入队列、Redis或外部数据库。

---

关联总计划：[学生端深化与数据可视化](2026-10-19-student-collaboration-and-dashboard-roadmap.md)。覆盖 DATA-01，为所有 VIS/STU/AI 项提供基础。

## 文件和测试入口

| 创建/修改 | 路径 | 职责 |
| --- | --- | --- |
| 创建 | `backend/app/migrations/__init__.py`、`runner.py`、`versions/v002_analytics.py` | 新库版本标记、旧库显式增量迁移与幂等检查 |
| 创建 | `scripts/migrate_data.py`、`scripts/Migrate-Data.ps1` | 跨平台迁移CLI与Windows包装，调用既有备份能力 |
| 创建 | `backend/app/analytics_models.py` | ProjectDailySnapshot、CollaborationEvent |
| 创建 | `backend/app/analytics/__init__.py`、`metrics.py`、`allocation.py`、`snapshots.py`、`events.py` | 指标、容量、观察记录与事件投影 |
| 创建 | `backend/app/analytics_schemas.py`、`routers/analytics.py` | 明确响应字段与学生内部分析API |
| 修改 | `backend/app/database.py`、`main.py` | 注册新模型、版本检测和快照调度生命周期 |
| 修改 | `backend/app/business.py`、`planning.py`、相关业务router | 共用指标规则、事务内事件和当天快照 |
| 创建 | `backend/tests/conftest.py` | 非autouse的student_env隔离测试夹具 |
| 创建 | `backend/tests/test_student_migrations.py`、`test_analytics_metrics.py`、`test_analytics_snapshots.py`、`test_analytics_permissions.py` | 迁移、数值、日期、隔离与并发 |

子任务测试运行时先设置独立 DATA_DIR、测试JWT和空 LLM_API_KEY/LLM_MODEL。以下命令中的 `python` 指项目指定解释器或云端 `.venv/bin/python`，不是任意系统Python；Windows也可使用 `scripts/Test.ps1` 做原有回归。

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_analytics_metrics.py -q
```

## 任务0：固定基线、样例与测试夹具

- [ ] **步骤1：记录基线。** 核对当前分支与云端Linux修复，记录生产文件SHA和现有测试结果；从真实业务库只做备份，不向其中写入测试样例。
- [ ] **步骤2：创建夹具。** `student_env` 使用临时DATA_DIR、内存SQLite、空模型配置、`create_app(Settings(...))`和`TestClient`；进入生命周期后调用现有`seed_demo`，登录六个演示账户，返回client、app、headers和两个项目ID。该夹具不自动作用于旧测试。
- [ ] **步骤3：固定新分析样例。** 单独创建两项目、已确认/草稿需求、todo/doing/done任务、跨周/纯周末日期、容量0和容量8的成员；时间参数固定为`2026-10-19T12:00:00+08:00`，不依赖执行机器当天。
- [ ] **步骤4：先验证隔离。** 运行`python -m pytest backend/tests/test_analytics_permissions.py -q`，在未有新路由时预期404导致断言失败；不得请求真实模型。
- [ ] **步骤5：提交测试基础。** 提交范围限新夹具和样例，提交信息`test(学生分析): 建立隔离指标与权限样例`。

## 任务1：增量迁移与扩展表

版本`v002_analytics`只增加迁移记录、每日快照和协作事件表。每日快照唯一键`(project_id, snapshot_date)`，字段包括UTC观测时间、Asia/Shanghai业务日、项目修订号、指标版本、计划基线、任务/成员指标JSON、数据用途标记。事件记录项目、操作者、对象、类型、事件时间、事件数据和幂等键，不存登录token或模型密钥。

旧库默认不自动重写；启动发现需要迁移时输出具体版本和迁移命令。全新库直接创建所需表并标记版本。后续P2/P3各自添加新的迁移版本，不能修改已经应用的v002内容。

- [ ] **步骤1：写迁移失败测试。** 以旧15表副本验证升级前后行数、文件SHA和原有业务JSON相同；同一迁移执行两次不新增记录；中途异常不写成功版本。
- [ ] **步骤2：确认失败。** 运行`python -m pytest backend/tests/test_student_migrations.py -q`，预期新迁移入口不存在或版本未变化。
- [ ] **步骤3：实现显式CLI。** `python scripts/migrate_data.py --data-dir data/cloud-demo --apply`先创建项目内备份，核对当前版本，在单事务应用DDL和版本记录；路径越界、链接、缺库、未知新版本返回非0，不用seed替代迁移。`--check`只报告所需迁移，不写库。
- [ ] **步骤4：验证恢复和启动。** 在新临时副本跑迁移、重复迁移、模拟失败和备份恢复；检查应用能读取旧账户、任务、文件和阶段历史。回退使用备份副本替换流程，不删除正式表。
- [ ] **步骤5：提交。** `feat(数据): 添加学生分析增量迁移与版本检查`，保留迁移前后验证报告。

## 任务2：统一指标与日期筛选

纯函数契约：

```python
def summarize_tasks(tasks: list[dict], *, user_id: int | None, as_of: str) -> dict:
    """返回total/done/doing/todo/overdue/due_soon/remaining_hours及对应task_ids。"""

def requirement_coverage(requirements: list[dict], tasks: list[dict]) -> dict:
    """只统计已确认需求，返回covered_ids/uncovered_ids及明确分母。"""
```

最小数值测试：

```python
def test_overdue_and_done_use_the_same_filtered_task_set():
    from app.analytics.metrics import summarize_tasks
    tasks = [
        dict(id=1, assignee_id=3, status='todo', due_date='2026-10-18', remaining_hours=3),
        dict(id=2, assignee_id=3, status='done', due_date='2026-10-18', remaining_hours=0),
        dict(id=3, assignee_id=4, status='doing', due_date='2026-10-20', remaining_hours=8),
    ]
    value = summarize_tasks(tasks, user_id=3, as_of='2026-10-19')
    assert value['total'] == 2
    assert value['done'] == 1
    assert value['overdue'] == 1
    assert value['overdue_task_ids'] == [1]
    assert value['remaining_hours'] == 3
```

- [ ] **步骤1：补充失败断言。** 覆盖截止当天不逾期、7天边界、草稿需求不入分母、重复任务不重复覆盖、空项目、错误日期和零分母。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_analytics_metrics.py -q`，预期未实现函数导致失败。
- [ ] **步骤3：实现。** 输入按允许筛选一次，结果统一产生数值、task_ids、口径和as_of；课程必做覆盖与需求任务覆盖分别计算；无分母返回null和原因。
- [ ] **步骤4：验证。** 同一fixture将计数卡与下钻ID逐一比较，读取现有progress接口确认其完成比例定义没有改变。
- [ ] **步骤5：提交。** `feat(分析): 统一任务需求指标和下钻口径`。

## 任务3：成员周负荷规则共用

新增`allocate_weekly(tasks, members)`纯函数，输出每个`(user_id, week_start)`的remaining_allocated_hours、capacity_hours、over_capacity_hours、task_ids。复用当前planning中工作日均分、纯周末归开始周、done任务不占容量的规则，不按任务数量判断轻重。

- [ ] **步骤1：写对照测试。** 8h容量、12h计划应超量4h；跨周6h任务按各周工作日分配；周末任务归开始周；容量0不除零。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_analytics_metrics.py -k weekly -q`，预期新分配入口缺失而失败。
- [ ] **步骤3：实现共用计算。** 当前生产`planning.py`调用同一个纯分配器；历史baseline与evaluated_source不改。诊断、热力图和约束检查统一消费该结果。
- [ ] **步骤4：验证等价。** 对旧容量测试和新跨周fixture逐一比较违规对象、周、分配值；零容量展示明确文本，不输出Infinity/NaN。
- [ ] **步骤5：提交。** `refactor(排期): 统一周负荷计算供分析与校验复用`。

## 任务4：真实快照与状态事件

业务写入时在同事务追加事件；对当前业务日刷新快照。独立日切调度只处理实际观测到的当前日，应用关闭的日期保留空缺；项目归档停止自动新采集。新增/完成/重新打开/范围调整采用明确事件，不能根据updated_at猜完成时间。

- [ ] **步骤1：写失败测试。** 同一天重复刷新只有一行；上海23:59和次日00:01分别落正确业务日；启动不能创建停机期间过去日期；事务回滚不留事件或快照。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_analytics_snapshots.py -q`，预期新服务不存在。
- [ ] **步骤3：实现。** `capture_today_snapshot(session, project_id, observed_at)`显式注入时钟，拒绝以当前状态写过去日期；快照保留revision/plan_version，事件幂等键避免HTTP重试重复。生命周期启动和关闭调度必须有界可取消。
- [ ] **步骤4：验证历史。** 覆盖任务新增导致燃尽上升、完成纠正、新计划基线、缺采样日、重复请求和服务重启；旧Plan/Submission快照不变。
- [ ] **步骤5：提交。** `feat(分析): 保存真实每日观测与协作事件`。

## 任务5：分析API与权限

统一前缀`/api/projects/{project_id}/analytics`：`/overview`、`/personal`、`/workload`、`/requirements`、`/timeline`、`/trends`、`/stages`。参数为ISO `from/to`、可选项目成员`member_id`与`stage_index`；`from<=to`、范围最多366天，时区固定，不接受任意SQL排序或其他项目对象ID。

每个内部分析API都调用当前学生成员授权。教师继续使用旧公开progress与stage接口，新API直接拒绝教师；不能先查全项目私有事件再在前端隐藏。

- [ ] **步骤1：写失败测试。** 本组学生成功、另一组/教师/未登录拒绝、跨项目member_id拒绝、反向日期422、超范围422、对象不存在不返回其私有明细。
- [ ] **步骤2：运行。** `python -m pytest backend/tests/test_analytics_permissions.py -q`，预期未注册路由404。
- [ ] **步骤3：实现。** 注册新router，返回规范响应和可下钻ID；timeline按权限投影安全摘要，不把整个Audit.detail原样返回。
- [ ] **步骤4：回归。** 新API、原后端、备份/恢复和原公开接口测试通过；对旧freeze拒绝新生产SHA的结果按版本边界记录，不改旧锁伪造通过。
- [ ] **步骤5：提交。** `feat(分析): 提供隔离的学生仪表盘数据接口`；保存P0实际验收记录并更新总计划状态。

## P0退出检查

- [ ] 旧库副本升级、重复升级、失败恢复及新库初始化有证据。
- [ ] 指标、下钻、周容量和时间边界一致；真实采样缺口未伪造。
- [ ] 教师和跨组访问在服务端拒绝；旧业务与正式数据保留。
- [ ] 新生产源码SHA、数据库版本和测试结果已归档，P1使用的API契约可读。
