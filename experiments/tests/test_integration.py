"""历史 v2 工具循环的真实 SDK 本地边界回归；v3 另有独立协议测试。"""
import asyncio
import json
from types import SimpleNamespace
import httpx
from openai import AsyncOpenAI
import pytest
from experiments import runner
from experiments.reliability_v3.backend import baseline_provider_module
from experiments.cases import frozen_cases
from experiments.tests.test_cases import labelled_output
from experiments.transport import Budget

# 该文件的原 JSON/查询往返 fixture 对应 v2，不用旧 fixture 要求新版跳过事实关卡。
# 归档源码与共用规则依赖在加载时核对 SHA；旧标签、评分和结果不修改。
OpenAIProvider = baseline_provider_module().OpenAIProvider


def settings():
    return SimpleNamespace(llm_model='frozen/model:free', llm_api_key='local-test-only-key',
        llm_base_url='https://openrouter.ai/api/v1', agent_timeout_seconds=60, ai_ready=True)


def install_local_provider(monkeypatch, handler):
    def factory(config):
        offline_config = SimpleNamespace(**vars(config))
        offline_config.ai_ready = False
        provider = OpenAIProvider(offline_config)
        provider.client = AsyncOpenAI(api_key=config.llm_api_key, base_url=config.llm_base_url,
            max_retries=0, timeout=60, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return provider
    monkeypatch.setattr(runner, 'OpenAIProvider', factory)


def response(message, usage=None):
    return httpx.Response(200, json=dict(id='local-unit-response', object='chat.completion', created=1792108800,
        model='frozen/model:free', choices=[dict(index=0, message=message, finish_reason='stop')], usage=usage))


@pytest.mark.parametrize('group', ['chat_only', 'context_only', 'agent'])
def test_real_sdk_records_single_baselines_and_production_tool_loop(monkeypatch, group):
    case = frozen_cases()[0]
    gold = labelled_output(case)
    seen = []
    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body['model'] == 'frozen/model:free'
        assert body['temperature'] == 0.2
        assert 'response_format' not in body
        assert body['provider']['max_price']['completion'] == '0'
        if group == 'agent' and len(seen) == 1:
            return response(dict(role='assistant', content=None, tool_calls=[dict(id='local-tool', type='function',
                function=dict(name='check_plan', arguments=json.dumps({'tasks': gold['tasks']})))]))
        return response(dict(role='assistant', content=json.dumps(gold, ensure_ascii=False)),
            usage=dict(prompt_tokens=10, completion_tokens=5, total_tokens=15, cost=0))
    install_local_provider(monkeypatch, handle)
    job = runner.make_jobs([case], [group], 1, 0)[0]
    budget = Budget(6)
    stop = asyncio.run(runner.execute_job(job, case, settings(), budget))
    assert stop is None
    assert job['status'] == 'completed' and job['score']['success']
    assert len(job['api_calls']) == budget.used == (2 if group == 'agent' else 1)
    assert all('local-test-only-key' not in str(c) for c in job['api_calls'])
    if group == 'agent':
        assert seen[0]['tools']
        assert job['tools'][0]['name'] == 'check_plan'
        assert job['tools'][0]['arguments']['tasks'] == gold['tasks']
        assert job['tools'][0]['result']['valid']
        assert job['api_calls'][0]['usage'] is None
    else:
        assert 'tools' not in seen[0]


def test_budget_exhaustion_inside_agent_keeps_real_partial_request_and_score_failure(monkeypatch):
    case = frozen_cases()[0]
    def handle(request):
        return response(dict(role='assistant', content=None, tool_calls=[dict(id='query', type='function',
            function=dict(name='get_tasks', arguments='{}'))]))
    install_local_provider(monkeypatch, handle)
    job = runner.make_jobs([case], ['agent'], 1, 0)[0]
    stop = asyncio.run(runner.execute_job(job, case, settings(), Budget(1)))
    assert stop == 'BudgetExceeded'
    assert job['status'] == 'failed'
    assert len(job['api_calls']) == 1
    assert job['api_calls'][0]['response']['id'] == 'local-unit-response'
    assert job['tools'][0]['result'][0]['existing_id'] == 201
    assert job['score']['extraction']['fn'] > 0


def test_dryrun_and_no_network_summary_keep_not_run_separate(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('dry-run 不得读取凭据或初始化真实模型')
    monkeypatch.setattr(runner, 'OpenAIProvider', forbidden)
    original_get = runner.os.environ.get
    def guarded_get(key, *args, **kwargs):
        if key in ('LLM_API_KEY', 'OPENROUTER_API_KEY', 'JWT_SECRET'):
            return forbidden()
        return original_get(key, *args, **kwargs)
    monkeypatch.setattr(runner.os.environ, 'get', guarded_get)
    args = runner.parser().parse_args(['--split', 'eval', '--repetitions', '2', '--output-dir', str(tmp_path)])
    assert asyncio.run(runner.run(args)) == 0
    summary = json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8'))
    records = json.loads((tmp_path / 'records.json').read_text(encoding='utf-8'))
    assert summary['comparison_complete'] is False
    assert summary['ranking_permitted'] is False
    assert summary['coverage_by_group'] == {'chat_only': 0, 'context_only': 0, 'agent': 0}
    assert summary['model_requests'] == 0
    assert len(records) == 60 and all(j['status'] == 'not_run' and j['score'] is None for j in records)
    records[0].update(status='running', api_calls=[{'request': {}, 'response': {'id': 'partial-actual-response'},
        'cost_usd': None, 'usage': None}])
    (tmp_path / 'records.json').write_text(json.dumps(records), encoding='utf-8')
    args = runner.parser().parse_args(['--summarize', '--output-dir', str(tmp_path)])
    assert asyncio.run(runner.run(args)) == 0
    recovered = json.loads((tmp_path / 'records.json').read_text(encoding='utf-8'))
    summary = json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8'))
    assert recovered[0]['status'] == 'failed'
    assert recovered[0]['error']['type'] == 'InterruptedAnalysis'
    assert recovered[0]['api_calls'][0]['response']['id'] == 'partial-actual-response'
    assert summary['attempted'] == 1 and summary['model_requests'] == 1
    assert not summary['comparison_complete'] and not summary['comparison_balanced']
