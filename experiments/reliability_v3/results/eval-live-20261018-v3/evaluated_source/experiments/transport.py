"""真实接口边界：请求级预算、零价预检、脱敏记录；单元测试可注入 HTTP 传输。"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re
import time
from urllib.parse import urlsplit
import httpx
from .backend import ProjectTools

ZERO_ROUTING = {'provider': {'allow_fallbacks': False,
    'max_price': {'prompt': '0', 'completion': '0', 'request': '0', 'image': '0', 'audio': '0'}}}


class BudgetExceeded(RuntimeError):
    pass


class GuardStopped(RuntimeError):
    pass


@dataclass
class Budget:
    limit: int
    used: int = 0

    def consume(self):
        if self.used >= self.limit:
            raise BudgetExceeded('全局模型请求预算已用完')
        self.used += 1


def redacted(value, secrets=()):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if str(k).lower() in ('authorization', 'api_key', 'jwt_secret', 'access_token', 'refresh_token')
                    else redacted(v, secrets)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redacted(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(?i)Bearer\s+[^\s"\'<>]+', 'Bearer [REDACTED]', value)
        value = re.sub(r'\bsk-[a-zA-Z0-9_-]+', '[REDACTED]', value)
        value = re.sub(r'\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+', '[REDACTED]', value)
    return value


def safe_error(exc, secrets=()):
    return dict(type=type(exc).__name__, status_code=getattr(exc, 'status_code', None),
                message=redacted(str(exc), secrets))


def actual_cost(usage):
    value = usage.get('cost') if isinstance(usage, dict) else None
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


class RecordingCreate:
    def __init__(self, create, budget, calls, secrets=(), checkpoint=None):
        self.create, self.budget, self.calls, self.secrets = create, budget, calls, secrets
        self.checkpoint = checkpoint

    async def __call__(self, **kwargs):
        self.budget.consume()  # 每一个 HTTP 模型请求（包括异常）均消耗全局预算。
        request = deepcopy(kwargs)
        request['extra_body'] = deepcopy(ZERO_ROUTING)
        entry = dict(sequence=self.budget.used, request=redacted(request, self.secrets), response=None,
                     usage=None, cost_usd=None, error=None, elapsed_ms=None)
        self.calls.append(entry)
        started = time.monotonic()
        try:
            if self.checkpoint:
                self.checkpoint()  # 先记下已分配预算的请求，再交由 SDK 发送。
            response = await self.create(**request)
            raw = response.model_dump(mode='json')
            entry['response'] = redacted(raw, self.secrets)
            entry['usage'] = redacted(raw.get('usage'), self.secrets)
            entry['cost_usd'] = actual_cost(entry['usage'])
            if entry['cost_usd'] is not None and entry['cost_usd'] > 0:
                raise GuardStopped('接口报告非零费用，已停止后续模型请求')
            return response
        except BaseException as exc:
            entry['error'] = safe_error(exc, self.secrets)
            raise
        finally:
            entry['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            if self.checkpoint:
                self.checkpoint()


class RecordingTools(ProjectTools):
    def __init__(self, database, journal, secrets=(), checkpoint=None):
        super().__init__(database, 1)
        self.journal, self.secrets = journal, secrets
        self.checkpoint = checkpoint

    def execute(self, name, arguments):
        entry = dict(name=name, arguments=redacted(arguments, self.secrets), result=None, error=None)
        self.journal.append(entry)
        try:
            result = super().execute(name, arguments)
            entry['result'] = redacted(result, self.secrets)
            return result
        except Exception as exc:
            entry['error'] = safe_error(exc, self.secrets)
            raise
        finally:
            if self.checkpoint:
                self.checkpoint()


def validate_preflight(model, models_data, key_data, requested_limit):
    found = next((m for m in models_data.get('data', []) if m.get('id') == model), None)
    if found is None:
        raise GuardStopped('所选模型未出现在当前模型目录；不会自动换模型')
    pricing = found.get('pricing')
    if not isinstance(pricing, dict) or not {'prompt', 'completion'} <= set(pricing):
        raise GuardStopped('当前模型价格信息不足')
    try:
        if any(not Decimal(str(v)).is_finite() or Decimal(str(v)) != 0 for v in pricing.values()):
            raise GuardStopped('所选模型当前存在非零或未知价格')
    except (InvalidOperation, TypeError, ValueError):
        raise GuardStopped('当前模型价格不可核验') from None
    key = key_data.get('data', {})
    quota = key.get('free_model_daily_requests', {})
    remaining = quota.get('remaining')
    if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining <= 0:
        raise GuardStopped('免费模型剩余请求额度未知或已经耗尽')
    credit = key.get('limit_remaining')
    if key.get('limit') is not None and (credit is None or Decimal(str(credit)) <= 0):
        raise GuardStopped('API Key 剩余美元限额不足或未知')
    snapshot = dict(model=model, pricing=pricing,
        key=dict(limit=key.get('limit'), limit_remaining=credit, is_free_tier=key.get('is_free_tier'),
                 free_model_daily_requests={k: quota.get(k) for k in ('limit', 'remaining', 'used')}),
        effective_max_calls=min(requested_limit, remaining),
        sources=['https://openrouter.ai/api/v1/models', 'https://openrouter.ai/api/v1/key'])
    return snapshot


async def preflight(settings, requested_limit, transport=None):
    url = urlsplit(settings.llm_base_url)
    if url.scheme != 'https' or url.netloc != 'openrouter.ai' or url.path.rstrip('/') != '/api/v1' or url.query or url.fragment:
        raise GuardStopped('真实实验仅允许 https://openrouter.ai/api/v1')
    if not settings.llm_api_key or not settings.llm_model:
        raise GuardStopped('需要进程环境提供 LLM_API_KEY（或 OPENROUTER_API_KEY）与 LLM_MODEL')
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=transport) as client:
        models = await client.get('https://openrouter.ai/api/v1/models')
        models.raise_for_status()
        key = await client.get('https://openrouter.ai/api/v1/key', headers={'Authorization': 'Bearer ' + settings.llm_api_key})
        key.raise_for_status()
        return validate_preflight(settings.llm_model, models.json(), key.json(), requested_limit)
