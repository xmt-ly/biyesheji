"""默认 dry-run；--live 才读取进程凭据并请求零价模型。"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from types import SimpleNamespace
from .backend import AgentOutput, BACKEND, provider_class, sha256, verify_baseline
from .cases import VERSION, fingerprint, frozen_cases
from .scoring import score, summarize
from .state import inputs, isolated_state
from experiments.transport import (Budget, BudgetExceeded, GuardStopped, RecordingCreate,
    RecordingTools, preflight, redacted, safe_error)

ROOT = Path(__file__).resolve().parent
GROUPS = ('baseline_v2', 'improved_v3')
ANALYSIS_TIMEOUT_SECONDS = 60
MAX_REQUESTS_PER_ANALYSIS = 6


def common_input(case, context, messages):
    return dict(mode=case['mode'], project_context=deepcopy(context), messages=deepcopy(messages))


def make_jobs(cases, groups=GROUPS, repetitions=2, seed=20261020):
    jobs = []
    for repeat in range(1, repetitions + 1):
        for index, case in enumerate(cases):
            offset = (seed + repeat - 1 + index) % len(groups)
            order = tuple(groups[offset:]) + tuple(groups[:offset])
            for group in order:
                jobs.append(dict(job_id=f'{case["id"]}-{repeat:02d}-{group}', case_id=case['id'],
                    repetition=repeat, group=group, status='not_run', output=None, raw_submission=None, score=None,
                    common_input=None, common_input_sha256=None, api_calls=[], tools=[],
                    elapsed_ms=None, error=None, stop_reason=None))
    return jobs


def source_hashes():
    result = {str(p.relative_to(ROOT)).replace('\\', '/'):sha256(p)
              for p in sorted(ROOT.glob('*.py'))}
    result.update({'tests/' + p.name:sha256(p) for p in sorted((ROOT / 'tests').glob('*.py'))})
    for name in ('PROTOCOL.md', 'README.md'):
        path = ROOT / name
        if path.exists():
            result[name] = sha256(path)
    for path in sorted((ROOT / 'baseline').glob('*')):
        if path.is_file():
            result['baseline/' + path.name] = sha256(path)
    production = {BACKEND / 'app' / name for name in ('schemas.py', 'planning.py', 'models.py',
        'serializers.py', 'database.py', 'permissions.py')}
    production.update((BACKEND / 'app').glob('agent*.py'))
    for path in sorted(production):
        result['production/' + path.name] = sha256(path)
    result['shared/transport.py'] = sha256(ROOT.parent / 'transport.py')
    return result


def protocol_hash():
    return fingerprint(source_hashes())


def freeze_value():
    return dict(version=VERSION, cases_sha256=fingerprint(frozen_cases('all')),
        protocol_sha256=protocol_hash(), source_sha256=source_hashes(), baseline_sha256=verify_baseline())


def verify_freeze(path):
    try:
        lock = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise GuardStopped('缺少本目录的有效冻结锁，请先离线审核') from None
    if lock != freeze_value():
        raise GuardStopped('样例、协议、基线或生产源码与冻结锁不一致')
    return lock


def write_json(path, value, secrets=()):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(redacted(value, secrets), ensure_ascii=False,
        indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def refresh_summary(output_dir, manifest, jobs):
    result = summarize(jobs)
    coverage = {g:Counter((j['case_id'], j['repetition']) for j in jobs
                if j['group'] == g and j['status'] not in ('not_run', 'running')) for g in manifest['groups']}
    attempted = sum(j['status'] != 'not_run' for j in jobs)
    expected_matrix = Counter((case_id, repeat, group) for case_id in manifest['case_ids']
        for repeat in range(1, manifest['repetitions'] + 1) for group in manifest['groups'])
    actual_matrix = Counter((j['case_id'], j['repetition'], j['group']) for j in jobs)
    plan_integrity = expected_matrix == actual_matrix and len({j['job_id'] for j in jobs}) == len(jobs)
    terminal = plan_integrity and all(j['status'] in ('completed', 'invalid', 'failed') for j in jobs)
    balanced = len({tuple(sorted(c.items())) for c in coverage.values()}) <= 1
    full_eval = manifest['split'] == 'eval' and len({j['case_id'] for j in jobs}) == 6 and manifest['repetitions'] == 2
    result.update(version=VERSION, run_mode=manifest['run_mode'], split=manifest['split'],
        model=manifest.get('model'), environment=manifest.get('environment'),
        cases_sha256=manifest['cases_sha256'], protocol_sha256=manifest['protocol_sha256'],
        plan_integrity=plan_integrity, comparison_complete=terminal, comparison_balanced=balanced,
        ranking_permitted=bool(terminal and balanced and full_eval and manifest['run_mode'] == 'live' and
                               set(manifest['groups']) == set(GROUPS)),
        planned=len(jobs), attempted=attempted,
        coverage_by_group={g:sum(c.values()) for g,c in coverage.items()},
        model_requests=sum(len(j['api_calls']) for j in jobs), stop_reason=manifest.get('stop_reason'),
        interpretation='semantic_success和strict_success定义见独立v3协议；不完整或不平衡不得排名。')
    write_json(Path(output_dir) / 'summary.json', result)
    write_json(Path(output_dir) / 'records.json', jobs)
    return result


class AnalysisRequestLimit(RuntimeError):
    pass


class LimitedRecordingCreate(RecordingCreate):
    async def __call__(self, **kwargs):
        if len(self.calls) >= MAX_REQUESTS_PER_ANALYSIS:
            raise AnalysisRequestLimit('每次分析最多六个模型请求')
        return await super().__call__(**kwargs)


def _parse_raw_json_content(content):
    """只解析纯 JSON 或包住整个响应的单个 JSON 围栏，不执行业务规范化。"""
    raw = content or ''
    fence = re.fullmatch(r'\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*', raw)
    return json.loads(fence.group(1) if fence else raw)


def raw_submission_from_calls(calls):
    """只解析真实保存的最后响应；不存在响应或提交时保持 None。"""
    if not calls or not calls[-1].get('response'):
        return None
    choices = calls[-1]['response'].get('choices') or []
    if not choices:
        return None
    message = choices[0].get('message') or {}
    tool_calls = message.get('tool_calls') or []
    try:
        if len(tool_calls) == 1 and tool_calls[0].get('function', {}).get('name') == 'finalize_analysis':
            value = json.loads(tool_calls[0]['function']['arguments'])
            return deepcopy(value.get('analysis')) if isinstance(value, dict) else None
        if not tool_calls and message.get('content'):
            value = _parse_raw_json_content(message['content'])
            return deepcopy(value.get('analysis', value)) if isinstance(value, dict) else value
    except (TypeError, ValueError, KeyError):
        return None
    return None


def failure_score(case, output, raw_submission):
    result = score(case, output, raw_submission)
    # 真实尝试没有完整完成，即使崩溃前已保存部分 output 也不能计为成功。
    result.update(semantic_success=False, strict_success=False, attempt_failed=True)
    return result


def default_provider(group, settings):
    """两组使用相同 SDK 边界；禁止重定向在预算记录之外再次发送 POST。"""
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient
    # 冷启动避免归档/当前 provider 先创建一个会自动重定向的默认客户端。
    provider = provider_class(group)(SimpleNamespace(ai_ready=False))
    provider.settings = settings
    provider.client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url,
        timeout=ANALYSIS_TIMEOUT_SECONDS, max_retries=0,
        http_client=DefaultAsyncHttpxClient(follow_redirects=False, timeout=ANALYSIS_TIMEOUT_SECONDS))
    return provider


async def execute_job(job, case, settings, budget, checkpoint=None, provider_factory=None):
    started = time.monotonic()
    secrets = (settings.llm_api_key,)
    provider = None
    with isolated_state(case) as database:
        context, messages = inputs(case, database)
        visible = common_input(case, context, messages)
        job.update(common_input=visible, common_input_sha256=fingerprint(visible), status='running')
        try:
            if checkpoint:
                checkpoint()
            provider = provider_factory(settings) if provider_factory else default_provider(job['group'], settings)
            provider.client.max_retries = 0
            provider.client.chat.completions.create = LimitedRecordingCreate(
                provider.client.chat.completions.create, budget, job['api_calls'], secrets, checkpoint)
            tools = RecordingTools(database, job['tools'], secrets, checkpoint)
            result = await asyncio.wait_for(provider.analyze(context, tools, case['mode'], messages),
                                            timeout=ANALYSIS_TIMEOUT_SECONDS)
            job['output'] = result['output']
            job['raw_submission'] = raw_submission_from_calls(job['api_calls'])
            job['score'] = score(case, job['output'], job['raw_submission'])
            job['status'] = 'completed' if job['score']['output_valid'] else 'invalid'
        except BaseException as exc:
            job['status'] = 'failed'
            job['error'] = safe_error(exc, secrets)
            job['raw_submission'] = raw_submission_from_calls(job['api_calls'])
            job['score'] = failure_score(case, job.get('output'), job['raw_submission'])
            if isinstance(exc, (BudgetExceeded, GuardStopped)) or getattr(exc, 'status_code', None) in (401, 402, 403, 429):
                job['stop_reason'] = type(exc).__name__ if not getattr(exc, 'status_code', None) else f'http_{exc.status_code}'
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                job['stop_reason'] = 'interrupted'
                raise
        finally:
            job['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            if checkpoint:
                checkpoint()
            if provider:
                await provider.close()
    return job.get('stop_reason')


def live_settings():
    # 唯一读取凭据入口；仅 --live 分支调用，绝不读取 .env / key / 正式 data。
    return SimpleNamespace(llm_api_key=os.environ.get('LLM_API_KEY') or os.environ.get('OPENROUTER_API_KEY', ''),
        llm_model=os.environ.get('LLM_MODEL', ''), llm_base_url=os.environ.get('LLM_BASE_URL', 'https://openrouter.ai/api/v1'),
        agent_timeout_seconds=60, ai_ready=True)


def environment():
    packages = {}
    for name in ('openai', 'httpx', 'pydantic', 'SQLAlchemy', 'fastapi'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(), packages=packages)


def prepare_inputs(cases, jobs):
    for case in cases:
        with isolated_state(case) as database:
            context, messages = inputs(case, database)
        visible = common_input(case, context, messages)
        for job in jobs:
            if job['case_id'] == case['id']:
                job.update(common_input=deepcopy(visible), common_input_sha256=fingerprint(visible))


def _validate_saved_job(job, expected):
    """快照必须属于冻结计划和同一个真实序列化输入。"""
    if not isinstance(job, dict) or not set(expected) <= set(job):
        raise GuardStopped('保存的逐项快照缺少必要字段')
    for field in ('job_id', 'case_id', 'group', 'repetition', 'common_input_sha256'):
        if type(job[field]) is not type(expected[field]) or job[field] != expected[field]:
            raise GuardStopped('保存的逐项快照身份或输入 SHA 不匹配')
    if job['common_input'] != expected['common_input'] or fingerprint(job['common_input']) != job['common_input_sha256']:
        raise GuardStopped('保存的逐项快照输入内容或 SHA 不匹配')
    if job['status'] not in ('not_run', 'running', 'completed', 'invalid', 'failed'):
        raise GuardStopped('保存的逐项快照状态无效')
    for field, immutable in (('api_calls', ('sequence', 'request')), ('tools', ('name', 'arguments'))):
        entries = job[field]
        if not isinstance(entries, list) or any(not isinstance(entry, dict) or
                not set(immutable) <= set(entry) for entry in entries):
            raise GuardStopped('保存的请求或工具记录格式无效')
    sequences = [entry['sequence'] for entry in job['api_calls']]
    if any(type(number) is not int or number < 1 for number in sequences) or any(
            left >= right for left, right in zip(sequences, sequences[1:])):
        raise GuardStopped('保存的真实请求序号无效')
    if any(not isinstance(entry['request'], dict) for entry in job['api_calls']) or any(
            not isinstance(entry['name'], str) or not isinstance(entry['arguments'], dict) for entry in job['tools']):
        raise GuardStopped('保存的请求或工具参数格式无效')
    if job['status'] == 'not_run' and (job['api_calls'] or job['tools'] or job['output'] is not None or job['score'] is not None):
        raise GuardStopped('未运行快照包含执行证据')
    if job['status'] in ('completed', 'invalid', 'failed') and not isinstance(job['score'], dict):
        raise GuardStopped('终态快照缺少已保存评分')
    if job['status'] == 'completed' and (job['output'] is None or job['score'].get('output_valid') is not True):
        raise GuardStopped('已完成快照缺少有效公共提交')


def _require_evidence_extension(older, newer, immutable):
    if len(newer) < len(older):
        raise GuardStopped('逐项快照的真实请求或工具前缀发生回退')
    for before, after in zip(older, newer):
        if any(before[field] != after[field] for field in immutable):
            raise GuardStopped('逐项快照的真实请求或工具前缀冲突')
        for field, value in before.items():
            if field not in after or (value is not None and value != after[field]):
                raise GuardStopped('逐项快照冲突或丢失已知响应、用量或工具结果')


def _require_job_extension(older, newer):
    allowed = {'not_run': {'not_run', 'running', 'completed', 'invalid', 'failed'},
        'running': {'running', 'completed', 'invalid', 'failed'}}
    if newer['status'] not in allowed.get(older['status'], {older['status']}):
        raise GuardStopped('逐项快照状态发生冲突或回退')
    for field, value in older.items():
        if field not in newer:
            raise GuardStopped('逐项快照丢失已保存字段')
        if field == 'api_calls':
            _require_evidence_extension(value, newer[field], ('sequence', 'request'))
        elif field == 'tools':
            _require_evidence_extension(value, newer[field], ('name', 'arguments'))
        elif field != 'status' and value is not None and value != newer[field]:
            raise GuardStopped('逐项快照存在已知字段冲突')


def recover_saved_jobs(output_dir, manifest, jobs, cases):
    """attempt 先于 records 提交；仅接受身份一致且证据单调扩展的逐项快照。"""
    if (not isinstance(jobs, list) or manifest['case_ids'] != [case['id'] for case in cases] or
            len(set(manifest['case_ids'])) != len(cases) or not manifest['groups'] or
            len(set(manifest['groups'])) != len(manifest['groups']) or
            not set(manifest['groups']) <= set(GROUPS) or
            type(manifest['repetitions']) is not int or manifest['repetitions'] < 1):
        raise GuardStopped('保存的计划或样例身份无效')
    expected_jobs = make_jobs(cases, tuple(manifest['groups']), manifest['repetitions'], manifest['seed'])
    prepare_inputs(cases, expected_jobs)
    expected = {job['job_id']: job for job in expected_jobs}
    if (any(not isinstance(job, dict) or not isinstance(job.get('job_id'), str) for job in jobs) or
            len(jobs) != len(expected) or {job['job_id'] for job in jobs} != set(expected)):
        raise GuardStopped('保存的完整计划身份不匹配或重复')
    attempts = {path.stem: path for path in (output_dir / 'attempts').glob('*.json')}
    if not set(attempts) <= set(expected):
        raise GuardStopped('发现不属于保存计划的逐项快照文件')
    recovered = []
    for job in jobs:
        identity = expected[job['job_id']]
        _validate_saved_job(job, identity)
        candidate = job
        if job['job_id'] in attempts:
            try:
                candidate = json.loads(attempts[job['job_id']].read_text(encoding='utf-8'))
            except (OSError, ValueError, UnicodeError):
                raise GuardStopped('逐项快照无法完整读取；保留文件等待复核') from None
            _validate_saved_job(candidate, identity)
            _require_job_extension(job, candidate)
        recovered.append(deepcopy(candidate))
    sequences = [entry['sequence'] for job in recovered for entry in job['api_calls']]
    if len(sequences) != len(set(sequences)):
        raise GuardStopped('不同逐项快照的真实请求序号重复')
    if (recovered != jobs or any(job['status'] == 'running' for job in recovered)) and protocol_hash() != manifest['protocol_sha256']:
        raise GuardStopped('恢复中断须使用该轮冻结源码')
    return recovered


def summarize_saved(output_dir):
    manifest = json.loads((output_dir / 'manifest.json').read_text(encoding='utf-8'))
    jobs = json.loads((output_dir / 'records.json').read_text(encoding='utf-8'))
    cases = json.loads((output_dir / 'cases.json').read_text(encoding='utf-8'))
    if fingerprint(cases) != manifest['cases_sha256']:
        raise GuardStopped('保存的样例/标签 SHA 不匹配')
    # 先验证整轮全部快照，任何身份/证据冲突都在修改文件前停止。
    jobs = recover_saved_jobs(output_dir, manifest, jobs, cases)
    interrupted = []
    for job in jobs:
        if job['status'] == 'running':
            job.update(status='failed', error=job.get('error') or dict(type='InterruptedAnalysis', status_code=None,
                message='进程中断；保留真实请求且不补造未返回响应'))
            case = next(c for c in cases if c['id'] == job['case_id'])
            job['raw_submission'] = raw_submission_from_calls(job['api_calls'])
            job['score'] = failure_score(case, job.get('output'), job['raw_submission'])
            interrupted.append(job)
    for job in interrupted:
        write_json(output_dir / 'attempts' / (job['job_id'] + '.json'), job)
    # 其他终态只聚合已有 score，不重新评分，不访问环境或网络。
    refresh_summary(output_dir, manifest, jobs)
    return 0


async def run(args):
    if args.repetitions < 1 or not 1 <= args.max_calls <= 180 or not args.groups or len(args.groups) != len(set(args.groups)):
        raise GuardStopped('请求预算或重复/组参数不符合冻结协议')
    output_dir = Path(args.output_dir).resolve()
    if output_dir == ROOT / 'baseline' or ROOT / 'baseline' in output_dir.parents:
        raise GuardStopped('baseline 归档目录只读')
    if output_dir == ROOT or (ROOT.parent in output_dir.parents and ROOT not in output_dir.parents):
        raise GuardStopped('结果不能写入旧 experiments 或新源码根目录')
    if args.summarize:
        return summarize_saved(output_dir)
    if args.freeze:
        lock_path = Path(args.freeze_lock).resolve()
        if lock_path.parent != ROOT:
            raise GuardStopped('新冻结锁必须位于 reliability_v3 本目录')
        write_json(lock_path, freeze_value())
        print('独立 v3 冻结锁已生成；真实调用尚未开始。')
        return 0
    if (output_dir / 'manifest.json').exists():
        raise GuardStopped('目录已有实验记录，请选新目录或 --summarize')
    cases = frozen_cases(args.split)
    jobs = make_jobs(cases, tuple(args.groups), args.repetitions, args.seed)
    prepare_inputs(cases, jobs)
    manifest = dict(version=VERSION, run_mode='live' if args.live else 'dry_run', split=args.split,
        groups=args.groups, case_ids=[c['id'] for c in cases], repetitions=args.repetitions, seed=args.seed, max_calls=args.max_calls,
        worst_case_model_requests=len(jobs) * MAX_REQUESTS_PER_ANALYSIS,
        cases_sha256=fingerprint(cases), protocol_sha256=protocol_hash(), source_sha256=source_hashes(),
        baseline_sha256=verify_baseline(), temperature=0.2, per_analysis_timeout_seconds=60,
        max_requests_per_analysis=6, max_retries=0, response_schema=AgentOutput.model_json_schema(),
        environment=environment(), model=None, base_url=None, freeze=None, preflight=None, stop_reason=None,
        comparison_scope='同一完整初始上下文/消息；版本提示和工具能力的整体方案差异，不能推断纯工具因果效应')
    (output_dir / 'attempts').mkdir(parents=True, exist_ok=True)
    write_json(output_dir / 'cases.json', cases)
    write_json(output_dir / 'manifest.json', manifest)
    refresh_summary(output_dir, manifest, jobs)
    if not args.live:
        print(f'离线计划：{len(cases)} 个样例、{len(jobs)} 项，模型请求 0 次。')
        return 0
    settings = live_settings()
    secrets = (settings.llm_api_key,)
    try:
        manifest['freeze'] = verify_freeze(Path(args.freeze_lock))
        manifest.update(model=settings.llm_model, base_url=settings.llm_base_url)
        manifest['preflight'] = await preflight(settings, args.max_calls)
        budget = Budget(manifest['preflight']['effective_max_calls'])
    except Exception as exc:
        manifest.update(stop_reason='preflight_stopped', error=safe_error(exc, secrets))
        write_json(output_dir / 'manifest.json', manifest, secrets)
        refresh_summary(output_dir, manifest, jobs)
        print('零价或冻结预检未通过；完整计划与停止原因已保存，模型请求 0 次。')
        return 2
    try:
        for job in jobs:
            if budget.used >= budget.limit:
                manifest['stop_reason'] = 'global_or_free_quota_exhausted'
                break
            case = next(c for c in cases if c['id'] == job['case_id'])
            def checkpoint():
                try:
                    write_json(output_dir / 'attempts' / (job['job_id'] + '.json'), job, secrets)
                    write_json(output_dir / 'records.json', jobs, secrets)
                    write_json(output_dir / 'manifest.json', manifest, secrets)
                except OSError:
                    budget.limit = budget.used
                    raise
            stop = await execute_job(job, case, settings, budget, checkpoint)
            if stop:
                manifest['stop_reason'] = stop
                break
    except BaseException as exc:
        manifest.update(stop_reason='interrupted', error=safe_error(exc, secrets))
        raise
    finally:
        write_json(output_dir / 'manifest.json', manifest, secrets)
        refresh_summary(output_dir, manifest, redacted(jobs, secrets))
    print('真实记录已保存；以 summary.json 的完整性和平衡标志决定能否比较。')
    return 0 if all(j['status'] != 'not_run' for j in jobs) else 2


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--summarize', action='store_true')
    mode.add_argument('--freeze', action='store_true')
    result.add_argument('--split', choices=('dev', 'eval', 'all'), default='eval')
    result.add_argument('--groups', nargs='+', choices=GROUPS, default=list(GROUPS))
    result.add_argument('--repetitions', type=int, default=2)
    result.add_argument('--seed', type=int, default=20261020)
    result.add_argument('--max-calls', type=int, default=180)
    result.add_argument('--output-dir', default=str(ROOT / 'results' / 'dry-run'))
    result.add_argument('--freeze-lock', default=str(ROOT / 'freeze.json'))
    return result


def main():
    args = parser().parse_args()
    if args.repetitions < 1 or not 1 <= args.max_calls <= 180 or len(args.groups) != len(set(args.groups)):
        parser().error('repetitions须为正数、max-calls须为1至180、groups不可重复')
    try:
        return asyncio.run(run(args))
    except (GuardStopped, OSError, ValueError, RuntimeError) as exc:
        print(f'实验未完成：{type(exc).__name__}；请检查安全的记录文件。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
