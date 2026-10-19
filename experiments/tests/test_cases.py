"""这些合成响应仅供单元测试，绝不写入实验原始结果。"""
import json
import pytest
from experiments.cases import fingerprint, frozen_cases
from experiments.scoring import score
from experiments.state import inputs, isolated_state


def labelled_output(case):
    expected = case['expected']
    tasks = []
    for i, label in enumerate(expected['tasks']):
        facts = dict(label['facts'])
        acceptance = facts.pop('acceptance', '；'.join(g[0] for g in label.get('acceptance_groups', [])) or '满足约定验收')
        tasks.append(dict(key=f"task_{facts['existing_id']}" if facts['existing_id'] else f'new_{i}',
            title=label['aliases'][0], description='', acceptance=acceptance,
            artifact_url='', blocker='', **facts))
    return dict(kind=case['mode'], title='测试专用输出',
        summary='；'.join(g[0] for g in expected['summary_groups']) or '测试专用建议',
        questions=['；'.join(g[0] for g in expected['question_groups'])] if expected['question_groups'] else [],
        tasks=tasks, source_message_ids=[401], supersedes_card_ids=expected['supersedes'])


def test_disjoint_frozen_splits():
    dev, evaluation = frozen_cases('dev'), frozen_cases('eval')
    assert len(dev) == 3 and len(evaluation) == 10
    assert not {c['id'] for c in dev} & {c['id'] for c in evaluation}
    assert fingerprint(evaluation) == fingerprint(frozen_cases('eval'))
    evaluation[0]['messages'][0]['content'] = '变更'
    assert fingerprint(evaluation) != fingerprint(frozen_cases('eval'))


@pytest.mark.parametrize('case', frozen_cases('all'), ids=lambda c: c['id'])
def test_gold_plans_are_feasible_and_gold_responses_score_full(case):
    result = score(case, labelled_output(case))
    assert result['success'], result
    assert result['plan_feasible'] is (True if case['expected']['outcome'] == 'plan' else None)


def test_tool_context_is_isolated_and_no_label_or_case_id_leaks():
    case = frozen_cases()[0]
    with isolated_state(case) as db:
        context, messages, directory = inputs(case, db)
        assert context['tasks'][0]['existing_id'] == 201
        assert messages[0]['created_at'] == '2026-10-16T09:00:00+08:00'
        assert directory['members'][0] == {'name': '张明', 'user_id': 11}
        assert 'weekly_hours' not in json.dumps(directory)
        wire = json.dumps(dict(project_context=context, messages=messages), ensure_ascii=False)
        assert 'expected' not in wire and 'E01' not in wire and case['category'] not in wire
        context['tasks'][0]['estimated_hours'] = 999
    with isolated_state(case) as db:
        context2, _, _ = inputs(case, db)
        assert context2['tasks'][0]['estimated_hours'] == 6


def test_duplicate_task_is_false_positive_and_completed_mutation_is_rejected():
    case = frozen_cases()[8]
    output = labelled_output(case)
    output['tasks'].append(dict(output['tasks'][0], key='new_duplicate'))
    result = score(case, output)
    assert result['extraction']['tasks']['fp'] == 1
    assert not result['success']
    output = labelled_output(case)
    done = dict(case['state']['tasks'][2], assignee_id=11)
    output['tasks'].append(done)
    result = score(case, output)
    assert 'completed_task' in {v['code'] for v in result['checks']['violations']}
    assert not result['plan_feasible']


@pytest.mark.parametrize(('field', 'wrong'), [('assignee_id', 12), ('start_date', '2026-10-22'),
    ('due_date', '2026-10-24'), ('estimated_hours', 3), ('remaining_hours', 3), ('dependencies', [])])
def test_incorrect_field_never_matches_correct_fact(field, wrong):
    case = frozen_cases()[0]
    output = labelled_output(case)
    output['tasks'][0][field] = wrong
    result = score(case, output)
    assert result['extraction']['per_field'][field]['tp'] == 0
    assert result['extraction']['per_field'][field]['fp'] == 1
    assert result['extraction']['per_field'][field]['fn'] == 1
    assert not result['success']


@pytest.mark.parametrize(('case_id', 'unrelated', 'expected_errors'), [
    ('E10', '只要画面是绿色就算通过，无需登录或错误凭据用例', 2),
    ('E03', '部署和截图都不需要，只要画面是绿色就算通过', 1)])
def test_explicit_unchanged_acceptance_rejects_unrelated_nonempty_text(case_id, unrelated, expected_errors):
    case = next(c for c in frozen_cases() if c['id'] == case_id)
    output = labelled_output(case)
    for task in output['tasks']:
        task['acceptance'] = unrelated
    result = score(case, output)
    assert result['success'] is False
    assert result['extraction']['per_field']['acceptance']['tp'] == 0
    assert result['extraction']['per_field']['acceptance']['fp'] == expected_errors
    assert result['extraction']['per_field']['acceptance']['fn'] == expected_errors
    # 校验器只验证可调度性与非空验收；字段忠实度由冻结标签另行判断。
    assert result['plan_feasible'] is True


@pytest.mark.parametrize(('case_id', 'task_index', 'field', 'wrong'), [
    ('E03', 0, 'estimated_hours', 3), ('E03', 0, 'remaining_hours', 3),
    ('E03', 0, 'start_date', '2026-10-22'), ('E03', 0, 'due_date', '2026-10-24'),
    ('E03', 0, 'dependencies', []), ('E07', 0, 'assignee_id', 12),
    ('E07', 0, 'estimated_hours', 5), ('E07', 0, 'remaining_hours', 5),
    ('E07', 0, 'start_date', '2026-10-20'), ('E07', 0, 'due_date', '2026-10-21'),
    ('E10', 0, 'start_date', '2026-10-20'), ('E10', 0, 'estimated_hours', 5),
    ('E10', 0, 'remaining_hours', 5), ('E10', 1, 'assignee_id', 13),
    ('E10', 1, 'estimated_hours', 3), ('E10', 1, 'remaining_hours', 3)])
def test_other_explicit_preserved_fields_already_have_exact_labels(case_id, task_index, field, wrong):
    case = next(c for c in frozen_cases() if c['id'] == case_id)
    output = labelled_output(case)
    output['tasks'][task_index][field] = wrong
    result = score(case, output)
    assert not result['success']
    assert result['extraction']['per_field'][field]['fp'] == 1
    assert result['extraction']['per_field'][field]['fn'] == 1
