import asyncio
from types import SimpleNamespace
import httpx
import pytest
from experiments.transport import (Budget, BudgetExceeded, GuardStopped, RecordingCreate,
    actual_cost, preflight, redacted, validate_preflight)


class RawResponse:
    def __init__(self, raw):
        self.raw = raw

    def model_dump(self, **kwargs):
        return self.raw


def models(price='0'):
    return {'data': [{'id': 'frozen/model:free', 'pricing': {'prompt': price, 'completion': '0', 'request': '0'}}]}


def key(remaining=50):
    return {'data': {'limit': None, 'limit_remaining': None, 'label': 'never-save-this-label',
                     'free_model_daily_requests': {'limit': 50, 'remaining': remaining, 'used': 0}}}


def test_null_usage_and_cost_stay_unknown_and_budget_counts_actual_requests():
    seen, calls = [], []
    async def create(**kwargs):
        seen.append(kwargs)
        return RawResponse({'id': 'test-only', 'usage': None})
    budget = Budget(2)
    wrapped = RecordingCreate(create, budget, calls)
    asyncio.run(wrapped(model='frozen/model:free', messages=[], temperature=0.2))
    asyncio.run(wrapped(model='frozen/model:free', messages=[], temperature=0.2))
    with pytest.raises(BudgetExceeded):
        asyncio.run(wrapped(model='frozen/model:free'))
    assert budget.used == len(seen) == len(calls) == 2
    assert all(c['usage'] is None and c['cost_usd'] is None for c in calls)
    assert all('tools' not in c and 'response_format' not in c for c in seen)
    assert seen[0]['extra_body']['provider']['allow_fallbacks'] is False
    assert seen[0]['extra_body']['provider']['max_price']['prompt'] == '0'


def test_request_error_is_counted_and_secret_redacted():
    calls = []
    async def create(**kwargs):
        raise RuntimeError('Bearer unit-secret custom-unit-key sk-or-v1-test')
    wrapped = RecordingCreate(create, Budget(1), calls, ('custom-unit-key',))
    with pytest.raises(RuntimeError):
        asyncio.run(wrapped(model='frozen/model:free'))
    assert len(calls) == 1 and calls[0]['response'] is None
    assert 'unit-secret' not in str(calls)
    assert 'custom-unit-key' not in str(calls)
    assert 'sk-or-v1-test' not in str(calls)


@pytest.mark.parametrize('usage', [None, {}, {'cost': None}, {'cost': 'nan'}, {'cost': True}])
def test_missing_or_invalid_cost_is_null(usage):
    assert actual_cost(usage) is None


def test_nonzero_real_cost_stops_without_losing_raw_response():
    calls = []
    async def create(**kwargs):
        return RawResponse({'usage': {'total_tokens': 3, 'cost': 0.01}})
    wrapped = RecordingCreate(create, Budget(1), calls)
    with pytest.raises(GuardStopped):
        asyncio.run(wrapped(model='frozen/model:free'))
    assert calls[0]['cost_usd'] == 0.01
    assert calls[0]['response']['usage']['total_tokens'] == 3


def test_zero_price_quota_snapshot_drops_labels_and_caps_effective_budget():
    result = validate_preflight('frozen/model:free', models(), key(37), 180)
    assert result['effective_max_calls'] == 37
    assert 'label' not in str(result)
    assert result['key']['limit_remaining'] is None


@pytest.mark.parametrize(('model', 'prices', 'quota'), [
    ('missing', models(), key()), ('frozen/model:free', models('0.01'), key()),
    ('frozen/model:free', models(), key(None)), ('frozen/model:free', models(), key(0))])
def test_unknown_model_paid_price_and_unknown_or_exhausted_quota_stop(model, prices, quota):
    with pytest.raises(GuardStopped):
        validate_preflight(model, prices, quota, 180)


def test_preflight_only_calls_metadata_endpoints_and_never_returns_auth():
    seen = []
    def handle(request):
        seen.append(request.url.path)
        if request.url.path.endswith('/models'):
            assert 'authorization' not in request.headers
            return httpx.Response(200, json=models())
        assert request.headers['authorization'] == 'Bearer metadata-test-secret'
        return httpx.Response(200, json=key())
    settings = SimpleNamespace(llm_model='frozen/model:free', llm_api_key='metadata-test-secret',
        llm_base_url='https://openrouter.ai/api/v1')
    snapshot = asyncio.run(preflight(settings, 180, httpx.MockTransport(handle)))
    assert seen == ['/api/v1/models', '/api/v1/key']
    assert 'metadata-test-secret' not in str(snapshot)


def test_recursive_redaction_handles_jwt_and_headers():
    value = redacted({'Authorization': 'Bearer test', 'nested': ['eyJhbGci.eyJzdWI.signature']})
    assert value['Authorization'] == '[REDACTED]'
    assert value['nested'] == ['[REDACTED]']


def test_checkpoints_persist_prepared_request_before_sdk_and_final_response():
    calls, checkpoints = [], []
    async def create(**kwargs):
        assert checkpoints == [(1, None)]
        return RawResponse({'id': 'unit-checkpoint', 'usage': None})
    def checkpoint():
        checkpoints.append((len(calls), calls[0]['response']))
    wrapped = RecordingCreate(create, Budget(1), calls, checkpoint=checkpoint)
    asyncio.run(wrapped(model='frozen/model:free'))
    assert checkpoints[-1] == (1, {'id': 'unit-checkpoint', 'usage': None})
