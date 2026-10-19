"""先固定空计划、非法输出与分母口径，避免形式上可行刷分。"""
from experiments.scoring import score, summarize


def case():
    return {'id': 'T01', 'split': 'dev', 'state': None,
            'messages': [{'id': 401}], 'mode': 'plan',
            'expected': {'outcome': 'plan', 'tasks': [{'aliases': ['操作文档'],
                'facts': {'existing_id': None, 'assignee_id': 11}}],
                'question_groups': [], 'summary_groups': [], 'supersedes': []}}


def empty():
    return {'kind': 'plan', 'title': '建议', 'summary': '没有变更',
            'questions': [], 'source_message_ids': [401], 'tasks': [],
            'supersedes_card_ids': []}


def test_empty_plan_is_failure_and_missed_task():
    result = score(case(), empty())
    assert result.get('success') is False
    assert result.get('plan_feasible') is False
    assert result.get('extraction', {}).get('fn') == 3


def test_illegal_output_still_has_plan_denominator_and_false_negative():
    result = score(case(), {'tasks': '非法'})
    assert result.get('output_valid') is False
    assert result.get('plan_eligible') is True
    assert result.get('extraction', {}).get('fn') == 3


def test_clarification_not_counted_as_feasible_plan():
    item = case()
    item['expected'].update(outcome='clarify', tasks=[], question_groups=[['负责人', '谁负责'], ['工时', '小时'], ['日期', '哪天']])
    out = empty()
    out['questions'] = ['由谁负责、预计几小时、哪天开始和截止？']
    result = score(item, out)
    assert result.get('success') is True
    assert result.get('plan_eligible') is False
    assert result.get('plan_feasible') is None


def test_failures_count_but_not_run_is_explicitly_separate():
    records = [dict(group='agent', status='failed', score=score(case(), None)),
               dict(group='agent', status='not_run', score=None)]
    summary = summarize(records).get('groups', {}).get('agent', {})
    assert summary.get('planned') == 2
    assert summary.get('attempted') == 1
    assert summary.get('failed') == 1
    assert summary.get('not_run') == 1
    assert summary.get('success_rate_attempted') == 0


def test_unknown_cost_never_becomes_zero_in_summary():
    records = [dict(group='agent', status='failed', score=score(case(), None),
                    api_calls=[{'cost_usd': None, 'usage': None}], elapsed_ms=10)]
    summary = summarize(records)['groups']['agent']
    assert summary['cost_usd'] is None
    assert summary['cost_known_requests'] == 0
    assert summary['api_requests'] == 1
    assert summary['plan_feasible_rate'] == 0
