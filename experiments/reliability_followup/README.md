# 交付修订后的独立复验候选

**CANDIDATE：仅准备，未冻结、未真实调用。** 新场景“校园共享场地预约”有3个开发例、6个评价例。案例与公共字段、日期依赖标签、离线 oracle 及验证说明见 [PROTOCOL.md](PROTOCOL.md)。候选审查通过后，由主代理负责冻结和后续真实执行；本阶段不生成锁或正式结果。

执行器、评分器、状态构造器、后端加载器、包入口与 v2 baseline 归档逐字复制自已审核 `reliability_v3`。生产 JSON 字符串兼容修订保持固定；不为这9道题修改生产提示或算法。旧24项/57请求、旧结果与锁原样保留。旧轮响应回放与单次真实兼容联调不算本轮质量。

两组 `baseline_v2` / `improved_v3` 使用相同完整 context、消息、模型、温度0.2，每项60秒、最多6请求，SDK重试0；6例×2组×2重复=24项，每组12项，最坏144请求，全局上限180并受免费余量限制。报价或额度未知就停，禁止付费回退和重定向。只有完整平衡的正式 live 评价才可比较，未知响应、用量或费用保持 null。

在项目根目录运行离线测试；环境变量只作用于当前 PowerShell 进程，不读凭据文件：

```powershell
$env:DATA_DIR = 'C:\Users\XMT18\Documents\Codex\work\followup-offline-20261018'
$env:JWT_SECRET = 'followup-offline-only-jwt-secret-20261018'
$env:LLM_API_KEY = ''
$env:OPENROUTER_API_KEY = ''
$env:LLM_MODEL = ''
& 'D:\Anaconda3\envs\face_env\python.exe' -B -X utf8 -m unittest discover -s experiments/reliability_followup/tests -v
```

测试中的 SDK 请求全部由 `httpx.MockTransport` 在进程内接管；预检停止路径也由本地 stub 接管，无外网、真实 Key 或模型请求。合成 oracle 只验证标签与约束，不能当模型质量结果。测试临时文件只位于独立临时目录；`-B` 不写 Python 缓存，unittest 不产生 pytest cache。

待独立审查后，可由主代理在新的本轮目录先保存离线完整计划。此命令仍然0模型请求：

```powershell
& 'D:\Anaconda3\envs\face_env\python.exe' -B -X utf8 -m experiments.reliability_followup.runner --output-dir experiments/reliability_followup/results/plan-reviewed
```

开发集需显式 `--split dev`，不混入6例评价统计。沿用的控制台 v3 名称、组名及 seed 仅是执行兼容标识；业务时间为2026-11-02（Asia/Shanghai），新题号为 FUE01–06、FUD01–03。

独立审查通过后才允许生成本目录新锁，并在真实请求前保存被测源码及全部计划。看到首次真实输出后，保留全部成功与失败、原始响应、tokens与未知费用；不改本轮标签、评分或提示以抬分，不覆盖旧历史。

候选验证证据存于本目录的 TDD 日志、`protected_before.json` 和候选交付记录。候选状态不代表新模型质量通过，页面验收或干净安装也不由这些离线测试替代。
