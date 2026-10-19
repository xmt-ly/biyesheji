"""隔离的 SDK 协议与来源事实回归，不访问真实模型或正式数据库。"""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from test_contract import env, headers, project, task_draft


class Reply:
    def __init__(self, content=None, calls=None):
        self.content, self.tool_calls = content, calls

    def model_dump(self, **kwargs):
        return {'role': 'assistant', 'content': self.content, 'tool_calls': [
            {'id': c.id, 'type': 'function', 'function': {'name': c.function.name,
             'arguments': c.function.arguments}} for c in self.tool_calls or []]}


def call(name, arguments, identifier='call1'):
    return SimpleNamespace(id=identifier, function=SimpleNamespace(
        name=name, arguments=arguments if isinstance(arguments, str) else json.dumps(arguments)))


class ScriptedChat:
    def __init__(self, replies, unknown_usage=False):
        self.replies, self.requests, self.unknown_usage = list(replies), [], unknown_usage

    async def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        assert self.replies, '不应增加额外模型请求'
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        usage = None if self.unknown_usage else SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(message=response)])


class SnapshotTools:
    def __init__(self, context, valid=True):
        self.context, self.calls, self.valid = context, [], valid

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        if name == 'get_project_context':
            return self.context
        if name == 'get_tasks':
            return self.context['tasks']
        if name == 'check_plan':
            return {'valid': self.valid, 'violations': []}
        raise ValueError('未知工具')


def provider(chat):
    from app.agent import OpenAIProvider
    from app.config import Settings
    result = OpenAIProvider(Settings(llm_api_key='', llm_model='fake-model'))
    result.client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    return result


def draft(**changes):
    value = dict(key='new_export', existing_id=None, title='导出校验', description='', requirement_id=1,
                 acceptance='校验和正确', assignee_id=2, estimated_hours=2, remaining_hours=2,
                 dependencies=[], start_date='2026-10-17', due_date='2026-10-19', status='todo',
                 progress=0, artifact_url='', blocker='', stage_index=2)
    return dict(value, **changes)


def analysis(tasks=None, **changes):
    return dict(dict(kind='plan', title='草案', summary='讨论结果', questions=[], source_message_ids=[10],
                     tasks=[] if tasks is None else tasks, supersedes_card_ids=[]), **changes)


def context(tasks=None, cards=None):
    return {'project': {'id': 1}, 'course': {}, 'requirements': [],
            'members': [{'user_id': 2, 'name': '小王', 'skills': ['导出'], 'weekly_hours': 10}],
            'tasks': tasks or [], 'pending_cards': cards or []}


def message(content='小王负责导出校验，预计两小时，今天开始，后天截止。', **changes):
    return dict(dict(id=10, kind='human', content=content, user_id=2,
                     created_at='2026-10-16T16:30:00+00:00'), **changes)


def evidence(content=None):
    quote = content or message()['content']
    return [{'task_key': 'new_export', 'field': f, 'message_id': 10, 'quote': quote}
            for f in ['assignee_id', 'estimated_hours', 'start_date', 'due_date']]


def prepare(value, ctx=None, msgs=None, facts=None):
    from app.agent_output import prepare_agent_output
    return prepare_agent_output(value, context() if ctx is None else ctx,
                                [message()] if msgs is None else msgs, facts or [])


def test_one_finalize_reuses_snapshot_and_returns_without_extra_model_request():
    value = analysis([draft()])
    chat = ScriptedChat([Reply(calls=[call('finalize_analysis', {'analysis': value, 'task_evidence': evidence()})])])
    tools = SnapshotTools(context())
    result = asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))
    assert result['output']['tasks'] == [draft()]
    assert result['tokens']['total_tokens'] == 15
    assert len(chat.requests) == 1
    assert {t['function']['name'] for t in chat.requests[0]['tools']} == {'check_plan', 'finalize_analysis'}
    assert tools.calls == [('check_plan', {'tasks': [draft()]})]


def test_no_e02_invention_and_bare_json_also_asks_four_concrete_questions():
    msgs = [message('导出需要校验和，验收时再确认。')]
    result = prepare(analysis([draft()]), msgs=msgs)
    assert result['tasks'] == []
    assert all(any(label in q for q in result['questions']) for label in ['负责人', '工时', '开始', '截止'])
    chat = ScriptedChat([Reply(content=json.dumps(analysis([draft()])))])
    result = asyncio.run(provider(chat).analyze(context(), SnapshotTools(context()), 'plan', msgs))
    assert result['output']['tasks'] == []


@pytest.mark.parametrize('change', [dict(message_id=11), dict(quote='小王负责，2小时，2026-10-17开始，2026-10-19截止')])
def test_forged_quote_and_unreferenced_message_do_not_support_new_task(change):
    facts = evidence()
    facts[0].update(change)
    result = prepare(analysis([draft()]), msgs=[message(), message(id=11)], facts=facts)
    assert result['tasks'] == []
    assert any('负责人' in q for q in result['questions'])


@pytest.mark.parametrize('text,hours,start,end', [
    ('我来负责导出校验，预计两个小时，今天开始，后天截止。', 2, '2026-10-17', '2026-10-19'),
    ('小王负责导出校验，预计一个半小时，2026年10月17日到2026年10月19日。', 1.5, '2026-10-17', '2026-10-19'),
    ('小王负责导出校验，预计半小时，明天开始，后天完成。', .5, '2026-10-18', '2026-10-19'),
    ('小王负责导出校验，预计2小时，2026-10-17至2026-10-19。', 2, '2026-10-17', '2026-10-19'),
    ('小王负责导出校验，预计两小时，10月22日开始、23日交付。', 2, '2026-10-22', '2026-10-23'),
    ('小王负责导出校验，预计两小时，11月22日至23日。', 2, '2026-11-22', '2026-11-23'),
    ('小王负责导出校验，预计两小时，22日到23日。', 2, '2026-10-22', '2026-10-23'),
])
def test_real_quotes_support_self_nomination_chinese_hours_and_shanghai_dates(text, hours, start, end):
    value = draft(estimated_hours=hours, remaining_hours=hours, start_date=start, due_date=end)
    assert prepare(analysis([value]), msgs=[message(text)], facts=evidence(text))['tasks'] == [value]


@pytest.mark.parametrize('text', [
    '如果小王负责导出校验，预计两小时，今天开始，后天截止。',
    '小王不负责导出校验，预计两小时，今天开始，后天截止。',
    '小王负责导出校验，预计两小时，下周开始，下下周截止。',
    '不由小王负责导出校验，预计两小时，今天开始，后天截止。',
    '小王负责导出校验，预计1到2小时，今天开始，后天截止。',
])
def test_conditional_negative_or_ambiguous_dates_remain_questions(text):
    assert prepare(analysis([draft()]), msgs=[message(text)], facts=evidence(text))['tasks'] == []



@pytest.mark.parametrize('field,uncertain,clipped', [
    ('estimated_hours', '预计两小时或三小时', '预计两小时'),
    ('estimated_hours', '预计两小时到三小时', '预计两小时'),
    ('start_date', '今天开始或明天开始', '今天开始'),
    ('start_date', '开始日期是今天或明天', '开始日期是今天'),
])
@pytest.mark.parametrize('quote_mode', ['complete', 'clipped'])
def test_ambiguous_original_clause_cannot_be_hidden_by_clipping_quote(field, uncertain, clipped, quote_mode):
    text = message()['content'].replace('预计两小时' if field == 'estimated_hours' else '今天开始', uncertain)
    facts = evidence(text)
    next(fact for fact in facts if fact['field'] == field)['quote'] = text if quote_mode == 'complete' else clipped
    result = prepare(analysis([draft()]), msgs=[message(text)], facts=facts)
    assert result['tasks'] == []
    assert any(('工时' if field == 'estimated_hours' else '开始日期') in q for q in result['questions'])


@pytest.mark.parametrize('other_clause', ['另一个任务预计三小时，', '另一个任务明天开始，'])
def test_independent_other_task_clause_does_not_make_clear_quote_ambiguous(other_clause):
    text = other_clause + message()['content']
    assert prepare(analysis([draft()]), msgs=[message(text)], facts=evidence(message()['content']))['tasks'] == [draft()]



@pytest.mark.parametrize('text', [
    '小王负责登录功能，预计两小时，今天开始，后天截止。',
    '导出校验待确认。小王负责登录功能，预计两小时，今天开始，后天截止。',
    '导出校验待确认，小王负责登录功能，预计两小时，今天开始，后天截止。',
    '导出校验。登录功能，小王负责，预计两小时，今天开始，后天截止。',
])
def test_other_task_cannot_lend_commitments_even_after_target_task_was_mentioned(text):
    result = prepare(analysis([draft()]), msgs=[message(text)], facts=evidence(text))
    assert result['tasks'] == []
    assert all(any(label in q for q in result['questions']) for label in ['负责人', '工时', '开始', '截止'])


def test_new_task_title_must_preserve_the_explicit_source_task_name():
    assert prepare(analysis([draft(title='导出')]), facts=evidence())['tasks'] == []


@pytest.mark.parametrize('split_messages', [False, True])
def test_unique_explicit_previous_task_supports_self_nomination_and_followup_facts(split_messages):
    named = message('任务：导出校验。', id=9)
    nomination = message('这项我来做。')
    supplement = message('预计两小时，今天开始，后天截止。', id=11)
    if split_messages:
        msgs = [named, nomination, supplement]
        facts = [dict(fact, message_id=10 if fact['field'] == 'assignee_id' else 11,
                      quote=nomination['content'] if fact['field'] == 'assignee_id' else supplement['content'])
                 for fact in evidence()]
        value = analysis([draft()], source_message_ids=[9, 10, 11])
    else:
        text = named['content'] + nomination['content'] + supplement['content']
        msgs, facts, value = [message(text)], evidence(text), analysis([draft()])
    assert prepare(value, msgs=msgs, facts=facts)['tasks'] == [draft()]


@pytest.mark.parametrize('declaration', [
    '请新增导出校验', '需要新增导出校验', '结果导出需求下需要新增导出校验',
])
def test_explicit_new_task_declaration_keeps_owner_after_requirement_metadata(declaration):
    text = declaration + '，关联结果导出需求，小王负责，预计与剩余均两小时，今天开始、后天截止。验收是导出文件与页面一致。'
    assert prepare(analysis([draft()]), msgs=[message(text)], facts=evidence(text))['tasks'] == [draft()]


def test_task_metadata_keeps_unique_topic_for_next_message_self_nomination():
    title = '库存条目核对'
    named = message('资产目录需求下需要新增库存条目核对，依赖已完成的资产目录发布。'
                    '验收是盘点数量与目录一致，放在实现阶段。', id=9)
    nomination = message('这项我来做。预计两小时，剩余也两小时，今天开始，明天交付。')
    value = draft(title=title, due_date='2026-10-18')
    facts = evidence(nomination['content'])
    result = prepare(analysis([value], source_message_ids=[9, 10]),
                     msgs=[named, nomination], facts=facts)
    assert result['tasks'] == [value]


@pytest.mark.parametrize('prefix', [
    '关联导出需求，依赖已完成的导出前置。验收是导出内容正确，放在实现阶段。',
    '任务：导出校验。任务：登录功能。关联登录需求，依赖已完成的登录前置。验收是登录成功，放在实现阶段。',
    '新增导出校验或登录功能，关联导出需求，验收是数据正确，放在实现阶段。',
])
def test_metadata_does_not_create_or_restore_an_ambiguous_or_other_task_topic(prefix):
    text = prefix + '这项我来做。预计两小时，今天开始，后天截止。'
    result = prepare(analysis([draft()]), msgs=[message(text)], facts=evidence(text))
    assert result['tasks'] == []
    assert all(any(label in q for q in result['questions']) for label in ['负责人', '工时', '开始', '截止'])


def test_metadata_preserves_topic_without_supplying_new_task_commitment_facts():
    text = '任务：导出校验。验收是小王负责复查。预计两小时，今天开始，后天截止。'
    result = prepare(analysis([draft()]), msgs=[message(text)], facts=evidence(text))
    assert result['tasks'] == []
    assert any('负责人' in q for q in result['questions'])
    assert not any('工时' in q or '开始日期' in q or '截止日期' in q for q in result['questions'])


@pytest.mark.parametrize('split_messages', [False, True])
def test_another_explicit_task_cuts_previous_task_inheritance(split_messages):
    named = message('任务：导出校验。', id=9)
    text = '任务：登录功能。这项我来做，预计两小时，今天开始，后天截止。'
    msgs = [named, message(text)] if split_messages else [message(named['content'] + text)]
    value = analysis([draft()], source_message_ids=[9, 10] if split_messages else [10])
    facts = evidence(text if split_messages else msgs[0]['content'])
    result = prepare(value, msgs=msgs, facts=facts)
    assert result['tasks'] == []
    assert all(any(label in q for q in result['questions']) for label in ['负责人', '工时', '开始', '截止'])



def test_unreferenced_intervening_task_also_cuts_previous_task_inheritance():
    text = '这项我来做，预计两小时，今天开始，后天截止。'
    msgs = [message('任务：导出校验。', id=8), message('任务：登录功能。', id=9), message(text)]
    result = prepare(analysis([draft()], source_message_ids=[8, 10]), msgs=msgs, facts=evidence(text))
    assert result['tasks'] == []
    assert all(any(label in q for q in result['questions']) for label in ['负责人', '工时', '开始', '截止'])


@pytest.mark.parametrize('owners,clipped', [
    ('小王负责导出校验或小李负责导出校验', '小王负责导出校验'),
    ('小王负责导出校验还是小李负责导出校验', '小王负责导出校验'),
    ('由小王或小李二选一负责导出校验', '由小王'),
])
@pytest.mark.parametrize('quote_mode', ['complete', 'clipped'])
def test_owner_choices_in_original_clause_remain_questions_when_quote_is_clipped(owners, clipped, quote_mode):
    text = message()['content'].replace('小王负责导出校验', owners)
    facts = evidence(text)
    facts[0]['quote'] = text if quote_mode == 'complete' else clipped
    result = prepare(analysis([draft()]), msgs=[message(text)], facts=facts)
    assert result['tasks'] == []
    assert any('负责人' in q for q in result['questions'])


def test_missing_new_task_evidence_replaces_confident_model_title_and_summary():
    value = analysis([draft(estimated_hours=3, remaining_hours=3)],
                     title='导出校验3小时已排定', summary='已确定由小王负责导出校验，3小时已排定。')
    result = prepare(value, msgs=[message('导出校验需要讨论。')])
    assert result['tasks'] == []
    assert '待确认' in result['title'] and '保留原计划' in result['summary']
    assert all(term not in result['title'] + result['summary'] for term in ['小王', '3小时', '已确定', '已排定'])
    assert all(any(label in q for q in result['questions']) for label in ['负责人', '工时', '开始', '截止'])


def test_member_skill_capacity_and_adjacent_task_do_not_supply_facts():
    result = prepare(analysis([draft()]), context(tasks=[draft(key='task_4', existing_id=4)]),
                     [message('导出需要校验和，验收时再确认。')], evidence('导出需要校验和，验收时再确认。'))
    assert result['tasks'] == [] and len(result['questions']) >= 4


def test_remaining_hours_needs_own_evidence_when_different():
    value = draft(remaining_hours=1, status='doing', progress=50)
    assert prepare(analysis([value]), facts=evidence())['tasks'] == []
    text = message()['content'] + '剩余一小时。'
    facts = evidence(text) + [{'task_key': 'new_export', 'field': 'remaining_hours', 'message_id': 10, 'quote': '剩余一小时。'}]
    assert prepare(analysis([value]), msgs=[message(text)], facts=facts)['tasks'] == [value]


def test_hours_explicitly_shared_by_estimate_and_remaining_support_both_fields():
    text = '小王负责导出校验，预计与剩余均3小时，今天开始，后天截止。'
    value = draft(estimated_hours=3, remaining_hours=3, status='doing', progress=10)
    facts = evidence(text) + [{'task_key': value['key'], 'field': 'remaining_hours', 'message_id': 10, 'quote': text}]
    assert prepare(analysis([value]), msgs=[message(text)], facts=facts)['tasks'] == [value]


@pytest.mark.parametrize('prefix', ['请不要改已完成项。', '请不要改已完成项，'])
def test_unrelated_negative_sentence_or_clause_does_not_cancel_explicit_commitments(prefix):
    text = prefix + message()['content']
    assert prepare(analysis([draft()]), msgs=[message(text)], facts=evidence(text))['tasks'] == [draft()]


@pytest.mark.parametrize('prefix', ['如果', '若'])
def test_quote_cannot_cut_condition_out_of_the_actual_sentence(prefix):
    quote = message()['content']
    assert prepare(analysis([draft()]), msgs=[message(prefix + quote)], facts=evidence(quote))['tasks'] == []


def test_invalid_one_of_multiple_new_tasks_removes_entire_partial_plan():
    first, second = draft(), draft(key='new_unknown', title='未确定的新任务')
    assert prepare(analysis([first, second]), facts=evidence())['tasks'] == []


def test_old_card_requires_pending_supersedes_explicit_inheritance_and_equal_value():
    old = {'id': 3, 'tasks': [draft()], 'status': 'pending'}
    facts = [{'task_key': 'new_export', 'field': f, 'card_id': 3, 'source_task_key': 'new_export'}
             for f in ['assignee_id', 'estimated_hours', 'start_date', 'due_date']]
    value = analysis([draft()], supersedes_card_ids=[3])
    ctx = context(cards=[old])
    assert prepare(value, ctx, [message('导出校验任务负责人、工时和日期都照旧。')], facts)['tasks'] == [draft()]
    for bad_value, bad_ctx, bad_msgs in [
        (analysis([draft()]), ctx, [message('照旧')]),
        (value, context(), [message('照旧')]),
        (value, ctx, [message('导出需要校验和。')]),
        (analysis([draft(estimated_hours=3)], supersedes_card_ids=[3]), ctx, [message('照旧')]),
    ]:
        assert prepare(bad_value, bad_ctx, bad_msgs, facts)['tasks'] == []


def test_old_card_cannot_lend_same_values_from_an_unrelated_task():
    old = {'id': 3, 'tasks': [draft(key='new_unrelated', title='无关任务')], 'status': 'pending'}
    facts = [{'task_key': 'new_export', 'field': f, 'card_id': 3, 'source_task_key': 'new_unrelated'}
             for f in ['assignee_id', 'estimated_hours', 'start_date', 'due_date']]
    assert prepare(analysis([draft()], supersedes_card_ids=[3]), context(cards=[old]),
                   [message('负责人、工时和日期都照旧。')], facts)['tasks'] == []


@pytest.mark.parametrize('text,missing,supported', [
    ('导出任务负责人不变，工时和日期待确认。', ['工时', '开始日期', '截止日期'], []),
    ('导出校验的负责人不变，工时和日期待确认。', ['工时', '开始日期', '截止日期'], ['负责人']),
    ('导出校验的工时不变，负责人和日期待确认。', ['负责人', '开始日期', '截止日期'], ['工时']),
    ('导出校验的开始日期不变，负责人、工时和截止日期待确认。', ['负责人', '工时', '截止日期'], ['开始日期']),
    ('导出校验的截止日期不变，负责人、工时和开始日期待确认。', ['负责人', '工时', '开始日期'], ['截止日期']),
    ('登录功能的负责人、工时和日期照旧，导出校验的安排待确认。', ['负责人', '工时', '开始日期', '截止日期'], []),
    ('导出校验的负责人不变，登录功能的工时和日期照旧。', ['工时', '开始日期', '截止日期'], ['负责人']),
])
def test_old_card_inheritance_requires_current_task_and_each_field(text, missing, supported):
    old = {'id': 3, 'tasks': [draft()], 'status': 'pending'}
    facts = [{'task_key': 'new_export', 'field': f, 'card_id': 3, 'source_task_key': 'new_export'}
             for f in ['assignee_id', 'estimated_hours', 'start_date', 'due_date']]
    result = prepare(analysis([draft()], supersedes_card_ids=[3]), context(cards=[old]), [message(text)], facts)
    assert result['tasks'] == []
    assert all(any(label in q for q in result['questions']) for label in missing)
    assert all(not any(label in q for q in result['questions']) for label in supported)
    assert '待确认' in result['title'] and '保留原计划' in result['summary']


@pytest.mark.parametrize('text', [
    '导出校验的负责人、工时和日期都照旧。', '导出校验的所有字段保持不变。',
])
def test_old_card_exact_task_explicit_all_fields_inheritance_remains_supported(text):
    value = draft(status='doing', progress=10)
    old = {'id': 3, 'tasks': [value], 'status': 'pending'}
    facts = [{'task_key': 'new_export', 'field': f, 'card_id': 3, 'source_task_key': 'new_export'}
             for f in ['assignee_id', 'estimated_hours', 'remaining_hours', 'start_date', 'due_date']]
    assert prepare(analysis([value], supersedes_card_ids=[3]), context(cards=[old]),
                   [message(text)], facts)['tasks'] == [value]


def test_old_card_estimated_hours_inheritance_does_not_confirm_remaining_hours():
    value = draft(status='doing', progress=10)
    old = {'id': 3, 'tasks': [value], 'status': 'pending'}
    facts = [{'task_key': 'new_export', 'field': f, 'card_id': 3, 'source_task_key': 'new_export'}
             for f in ['assignee_id', 'estimated_hours', 'remaining_hours', 'start_date', 'due_date']]
    text = '导出校验的负责人、预计工时、开始日期和截止日期不变，剩余工时待确认。'
    result = prepare(analysis([value], supersedes_card_ids=[3]), context(cards=[old]), [message(text)], facts)
    assert result['tasks'] == []
    assert len(result['questions']) == 1 and '剩余工时' in result['questions'][0]


def test_unchanged_existing_removed_but_real_completed_change_and_illegal_reference_preserved():
    existing = draft(key='task_4', existing_id=4, status='done', progress=100, remaining_hours=0)
    ctx = context(tasks=[existing])
    assert prepare(analysis([existing]), ctx)['tasks'] == []
    changed = dict(existing, title='不应允许发布的完成任务改动')
    assert prepare(analysis([changed]), ctx)['tasks'] == [changed]
    foreign = dict(existing, key='task_999', existing_id=999)
    assert prepare(analysis([foreign]), ctx)['tasks'] == [foreign]


def test_existing_delay_remains_supported_without_new_commitment_evidence():
    existing = draft(key='task_4', existing_id=4)
    delayed = dict(existing, due_date='2026-10-20')
    assert prepare(analysis([delayed]), context(tasks=[existing]))['tasks'] == [delayed]


@pytest.mark.parametrize('value,msgs', [
    (analysis([draft()], source_message_ids=[11]), [message()]),
    (analysis([draft()], source_message_ids=[]), [message()]),
    (analysis([draft()]), [message(kind='agent')]),
    (analysis([draft(), draft()]), [message()]),
    (analysis([draft(key='task_4', existing_id=4), draft(key='other', existing_id=4)]), [message()]),
])
def test_sources_and_duplicate_identifiers_are_checked_before_fact_filtering(value, msgs):
    with pytest.raises(ValueError):
        prepare(value, msgs=msgs)


@pytest.mark.parametrize('content', ['not json SECRET_INPUT', '{"kind":"bad","summary":"SECRET_INPUT"}',
                                     '解释\n```json\n{}\n```', '```json\n{}\n```\n```json\n{}\n```'])
def test_two_format_repair_attempts_are_bounded_and_feedback_is_sanitized(content):
    chat = ScriptedChat([Reply(content=content)] * 4)
    with pytest.raises(ValueError):
        asyncio.run(provider(chat).analyze(context(), SnapshotTools(context()), 'plan', [message()]))
    assert len(chat.requests) == 3
    feedback = json.dumps(chat.requests[-1]['messages'][2:], ensure_ascii=False)
    assert 'SECRET_INPUT' not in feedback
    assert 'loc' in feedback and 'type' in feedback


def test_json_fence_and_wrapper_repair_usage_and_unknown_usage():
    value = analysis()
    for unknown in [False, True]:
        chat = ScriptedChat([Reply(content='{}'), Reply(content='```json\n' + json.dumps({'analysis': value, 'task_evidence': []}) + '\n```')], unknown)
        result = asyncio.run(provider(chat).analyze(context(), SnapshotTools(context()), 'discussion', [message()]))
        assert result['output'] == value
        assert result['tokens'] is None if unknown else result['tokens']['total_tokens'] == 30


def test_invalid_finalize_parameters_get_paired_sanitized_repair_feedback():
    value = analysis()
    chat = ScriptedChat([Reply(calls=[call('finalize_analysis', '{"analysis":"SECRET_INPUT"}')]),
                         Reply(calls=[call('finalize_analysis', {'analysis': value, 'task_evidence': []}, 'fixed')])])
    result = asyncio.run(provider(chat).analyze(context(), SnapshotTools(context()), 'discussion', [message()]))
    assert result['output'] == value and result['tokens']['total_tokens'] == 30
    feedback = chat.requests[1]['messages'][-1]
    assert feedback['role'] == 'tool' and feedback['tool_call_id'] == 'call1'
    assert 'SECRET_INPUT' not in json.dumps(chat.requests[1]['messages'][2:])
    assert json.loads(feedback['content'])['format_errors'][0]['type'] == 'model_type'


def test_malformed_multiple_calls_are_all_paired_without_executing_partial_tools():
    value = analysis()
    chat = ScriptedChat([Reply(calls=[call('check_plan', '{"tasks":', 'broken'), call('check_plan', {'tasks': []}, 'valid')]),
                         Reply(content=json.dumps(value))])
    tools = SnapshotTools(context())
    result = asyncio.run(provider(chat).analyze(context(), tools, 'discussion', [message()]))
    assert result['output'] == value
    feedback = [m for m in chat.requests[1]['messages'] if m['role'] == 'tool']
    assert {m['tool_call_id'] for m in feedback} == {'broken', 'valid'}
    assert tools.calls == [('check_plan', {'tasks': []})]


def test_more_than_five_tool_calls_fail_without_execution():
    chat = ScriptedChat([Reply(calls=[call('check_plan', {'tasks': []}, f'call{i}') for i in range(6)])])
    tools = SnapshotTools(context())
    with pytest.raises(ValueError):
        asyncio.run(provider(chat).analyze(context(), tools, 'discussion', [message()]))
    assert tools.calls == [] and len(chat.requests) == 1


def test_missing_fact_questions_are_not_hidden_by_model_question_limit():
    value = analysis([draft()], questions=[f'其他问题{i}' for i in range(100)])
    result = prepare(value)
    assert all(any(label in q for q in result['questions']) for label in ['负责人', '工时', '开始', '截止'])


def test_valid_check_narrows_next_request_and_identical_finalize_reuses_check():
    value = analysis([draft()])
    chat = ScriptedChat([Reply(calls=[call('check_plan', {'tasks': value['tasks']})]),
                         Reply(calls=[call('finalize_analysis', {'analysis': value, 'task_evidence': evidence()}, 'done')])])
    tools = SnapshotTools(context())
    result = asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))
    assert result['output']['tasks'] == [draft()]
    assert [t['function']['name'] for t in chat.requests[1]['tools']] == ['finalize_analysis']
    assert len(tools.calls) == 1 and result['tokens']['total_tokens'] == 30



def test_repeated_invalid_check_is_reused_and_each_call_gets_feedback():
    clarification = analysis(questions=['请确认可行的任务范围。'])
    chat = ScriptedChat([
        Reply(calls=[call('check_plan', {'tasks': []}, 'first')]),
        Reply(calls=[call('check_plan', {'tasks': []}, 'repeated')]),
        Reply(calls=[call('finalize_analysis', {'analysis': clarification, 'task_evidence': []}, 'clarify')]),
    ])
    tools = SnapshotTools(context(), valid=False)
    result = asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))
    assert result['output'] == clarification
    assert len(chat.requests) == 3
    assert tools.calls == [('check_plan', {'tasks': []})]
    feedback = [m for m in chat.requests[2]['messages'] if m['role'] == 'tool']
    assert [m['tool_call_id'] for m in feedback] == ['first', 'repeated']
    assert all(json.loads(m['content']) == {'valid': False, 'violations': []} for m in feedback)


def test_six_request_ceiling_and_no_retry_on_network_error():
    ctx = context()
    chat = ScriptedChat([Reply(calls=[call('check_plan', {'tasks': []}, f'call{i}')]) for i in range(7)])
    with pytest.raises(ValueError):
        asyncio.run(provider(chat).analyze(ctx, SnapshotTools(ctx, valid=False), 'plan', [message()]))
    assert len(chat.requests) == 6
    chat = ScriptedChat([RuntimeError('secret network detail')])
    with pytest.raises(RuntimeError):
        asyncio.run(provider(chat).analyze(ctx, SnapshotTools(ctx), 'plan', [message()]))
    assert len(chat.requests) == 1


@pytest.mark.parametrize('calls', [
    [call('finalize_analysis', {'analysis': analysis(), 'task_evidence': []}), call('get_tasks', {}, 'query')],
    [call('finalize_analysis', {'analysis': analysis(), 'task_evidence': []}),
     call('finalize_analysis', {'analysis': analysis(), 'task_evidence': []}, 'again')],
])
def test_mixed_or_multiple_finalize_is_explicitly_rejected(calls):
    chat = ScriptedChat([Reply(calls=calls)])
    with pytest.raises(ValueError):
        asyncio.run(provider(chat).analyze(context(), SnapshotTools(context()), 'plan', [message()]))
    assert len(chat.requests) == 1


def test_sources_are_not_treated_as_repairable_json_errors():
    chat = ScriptedChat([Reply(content=json.dumps(analysis(source_message_ids=[999])))])
    with pytest.raises(ValueError):
        asyncio.run(provider(chat).analyze(context(), SnapshotTools(context()), 'plan', [message()]))
    assert len(chat.requests) == 1


def test_production_check_preserves_completed_protection_and_cross_project_rejection(env):
    from app.agent import ProjectTools
    from app.models import Task
    ctx_tools = ProjectTools(env[2].state.db, project(env)['id'])
    ctx = ctx_tools.execute('get_project_context', {})
    existing = ctx['tasks'][0]
    with env[2].state.db.Session() as db:
        original = db.get(Task, existing['existing_id'])
        original.status, original.progress, original.remaining_hours = 'done', 100, 0
        db.commit()
    ctx = ctx_tools.execute('get_project_context', {})
    changed = dict(ctx['tasks'][0], title='伪装成合法完成任务修改')
    clarification = analysis(questions=['已完成任务不能修改，请确认新的任务范围。'])
    chat = ScriptedChat([Reply(calls=[call('finalize_analysis', {'analysis': analysis([changed]), 'task_evidence': []})]),
                         Reply(calls=[call('finalize_analysis', {'analysis': clarification, 'task_evidence': []}, 'clarify')])])
    output = asyncio.run(provider(chat).analyze(ctx, ctx_tools, 'adjust', [message()]))['output']
    assert output == clarification
    assert len(chat.requests) == 2
    assert any(v['code'] == 'completed_task' for item in ctx_tools.results if item['name'] == 'check_plan'
               for v in item['result']['violations'])
    assert 'completed_task' in chat.requests[1]['messages'][-1]['content']
    with pytest.raises(ValueError):
        ctx_tools.execute('get_tasks', {'project_id': project(env, 'leader2')['id']})
    with pytest.raises(ValueError):
        ctx_tools.execute('check_plan', {'tasks': [], 'evil': True})
