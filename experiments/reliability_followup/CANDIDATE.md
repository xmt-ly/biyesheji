# 独立复验准备交付记录

状态：**CANDIDATE，待独立规格与质量审查**。记录日期2026-10-18。本目录没有 `freeze.json`、没有正式 `results/`、没有真实模型请求；本轮只完成新题目及离线验证准备。

新增内容：

- `cases.py`：校园共享场地预约场景，FUE01–06六个评价例和FUD01–03三个开发例，固定业务时间2026-11-02 10:00（Asia/Shanghai），新人物、任务、需求及承诺。
- `runner.py`、`scoring.py`、`state.py`、`backend.py`、`__init__.py`：逐字复用审核后的v3执行实现。
- `baseline/agent.py`、`database.py`、`models.py`、`permissions.py`、`planning.py`、`schemas.py`、`serializers.py`、`manifest.json`：逐字复制的8份归档文件。
- `PROTOCOL.md`、`README.md`：本轮候选协议、边界和离线入口。
- `tests/test_protocol.py`：43个测试方法，直接导入新目录module，复用旧测试思想并改为本轮题目身份；SDK边界由MockTransport在进程内验证。
- `tests/test_candidate.py`：10个新增候选测试，覆盖身份/日期/外键、初态/修复可行性、所有标签oracle、完成保护、输入隔离与源文件保留。
- `protected_before.json`、`candidate_evidence.json`：旧文件保护清单及本轮SHA证据，均不是冻结锁。
- `tdd-red.txt`、`tdd-candidate-red.txt`、`tdd-green.txt`：先红后绿的离线日志。

## TDD与新鲜验证

先创建新目录的协议测试，再运行：43个方法出现26个“缺少新执行器”的断言失败与29个缺少本地module的错误/子测试错误。随后新增10个候选测试，补实现前运行，10个均以“新业务题目尚未准备”断言失败。两个日志保留了真实红灯。

复制冻结执行源码、补齐新题目和协议后运行：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -B -X utf8 -m unittest discover -s experiments/reliability_followup/tests -v
```

结果：**53 tests，OK，14.323秒**。进程使用独立C盘 `DATA_DIR`、固定离线JWT，清空模型和Key环境变量，使用 `-B` 和unittest，不产生pytest cache。测试产生的执行记录都在独立临时目录，本目录没有正式实验结果。传输层测试中的预检/请求均为本地stub，没有外网请求。

所有9个oracle通过本目录scorer及真实公共check_plan；初始状态除明确待修的FUE05依赖时间冲突外均可行。完成任务字段保护反例、冗余任务、错误来源、错误ID、未知费用、每项/全局预算、禁重定向与中断恢复反例均通过。以上是评价程序验证，不是模型成功数。

## 源码一致与旧文件保护

`candidate_evidence.json` 对13份复制文件逐字比较，全部相同；`protected_before.json` 中88份旧源码、归档、结果、锁及当前兼容helper全部仍保持SHA。生产helper SHA仍为 `55e694506db60e0fa9103d49397c178e54e00b09393c78a8f126ba8ee5239b06`。

| 文件 | 新旧相同SHA256 |
| --- | --- |
| runner.py | b1dd1b225af5c64f2b744850e057d39d5967feed928bdbcd489ffce54fad2109 |
| scoring.py | c0154df6d4fff6efcae4e6317c9cde129c0b4e4f5e37368455be5924ef2defa3 |
| state.py | 4b936b5ab2204dba7fbd2e93be23d9e36bcbd9361bd3bb0756408323a8e9afe7 |
| backend.py | 9d51a8b571d6290206128d1f7589bed1fffd5531f3fa289e865357ee0a88fad1 |
| __init__.py | 99bfb35af4ae894fadf76d13938e0d0e5258fa6d9a487263c2e91ba115e24584 |

9例全标签指纹：`bb9b814ce447212e182d3e9e634a57104fa47a50d837a2d31f26ab86f85dc193`。独立审查若导致候选标签修订，应在真实调用前重新验证和固定，不将本记录冒充真实运行锁。

## 留给独立审查的边界

组长技术ID21与项目ID1为逐字复用state.py的固定元数据；21仍是本轮团队组长何澄，人物姓名和账号全新，没有引入悬空或非成员creator。其余成员72/73、教师12、需求1701–1704、任务2701–2703、消息3701起均与旧轮不同。题目独立性不要求技术整数完全不相交。

合成oracle从标签直接构造答案，因此全绿只说明真值、来源、日期依赖和公共约束内部一致；不说明模型能做对，也不代表任何真实质量成功率。有限标题/验收/问题匹配仍可能低估未列等义表达。尚待独立规格与质量复核、主代理正式固定源码和锁、保存完整计划，再决定真实新轮；首轮真实输出无论好坏都应保留原分数和未知费用。
