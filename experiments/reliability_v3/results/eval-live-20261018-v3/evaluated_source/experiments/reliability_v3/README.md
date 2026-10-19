# 独立 v3 可靠性评价

旧评价样例、评分与真实结果保留；旧 SDK 边界测试明确使用归档 v2，当前 v3 有独立协议测试；本目录的 `baseline/` 为只读归档。评分与运行定义见 [PROTOCOL.md](PROTOCOL.md)。程序默认离线，不自动真实调用；已保存的实际运行情况见 [独立复验报告](../../docs/Agent可靠性复验.md)。

在仓库根目录运行：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -X utf8 -m unittest experiments.reliability_v3.tests.test_protocol -v
& 'D:\Anaconda3\envs\face_env\python.exe' -X utf8 -m experiments.reliability_v3.runner --output-dir experiments/reliability_v3/results/plan
```

默认为6评价例×2组×2重复，共24项、0模型请求。开发集可显式加 `--split dev`，不得混入评价成功率。

在生产源码固定、样例预审和独立双审通过后，由主代理生成新锁：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -X utf8 -m experiments.reliability_v3.runner --freeze
```

真实运行仅由主代理在已授权的免费额度范围内显式执行；进程须已提供模型和密钥环境，程序不读凭据文件：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -X utf8 -m experiments.reliability_v3.runner --live --max-calls 180 --output-dir experiments/reliability_v3/results/live-reviewed
```

每组最多12次分析，每项最多6模型请求、60秒、温度0.2、SDK重试0；最坏144请求。当前报价或免费额度未知会停止，不能自动切付费模型。

中断后只离线重汇总已保存评分：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -X utf8 -m experiments.reliability_v3.runner --summarize --output-dir experiments/reliability_v3/results/live-reviewed
```

先看 summary 的 `comparison_complete`、`comparison_balanced` 与 `ranking_permitted`。主指标 `semantic_success` 在缺信息澄清场景允许额外追问独立计数，计划场景有未解决问题仍失败；`strict_success` 进一步要求无额外追问及无原样旧任务输出。两者均不同于旧7/20指标。null token/费用不是0；失败保留在实际尝试分母。


项目 PowerShell 入口 `scripts/Run-Experiments.ps1` 默认选择本目录的独立新评价，仍为离线：

```powershell
& .\scripts\Run-Experiments.ps1 -Split dev -Repetitions 1
# 通过冻结与双审后才显式调用真实免费模型：
& .\scripts\Run-Experiments.ps1 -Live -DirectModelConnection
```

`-Protocol legacy` 选择旧框架；旧锁对应历史生产源码，新实现会使旧锁检查失败。历史复现应使用 10 月 15 日交付包，不在新源码上覆盖旧锁或改写旧结果。
