"""python -m experiments.runner：默认只生成离线计划，--live 才能请求模型。"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
from types import SimpleNamespace
from .backend import PROMPT, PROMPT_VERSION, AgentOutput, OpenAIProvider
from .cases import VERSION, fingerprint, frozen_cases
from .scoring import score, summarize
from .state import inputs, isolated_state
from .transport import Budget, BudgetExceeded, GuardStopped, RecordingCreate, RecordingTools, preflight, redacted, safe_error

GROUPS = ('chat_only', 'context_only', 'agent')
ROOT = Path(__file__).resolve().parent


def make_jobs(cases, groups, repetitions, seed):
    jobs = []
    for repeat in range(1, repetitions + 1):
        for index, case in enumerate(cases):
            # 固定轮转交错，预算耗尽前不会先完整跑完某一种方法。
            offset = (seed + repeat - 1 + index) % len(groups)
            order = list(groups[offset:]) + list(groups[:offset])
            for group in order:
                jobs.append(dict(job_id=f'{case["id"]}-{repeat:02d}-{group}', case_id=case['id'],
                    repetition=repeat, group=group, status='not_run', output=None, score=None,
                    api_calls=[], tools=[], elapsed_ms=None, error=None, stop_reason=None))
    return jobs


def request_messages(case, group, context, messages, directory):
    visible = {'name_id_directory': directory} if group == 'chat_only' else context
    return [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': json.dumps(
        dict(mode=case['mode'], project_context=visible, messages=messages), ensure_ascii=False)}]


def protocol_hash():
    source = {name: (ROOT / name).read_text(encoding='utf-8') for name in
              ('backend.py', 'cases.py', 'state.py', 'scoring.py', 'transport.py', 'runner.py')}
    source['production_prompt'] = PROMPT
    source['production_schema'] = AgentOutput.model_json_schema()
    # 冻结生产算法与序列化接口，避免校验器或 provider 漂移被静默忽略。
    for name in ('agent.py', 'planning.py', 'schemas.py', 'models.py', 'serializers.py', 'database.py', 'permissions.py'):
        source['backend/' + name] = (ROOT.parent / 'backend' / 'app' / name).read_text(encoding='utf-8')
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def write_json(path, value, secrets=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(redacted(value, secrets), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def freeze_value():
    return dict(version=VERSION, cases_sha256=fingerprint(frozen_cases('all')), protocol_sha256=protocol_hash())


def verify_freeze(path):
    try:
        lock = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise GuardStopped('缺少有效冻结锁，请先生成并完成人工复核') from None
    if lock != freeze_value():
        raise GuardStopped('样例、评分协议或生产实现与冻结哈希不一致；禁止直接运行')
    return lock


def refresh_summary(output_dir, manifest, jobs):
    result = summarize(jobs)
    coverages = {g: sum(j['status'] != 'not_run' for j in jobs if j['group'] == g) for g in manifest['groups']}
    attempted = sum(coverages.values())
    result.update(run_mode=manifest['run_mode'], split=manifest['split'], seed=manifest['seed'],
        repetitions=manifest['repetitions'], cases_sha256=manifest['cases_sha256'],
        protocol_sha256=manifest['protocol_sha256'], comparison_complete=attempted == len(jobs),
        coverage_by_group=coverages, comparison_balanced=len(set(coverages.values())) <= 1,
        ranking_permitted=attempted == len(jobs) and set(manifest['groups']) == set(GROUPS),
        planned=len(jobs), attempted=attempted, model_requests=sum(len(j['api_calls']) for j in jobs),
        stop_reason=manifest.get('stop_reason'),
        interpretation='只有完整且各组覆盖一致的结果可作为全套比较；局部结果不可据此排名。')
    write_json(output_dir / 'summary.json', result)
    write_json(output_dir / 'records.json', jobs)
    return result


async def execute_job(job, case, settings, budget, checkpoint=None):
    started = time.monotonic()
    secrets = (settings.llm_api_key,)
    provider = None
    with isolated_state(case) as database:
        context, messages, directory = inputs(case, database)
        job['input_messages'] = request_messages(case, job['group'], context, messages, directory)
        try:
            job['status'] = 'running'
            provider = OpenAIProvider(settings)
            create = provider.client.chat.completions.create
            provider.client.chat.completions.create = RecordingCreate(create, budget, job['api_calls'], secrets, checkpoint)
            tools = RecordingTools(database, job['tools'], secrets, checkpoint)

            async def analyze():
                if job['group'] == 'agent':
                    return (await provider.analyze(context, tools, case['mode'], messages))['output']
                response = await provider.client.chat.completions.create(model=settings.llm_model,
                    messages=job['input_messages'], temperature=0.2)
                return json.loads(response.choices[0].message.content or '{}')

            job['output'] = await asyncio.wait_for(analyze(), timeout=60)
            job['score'] = score(case, job['output'])
            job['status'] = 'completed' if job['score']['output_valid'] else 'invalid'
        except Exception as exc:
            job['status'] = 'failed'
            job['error'] = safe_error(exc, secrets)
            job['score'] = score(case, job['output'])
            if isinstance(exc, (BudgetExceeded, GuardStopped)) or getattr(exc, 'status_code', None) in (401, 402, 403, 429):
                job['stop_reason'] = type(exc).__name__ if not getattr(exc, 'status_code', None) else f'http_{exc.status_code}'
        finally:
            job['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            if provider:
                await provider.close()
    return job.get('stop_reason')


async def run(args):
    output_dir = Path(args.output_dir).resolve()
    if args.summarize:
        manifest = json.loads((output_dir / 'manifest.json').read_text(encoding='utf-8'))
        jobs = json.loads((output_dir / 'records.json').read_text(encoding='utf-8'))
        cases = json.loads((output_dir / 'cases.json').read_text(encoding='utf-8'))
        if fingerprint(cases) != manifest['cases_sha256']:
            raise GuardStopped('结果目录中的样例/标签快照哈希不匹配')
        for job in jobs:
            if job['status'] == 'running':
                if protocol_hash() != manifest['protocol_sha256']:
                    raise GuardStopped('恢复中断记录须使用该轮冻结协议源码')
                # 进程中断留下的真实尝试保留原始请求，按失败计入分母。
                job['status'] = 'failed'
                job['error'] = dict(type='InterruptedAnalysis', status_code=None, message='分析中断，保留已有请求与工具记录')
                job['score'] = score(next(c for c in cases if c['id'] == job['case_id']), job.get('output'))
        # 仅重算已有评分的聚合，不重新解释模型响应，不读取环境凭据。
        refresh_summary(output_dir, manifest, jobs)
        return 0
    if args.freeze:
        write_json(Path(args.freeze_lock), freeze_value())
        print('冻结锁已生成，请独立复核后再显式使用 --live。')
        return 0
    if (output_dir / 'manifest.json').exists():
        raise GuardStopped('输出目录已有实验记录，请使用新目录或 --summarize')
    cases = frozen_cases(args.split)
    jobs = make_jobs(cases, tuple(args.groups), args.repetitions, args.seed)
    manifest = dict(version=VERSION, run_mode='live' if args.live else 'dry_run', split=args.split,
        groups=args.groups, repetitions=args.repetitions, seed=args.seed, max_calls=args.max_calls,
        cases_sha256=fingerprint(cases), protocol_sha256=protocol_hash(), prompt_version=PROMPT_VERSION,
        temperature=0.2, per_analysis_timeout_seconds=60, max_agent_rounds=6, max_retries=0,
        response_protocol=AgentOutput.model_json_schema(), response_format_forced=False,
        environment=dict(python=sys.version, platform=platform.platform(),
            packages={name: importlib.metadata.version(name) for name in ('openai', 'httpx', 'pydantic', 'SQLAlchemy', 'fastapi')}),
        information_scope=dict(chat_only='聊天室消息+共用名称编号目录',
            context_only='与agent完全相同的ProjectTools业务上下文+消息',
            agent='业务上下文+消息+生产工具和校验反馈'),
        budget_difference=dict(chat_only='单次请求', context_only='单次请求', agent='至多6次请求'),
        model=None, base_url=None, preflight=None, freeze=None, stop_reason=None)
    # --live 之外不读取凭据，也不实例化 SDK 客户端。
    write_json(output_dir / 'cases.json', cases)
    if not args.live:
        for job in jobs:
            case = next(c for c in cases if c['id'] == job['case_id'])
            with isolated_state(case) as database:
                context, messages, directory = inputs(case, database)
            job['input_messages'] = request_messages(case, job['group'], context, messages, directory)
        write_json(output_dir / 'manifest.json', manifest)
        refresh_summary(output_dir, manifest, jobs)
        print(f'离线准备完成：{len(cases)}个样例，{len(jobs)}项计划，模型请求0次。')
        return 0
    settings = SimpleNamespace(llm_api_key=os.environ.get('LLM_API_KEY') or os.environ.get('OPENROUTER_API_KEY', ''),
        llm_model=os.environ.get('LLM_MODEL', ''), llm_base_url=os.environ.get('LLM_BASE_URL', 'https://openrouter.ai/api/v1'),
        agent_timeout_seconds=60, ai_ready=True, data_dir=output_dir / 'isolated')
    secrets = (settings.llm_api_key,)
    try:
        manifest['freeze'] = verify_freeze(Path(args.freeze_lock))
        manifest['preflight'] = await preflight(settings, args.max_calls)
        manifest.update(model=settings.llm_model, base_url=settings.llm_base_url)
        budget = Budget(manifest['preflight']['effective_max_calls'])
    except Exception as exc:
        manifest.update(stop_reason='preflight_stopped', error=safe_error(exc, secrets))
        write_json(output_dir / 'manifest.json', manifest, secrets)
        refresh_summary(output_dir, manifest, jobs)
        print('预检未通过；未发起模型请求，完整计划与停止原因已保存。')
        return 2
    write_json(output_dir / 'manifest.json', manifest, secrets)
    refresh_summary(output_dir, manifest, jobs)
    for job in jobs:
        if budget.used >= budget.limit:
            manifest['stop_reason'] = 'global_or_free_quota_exhausted'
            break
        case = next(c for c in cases if c['id'] == job['case_id'])
        def checkpoint():
            try:
                write_json(output_dir / 'attempts' / (job['job_id'] + '.json'), job, secrets)
                write_json(output_dir / 'records.json', jobs, secrets)
            except OSError:
                budget.limit = budget.used  # 无法保存时禁止再发起下一次模型请求。
                raise
        stop = await execute_job(job, case, settings, budget, checkpoint)
        write_json(output_dir / 'attempts' / (job['job_id'] + '.json'), job, secrets)
        write_json(output_dir / 'records.json', jobs, secrets)
        if stop:
            manifest['stop_reason'] = stop
            break
    write_json(output_dir / 'manifest.json', manifest, secrets)
    refresh_summary(output_dir, manifest, redacted(jobs, secrets))
    print('真实实验记录已保存；请查看 summary.json 的完整性、覆盖数及失败记录。')
    return 0 if all(j['status'] != 'not_run' for j in jobs) else 2


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='显式允许真实模型请求')
    mode.add_argument('--dry-run', action='store_true', help='离线准备；默认行为')
    mode.add_argument('--summarize', action='store_true', help='无网络重算已有结果汇总')
    mode.add_argument('--freeze', action='store_true', help='生成待独立审核的冻结哈希')
    result.add_argument('--split', choices=('dev', 'eval', 'all'), default='eval')
    result.add_argument('--groups', nargs='+', choices=GROUPS, default=list(GROUPS))
    result.add_argument('--repetitions', type=int, default=2)
    result.add_argument('--seed', type=int, default=20261016)
    result.add_argument('--max-calls', type=int, default=180)
    result.add_argument('--output-dir', default=str(ROOT / 'results' / 'dry-run'))
    result.add_argument('--freeze-lock', default=str(ROOT / 'freeze.json'))
    return result


def main():
    args = parser().parse_args()
    if args.repetitions < 1 or not 1 <= args.max_calls <= 180 or len(args.groups) != len(set(args.groups)):
        parser().error('repetitions须为正数，max-calls须为1至180，groups不能重复')
    try:
        return asyncio.run(run(args))
    except (GuardStopped, OSError, ValueError) as exc:
        # 这里只报告稳定提示，不打印可能包含密钥的异常原文。
        print(f'实验未完成：{type(exc).__name__}。请检查参数和记录目录。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
