"""冻结关键词匹配 + 精确结构字段 + 生产 check_plan，不调用任何模型评分。"""
from collections import Counter
import re
from .backend import AgentOutput, Project, check_plan
from .state import isolated_state

CHECK_CODES = ('duplicate_key', 'invalid_task', 'completed_task', 'reserved_key',
    'invalid_requirement', 'invalid_assignee', 'missing_acceptance', 'invalid_hours',
    'invalid_date', 'date_order', 'date_range', 'invalid_stage', 'stage_deadline',
    'requirement_coverage', 'course_feature_coverage', 'invalid_dependency',
    'dependency_time', 'dependency_cycle', 'weekly_capacity')


def normalized(text):
    return re.sub(r'[\W_]+', '', str(text).lower())


def group_hits(groups, text):
    value = normalized(text)
    return [any(normalized(alias) in value for alias in group) for group in groups]


def counts(tp=0, fp=0, fn=0):
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return dict(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)


def _facts(label):
    result = dict(label['facts'])
    if label.get('acceptance_groups'):
        result['acceptance_keywords'] = True
    return result


def extraction(labels, tasks):
    task_counts = Counter(tp=0, fp=0, fn=0)
    field_counts = Counter(tp=0, fp=0, fn=0)
    per_field = {}
    unmatched = set(range(len(labels)))
    matches = []

    def add(field, kind):
        field_counts[kind] += 1
        per_field.setdefault(field, Counter(tp=0, fp=0, fn=0))[kind] += 1

    for task in tasks:
        # 标题冻结别名为匹配入口，描述不能替代任务标题。
        title = normalized(task['title'])
        found = next((i for i in sorted(unmatched)
                      if any(normalized(a) in title for a in labels[i]['aliases'])), None)
        if found is None:
            task_counts['fp'] += 1
            # 幻觉或重复任务按标准字段计为错误项，不因不匹配而消失。
            fields = ('existing_id', 'requirement_id', 'assignee_id', 'estimated_hours',
                      'remaining_hours', 'start_date', 'due_date', 'dependencies', 'status',
                      'progress', 'stage_index', 'acceptance_keywords')
            for field in fields:
                add(field, 'fp')
            matches.append(dict(predicted_key=task['key'], label=None))
            continue
        unmatched.remove(found)
        label = labels[found]
        task_counts['tp'] += 1
        matches.append(dict(predicted_key=task['key'], label_index=found))
        for field, expected in _facts(label).items():
            actual = (all(group_hits(label['acceptance_groups'], task['acceptance']))
                      if field == 'acceptance_keywords' else task.get(field))
            if field == 'dependencies':
                actual, expected = sorted(actual or []), sorted(expected)
            if actual == expected:
                add(field, 'tp')
            else:
                add(field, 'fp')
                add(field, 'fn')
    for i in unmatched:
        task_counts['fn'] += 1
        for field in _facts(labels[i]):
            add(field, 'fn')
    combined = task_counts + field_counts
    # Counter 加法会去掉零，但 counts 的默认值保持完整输出。
    return dict(**counts(**combined), tasks=counts(**task_counts), fields=counts(**field_counts),
                per_field={k: counts(**v) for k, v in per_field.items()}, matches=matches)


def score(case, output):
    expected = case['expected']
    eligible = expected['outcome'] == 'plan'
    data, validation_error = None, None
    try:
        data = AgentOutput.model_validate(output).model_dump(mode='json')
    except Exception as exc:
        # 不保存异常原文，避免提供商或字段内容带出秘密。
        validation_error = type(exc).__name__
    tasks = data['tasks'] if data else []
    extracted = extraction(expected['tasks'], tasks)
    questions = '\n'.join(data['questions']) if data else ''
    q_hits = group_hits(expected['question_groups'], questions)
    s_hits = group_hits(expected['summary_groups'], data['summary'] if data else '')
    check = None
    if data and tasks and case['state'] is not None:
        with isolated_state(case) as database, database.Session() as db:
            check = check_plan(db, db.get(Project, 1), tasks)
    source_ok = bool(data) and sorted(data['source_message_ids']) == sorted(m['id'] for m in case['messages'])
    supersedes_ok = bool(data) and sorted(data['supersedes_card_ids']) == sorted(expected['supersedes'])
    feasible = bool(data and tasks and check and check['valid']) if eligible else None
    outcome_ok = bool(data) and (
        (eligible and bool(tasks) and not data['questions']) or
        (expected['outcome'] == 'clarify' and not tasks and bool(data['questions']) and all(q_hits)) or
        (expected['outcome'] == 'infeasible' and not tasks and all(s_hits)))
    success = bool(outcome_ok and source_ok and supersedes_ok and extracted['fp'] == 0
                   and extracted['fn'] == 0 and (not eligible or feasible))
    violated = {v['code'] for v in check['violations']} if check else set()
    normalized_questions = [normalized(q) for q in data['questions']] if data else []
    return dict(output_valid=data is not None, validation_error=validation_error, success=success,
        outcome=expected['outcome'], outcome_ok=outcome_ok, plan_eligible=eligible, plan_feasible=feasible,
        extraction=extracted, source_ids_ok=source_ok, supersedes_ok=supersedes_ok,
        question_hits=q_hits, summary_hits=s_hits,
        unexpected_questions=len(data['questions']) if data and eligible else 0,
        duplicate_questions=len(normalized_questions) - len(set(normalized_questions)),
        duplicate_or_unmatched_tasks=extracted['tasks']['fp'], checks=check,
        constraint_passes={code: bool(data and tasks and check and code not in violated) for code in CHECK_CODES}
            if eligible else None)


def _aggregate_counts(items):
    return counts(**{key: sum(v.get(key, 0) for v in items) for key in ('tp', 'fp', 'fn')})


def summarize(records):
    result = dict(groups={}, limitations=[
        '冻结别名和精确字段仅衡量机械匹配；等义重命名及其他可行日期可能低估表现。',
        '人工复核应独立保留意见，不得回改冻结标签、覆盖机械分数或删除失败。',
        '不同组的信息范围和调用预算不同，不能据此声称纯工具调用的因果提升。'])
    for group in sorted({r['group'] for r in records}):
        all_items = [r for r in records if r['group'] == group]
        items = [r for r in all_items if r['status'] != 'not_run']
        scores = [r['score'] for r in items if r.get('score') is not None]
        plans = [s for s in scores if s['plan_eligible']]
        per_field = sorted({f for s in scores for f in s['extraction']['per_field']})
        success = sum(s['success'] for s in scores)
        calls = [c for r in items for c in r.get('api_calls', [])]
        costs = [c.get('cost_usd') for c in calls]
        tokens = {field: (sum(c['usage'][field] for c in calls)
                   if calls and all(isinstance(c.get('usage'), dict) and isinstance(c['usage'].get(field), (int, float)) for c in calls)
                   else None) for field in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
        durations = [r['elapsed_ms'] for r in items if r.get('elapsed_ms') is not None]
        result['groups'][group] = dict(planned=len(all_items), attempted=len(items),
            completed=sum(r['status'] == 'completed' for r in items),
            failed=sum(r['status'] == 'failed' for r in items),
            invalid=sum(r['status'] == 'invalid' for r in items), not_run=len(all_items) - len(items),
            success=success, success_rate_attempted=success / len(items) if items else None,
            plan_eligible_attempts=len(plans), feasible_nonempty=sum(s['plan_feasible'] for s in plans),
            plan_feasible_rate=sum(s['plan_feasible'] for s in plans) / len(plans) if plans else None,
            clarify=dict(attempts=sum(s['outcome'] == 'clarify' for s in scores),
                         success=sum(s['success'] and s['outcome'] == 'clarify' for s in scores)),
            infeasible=dict(attempts=sum(s['outcome'] == 'infeasible' for s in scores),
                           success=sum(s['success'] and s['outcome'] == 'infeasible' for s in scores)),
            extraction=_aggregate_counts([s['extraction'] for s in scores]),
            task_extraction=_aggregate_counts([s['extraction']['tasks'] for s in scores]),
            field_extraction=_aggregate_counts([s['extraction']['fields'] for s in scores]),
            per_field={f: _aggregate_counts([s['extraction']['per_field'].get(f, {}) for s in scores]) for f in per_field},
            constraint_pass_counts={code: sum(s['constraint_passes'][code] for s in plans) for code in CHECK_CODES},
            constraint_denominator=len(plans),
            constraint_pass_ratio=sum(sum(s['constraint_passes'].values()) for s in plans) / (len(plans) * len(CHECK_CODES)) if plans else None,
            api_requests=len(calls), cost_usd=sum(costs) if costs and all(c is not None for c in costs) else None,
            cost_known_requests=sum(c is not None for c in costs),
            tokens=tokens, question_groups_expected=sum(len(s['question_hits']) for s in scores),
            question_groups_found=sum(sum(s['question_hits']) for s in scores),
            unexpected_questions=sum(s['unexpected_questions'] for s in scores),
            duplicate_questions=sum(s['duplicate_questions'] for s in scores),
            supersedes_correct=sum(s['supersedes_ok'] for s in scores),
            mean_elapsed_ms=sum(durations) / len(durations) if durations else None,
            elapsed_known_attempts=len(durations))
    return result
