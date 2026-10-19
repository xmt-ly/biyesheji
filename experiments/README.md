# 协作 Agent 隔离评价框架

此目录实现需求规格说明书第 10 节的三组对照、冻结样例、真实请求记录与机械评分。默认执行离线准备，不请求模型。实验不导入 `app.main`，不读取 `.env`、`jwt.key` 或正式数据库，不发布草案。

在项目根目录使用现有 Python：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -m pytest experiments/tests -q
& 'D:\Anaconda3\envs\face_env\python.exe' -m experiments.runner --dry-run --split eval --repetitions 2 --output-dir experiments/results/eval-dry-run
& 'D:\Anaconda3\envs\face_env\python.exe' -m experiments.runner --summarize --output-dir experiments/results/eval-dry-run
```

开发集用 `--split dev`；最终评价集用 `--split eval`。默认三组均运行，`--groups` 可选择子组用于开发。默认 seed 为 `20261016`，方法按样例和重复次数固定轮转交错。已有结果目录会拒绝覆盖。

真实运行前须先完成人工规格与质量复核，再冻结协议和样例：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -m experiments.runner --freeze
# 独立复核 experiments/freeze.json 及其对应源码和标签后，再由获授权的调用方执行：
& 'D:\Anaconda3\envs\face_env\python.exe' -m experiments.runner --live --split eval --repetitions 2 --max-calls 180 --output-dir experiments/results/eval-live-01
```

凭据和模型只从调用进程环境读取：`LLM_API_KEY`（或 `OPENROUTER_API_KEY`）、`LLM_MODEL`，以及可选的 `LLM_BASE_URL`。真实模式仅接受 `https://openrouter.ai/api/v1`。此框架不会载入任何环境文件，也不会选择或切换模型。请由已有安全方式准备进程环境，禁止把凭据写入命令或结果文件。

真实模式先查询 OpenRouter 模型价格和免费剩余请求额度。当前选定模型所有已公开价格项须均为零，免费剩余额度须已知且大于零，有限美元额度须未耗尽；否则停止。有效调用上限取 `min(--max-calls, free_model_daily_requests.remaining)`。每个 API 请求（包括失败）计一次，SDK 不自动重试，单次分析总超时为 60 秒。两组基线至多一次，Agent 至多六轮。每次实际请求均附 `provider.allow_fallbacks=false` 和零价格上限；发现非零实际费用立即停止，保留该响应。价格和额度未知时不推测、不更换付费模型。

结果文件：

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 信息范围、模型与温度、预算、运行环境、输出协议、冻结哈希、脱敏预检、停止原因 |
| `cases.json` | 本次完整初始状态、消息与冻结标签；只在本地保存，标签不发给模型 |
| `records.json` | 完整 planned 清单；原始请求、原始响应、工具参数与结果、输出、评分、异常、耗时 |
| `attempts/*.json` | 每个实际尝试的独立记录，包含失败与非法输出 |
| `summary.json` | 各组覆盖数、完整性、成功/可行率、抽取 TP/FP/FN/F1、费用与用量、局限 |

缺少接口用量或费用时保存 `null`，不以零费用模型报价代替实际账单。原始响应仅做凭据及令牌脱敏，不编造或修补模型输出。单元测试中的本地 HTTP 响应只验证边界行为，绝不成为实验样本。

每次实际 API 请求返回或异常、每次工具执行后都会原子保存检查点。进程中断留下的 `running` 记录在 `--summarize` 时标为 `InterruptedAnalysis` 失败，按冻结标签计算缺失输出评分，保留已完成的原始请求与工具记录；正在传输、尚未返回的请求可能没有服务端响应。

`--summarize` 仅读取已有结果，离线重新汇总已保存评分，不重新调用模型、不修改标签。`not_run` 表示未尝试，单独报告，既不计零分也不计失败；非法输出和真实请求失败计入已尝试分母。`comparison_complete=false` 或覆盖不平衡时，结果只能作为明确标注的部分记录，不可作为全套比较或排名。完整运行仍须结合样例规模和重复次数解释。

详细口径见[实验方案](实验方案.md)和[标签说明](标签说明.md)。
