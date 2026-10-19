"""供应商把内部 analysis 对象编码成一层 JSON 字符串时的兼容边界。"""
import asyncio
import json

import pytest
from pydantic import ValidationError

from app.agent_output import AnalysisSubmission
from app.schemas import AgentOutput
from test_agent_reliability import (
    Reply, ScriptedChat, SnapshotTools, analysis, call, context, draft, evidence, message, provider,
)


def submission_reply(transport, payload):
    if transport == 'tool':
        return Reply(calls=[call('finalize_analysis', payload)])
    content = json.dumps(payload, ensure_ascii=False)
    if transport == 'fenced_wrapper':
        content = '```json\n' + content + '\n```'
    return Reply(content=content)


@pytest.mark.parametrize('transport', ['tool', 'wrapper', 'fenced_wrapper'])
@pytest.mark.parametrize('encoded', [False, True], ids=['object', 'json_string'])
def test_complete_analysis_preserves_grounded_tasks_and_plan_validation(transport, encoded):
    value = analysis([draft()])
    payload = {'analysis': json.dumps(value, ensure_ascii=False) if encoded else value,
               'task_evidence': evidence()}
    chat = ScriptedChat([submission_reply(transport, payload)])
    tools = SnapshotTools(context())

    result = asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert result['output'] == value
    assert result['tokens']['total_tokens'] == 15
    assert len(chat.requests) == 1
    assert tools.calls == [('check_plan', {'tasks': [draft()]})]


def test_normalization_keeps_input_and_object_protocol_schema():
    value = analysis([draft()])
    encoded = json.dumps(value, ensure_ascii=False)
    payload = {'analysis': encoded, 'task_evidence': evidence()}

    result = AnalysisSubmission.model_validate(payload)

    assert result.analysis.model_dump(mode='json') == value
    assert payload['analysis'] == encoded
    assert [fact.model_dump(mode='json', exclude_none=True) for fact in result.task_evidence] == evidence()
    schema = AnalysisSubmission.model_json_schema()
    assert schema['properties']['analysis'] == {'$ref': '#/$defs/AgentOutput'}
    assert schema['$defs']['AgentOutput']['type'] == 'object'
    with pytest.raises(ValidationError):
        AgentOutput.model_validate(encoded)


@pytest.mark.parametrize('transport', ['tool', 'wrapper', 'fenced_wrapper'])
@pytest.mark.parametrize('invalid', [
    '{"summary":"SECRET_NESTED"',
    'SECRET_NESTED prefix ' + json.dumps(analysis()),
    json.dumps(analysis()) + ' SECRET_NESTED suffix',
    '```json\n' + json.dumps(analysis()) + '\n```',
    json.dumps([analysis()]),
    'null',
    'true',
    '7',
    json.dumps(json.dumps(analysis())),
], ids=['malformed', 'mixed_prefix', 'mixed_suffix', 'nested_fence', 'array', 'null',
        'boolean', 'number', 'double_encoding'])
def test_invalid_nested_json_is_rejected_with_bounded_sanitized_repair(transport, invalid):
    payload = {'analysis': invalid, 'task_evidence': evidence()}
    chat = ScriptedChat([submission_reply(transport, payload) for _ in range(4)])
    tools = SnapshotTools(context())

    with pytest.raises(ValueError, match='两次格式修正后仍无效'):
        asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert len(chat.requests) == 3
    assert tools.calls == []
    feedback = chat.requests[-1]['messages'][2:]
    assert 'SECRET_NESTED' not in json.dumps(feedback, ensure_ascii=False)
    repairs = [json.loads(item['content']) for item in feedback if item.get('content')]
    assert len(repairs) == 2
    assert all(item['format_errors'] and all('loc' in issue and 'type' in issue
               for issue in item['format_errors']) for item in repairs)


@pytest.mark.parametrize('transport', ['tool', 'wrapper'])
def test_invalid_nested_json_can_be_repaired_to_one_json_string(transport):
    invalid = {'analysis': '{"title":', 'task_evidence': []}
    value = analysis([draft()])
    valid = {'analysis': json.dumps(value), 'task_evidence': evidence()}
    chat = ScriptedChat([submission_reply(transport, invalid), submission_reply(transport, valid)])
    tools = SnapshotTools(context())

    result = asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert result['output'] == value
    assert len(chat.requests) == 2
    assert tools.calls == [('check_plan', {'tasks': [draft()]})]


@pytest.mark.parametrize('transport', ['tool', 'wrapper'])
@pytest.mark.parametrize('facts', [[], evidence('没有出现在消息中的伪造引文')],
                         ids=['missing', 'forged_quote'])
def test_string_analysis_still_requires_true_field_evidence(transport, facts):
    value = analysis([draft()])
    chat = ScriptedChat([submission_reply(transport, {
        'analysis': json.dumps(value), 'task_evidence': facts,
    })])
    tools = SnapshotTools(context())

    result = asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert result['output']['tasks'] == []
    assert all(any(label in question for question in result['output']['questions'])
               for label in ['负责人', '工时', '开始', '截止'])
    assert len(chat.requests) == 1
    assert tools.calls == [('check_plan', {'tasks': []})]


@pytest.mark.parametrize('transport', ['tool', 'wrapper'])
@pytest.mark.parametrize('extra_location', ['analysis', 'submission', 'task', 'evidence'])
def test_string_analysis_keeps_unknown_fields_forbidden(transport, extra_location):
    value = analysis([draft()])
    facts = evidence()
    payload = {'task_evidence': facts}
    target = {'analysis': value, 'submission': payload, 'task': value['tasks'][0],
              'evidence': facts[0]}[extra_location]
    target['SECRET_UNKNOWN_FIELD'] = True
    payload['analysis'] = json.dumps(value)
    chat = ScriptedChat([submission_reply(transport, payload) for _ in range(4)])
    tools = SnapshotTools(context())

    with pytest.raises(ValueError, match='两次格式修正后仍无效'):
        asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert len(chat.requests) == 3
    assert tools.calls == []
    feedback = chat.requests[-1]['messages'][2:]
    assert 'SECRET_UNKNOWN_FIELD' not in json.dumps(feedback)
    repairs = [json.loads(item['content']) for item in feedback if item.get('content')]
    assert all(any(issue['type'] == 'extra_forbidden' for issue in item['format_errors'])
               for item in repairs)


@pytest.mark.parametrize('transport', ['tool', 'wrapper'])
def test_task_evidence_is_not_json_string_normalized(transport):
    payload = {'analysis': json.dumps(analysis([draft()])), 'task_evidence': json.dumps(evidence())}
    chat = ScriptedChat([submission_reply(transport, payload) for _ in range(4)])
    tools = SnapshotTools(context())

    with pytest.raises(ValueError, match='两次格式修正后仍无效'):
        asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert len(chat.requests) == 3
    assert tools.calls == []


@pytest.mark.parametrize('transport', ['tool', 'wrapper'])
def test_string_analysis_keeps_invalid_source_as_nonrepairable_business_error(transport):
    payload = {'analysis': json.dumps(analysis([draft()], source_message_ids=[999])),
               'task_evidence': evidence()}
    chat = ScriptedChat([submission_reply(transport, payload)])
    tools = SnapshotTools(context())

    with pytest.raises(ValueError, match='模型来源引用无效'):
        asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert len(chat.requests) == 1
    assert tools.calls == []


@pytest.mark.parametrize('transport', ['tool', 'wrapper'])
def test_string_analysis_keeps_failed_plan_check_and_accepts_clarification(transport):
    value = analysis([draft()])
    clarification = analysis(questions=['请确认可行的任务范围。'])
    chat = ScriptedChat([
        submission_reply(transport, {'analysis': json.dumps(value), 'task_evidence': evidence()}),
        submission_reply(transport, {'analysis': json.dumps(clarification), 'task_evidence': []}),
    ])
    tools = SnapshotTools(context(), valid=False)

    result = asyncio.run(provider(chat).analyze(context(), tools, 'plan', [message()]))

    assert result['output'] == clarification
    assert len(chat.requests) == 2
    assert tools.calls == [('check_plan', {'tasks': [draft()]}), ('check_plan', {'tasks': []})]
    assert json.loads(chat.requests[1]['messages'][-1]['content']) in [
        {'valid': False, 'violations': []}, {'plan_checks': {'valid': False, 'violations': []}},
    ]
