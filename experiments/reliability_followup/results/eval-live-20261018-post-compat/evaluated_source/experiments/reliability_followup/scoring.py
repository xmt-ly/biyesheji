"""同一公共协议先验证原始输出，再过滤精确未变旧任务；仅聚合真实保存评分。"""
from collections import Counter
from copy import deepcopy
import re
from .backend import AgentOutput, Project, check_plan
from .state import isolated_state

CHECK_CODES = ('duplicate_key', 'invalid_task', 'completed_task', 'reserved_key',
    'invalid_requirement', 'invalid_assignee', 'missing_acceptance', 'invalid_hours',
    'invalid_date', 'date_order', 'date_range', 'invalid_stage', 'stage_deadline',
    'requirement_coverage', 'course_feature_coverage', 'invalid_dependency',
    'dependency_time', 'dependency_cycle', 'weekly_capacity')
QUESTION_PATTERNS = {
    'assignee': r'谁|负责人|哪位|成员.{0,8}(?:承担|负责)',
    'hours': r'工时|小时|工作量|耗时|时长',
    'start_date': r'开始|开工|启动日期',
    'due_date': r'截止|交付|交工|完成日期|何时完成|哪天完成|什么时候完成|最晚|(?:哪天|何时|什么时候).{0,8}结束',
    'acceptance': r'验收|标准', 'stage': r'阶段', 'dependencies': r'依赖|前置',
    'requirement': r'关联.{0,8}需求|需求.{0,8}关联',
}


def normalized(value):
    return re.sub(r'[\W_]+', '', str(value).lower())


def question_topics(question):
    topics = set()
    for clause in re.split(r'[，,；;。！？?!]', question):
        # 问题中用于复述的已知事实不当作再次追问；规则在模型输出前固定。
        if re.search(r'已确认|已经确定|已明确|已定', clause) and not re.search(r'吗|么|何|哪|几|请确认|请问', clause):
            continue
        topics.update(key for key, pattern in QUESTION_PATTERNS.items() if re.search(pattern, clause))
    return topics


def counts(tp=0, fp=0, fn=0):
    return dict(tp=tp, fp=fp, fn=fn, precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / (tp + fn) if tp + fn else None,
        f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None)


def _canonical_task(task):
    value = deepcopy(task)
    value['dependencies'] = sorted(value['dependencies'])
    return value


def effective_changes(case, tasks):
    """只移除全部字段与真实原任务一致的合法引用；其他内容不隐藏。"""
    original = {t['existing_id']: _canonical_task(t) for t in case['state']['tasks']}
    effective, unchanged = [], []
    for task in tasks:
        source = original.get(task.get('existing_id'))
        if source is not None and _canonical_task(task) == source:
            unchanged.append(task['key'])
        else:
            effective.append(task)
    return effective, unchanged


def extraction(labels, tasks):
    task_counts, field_counts = Counter(tp=0, fp=0, fn=0), Counter(tp=0, fp=0, fn=0)
    per_field, matches, mismatches = {}, [], []
    unmatched = set(range(len(labels)))

    def add(field, kind):
        field_counts[kind] += 1
        per_field.setdefault(field, Counter(tp=0, fp=0, fn=0))[kind] += 1

    for task in tasks:
        found = next((i for i in sorted(unmatched)
            if normalized(task['title']) in {normalized(a) for a in labels[i]['aliases']}), None)
        if found is None:
            task_counts['fp'] += 1
            matches.append(dict(predicted_key=task['key'], label_index=None))
            continue
        unmatched.remove(found)
        task_counts['tp'] += 1
        label = labels[found]
        matches.append(dict(predicted_key=task['key'], label_index=found))
        for field, expected in label['facts'].items():
            actual = task.get(field)
            if field == 'dependencies':
                good = sorted(actual or []) == sorted(expected)
            elif isinstance(expected, dict) and set(expected) == {'one_of'}:
                good = actual in expected['one_of']
            else:
                good = actual == expected
            if good:
                add(field, 'tp')
            else:
                add(field, 'fp')
                add(field, 'fn')
                mismatches.append(dict(label_index=found, predicted_key=task['key'], field=field,
                                       expected=expected, actual=actual))
        acceptance = task['acceptance']
        for pattern in label.get('acceptance_scope_exclusions', []):
            # 只去掉标签预先列明的失败条件，余下部分仍须正面满足验收词组。
            acceptance = re.sub(pattern, '', acceptance)
        for index, group in enumerate(label['acceptance_groups']):
            if any(normalized(alias) in normalized(acceptance) for alias in group):
                add('acceptance_keywords', 'tp')
            else:
                add('acceptance_keywords', 'fp')
                add('acceptance_keywords', 'fn')
                mismatches.append(dict(label_index=found, field='acceptance_keywords', group_index=index))
        for pattern in label.get('acceptance_reject_patterns', []):
            if re.search(pattern, acceptance):
                add('acceptance_relation', 'fp')
                add('acceptance_relation', 'fn')
                mismatches.append(dict(label_index=found, field='acceptance_relation', rejected_pattern=pattern))
    for i in unmatched:
        task_counts['fn'] += 1
        for field in labels[i]['facts']:
            add(field, 'fn')
        for _ in labels[i]['acceptance_groups']:
            add('acceptance_keywords', 'fn')
    total = {k:task_counts[k] + field_counts[k] for k in ('tp', 'fp', 'fn')}
    return dict(**counts(**total), tasks=counts(**task_counts), fields=counts(**field_counts),
        per_field={key:counts(**value) for key,value in per_field.items()}, matches=matches, mismatches=mismatches)


_UNSET = object()


def _score_output(case, output):
    expected = case['expected']
    data, validation_error = None, None
    try:
        data = AgentOutput.model_validate(output).model_dump(mode='json')
    except Exception as exc:
        validation_error = type(exc).__name__
    raw = data['tasks'] if data else []
    check = None
    if data:
        with isolated_state(case) as database, database.Session() as db:
            check = check_plan(db, db.get(Project, 1), raw)
    # 来源、重复、约束和完成保护均在过滤前检查。
    def valid_sources(value):
        ids = value['source_message_ids'] if value else []
        return bool(value) and len(ids) == len(set(ids)) and sorted(ids) == sorted(m['id'] for m in case['messages'])
    source_ok = valid_sources(data)
    supersedes_ok = bool(data) and sorted(data['supersedes_card_ids']) == sorted(expected['supersedes'])
    keys = [t['key'] for t in raw]
    existing_ids = [t['existing_id'] for t in raw if t['existing_id'] is not None]
    duplicate_keys = len(keys) - len(set(keys))
    duplicate_existing_ids = len(existing_ids) - len(set(existing_ids))
    duplicate_dependencies = sum(len(t['dependencies']) - len(set(t['dependencies'])) for t in raw)
    raw_contract = bool(data) and not (duplicate_keys or duplicate_existing_ids or duplicate_dependencies)
    violated = {v['code'] for v in check['violations']} if check else set()
    completed = bool(data) and 'completed_task' not in violated
    effective, unchanged = effective_changes(case, raw)
    extracted = extraction(expected['tasks'], effective)
    question_labels, unknown_questions = set(), 0
    for question in data['questions'] if data else []:
        hits = question_topics(question)
        question_labels.update(hits)
        unknown_questions += not bool(hits)
    required = set(expected['question_labels'])
    extra_labels = sorted(question_labels - required)
    missing_labels = sorted(required - question_labels)
    questions = data['questions'] if data else []
    eligible = expected['outcome'] == 'plan'
    outcome_ok = bool(data) and (
        (eligible and bool(effective) and not questions) or
        (expected['outcome'] == 'clarify' and not effective and bool(questions) and not missing_labels))
    feasible = bool(check and check['valid']) if data else False
    kind_ok = bool(data) and data['kind'] == case['mode']
    semantic_success = bool(data and outcome_ok and source_ok and supersedes_ok and raw_contract and
        completed and feasible and extracted['fp'] == 0 and extracted['fn'] == 0)
    duplicate_questions = len(questions) - len({normalized(q) for q in questions})
    changes_only = bool(data) and not unchanged
    strict_success = bool(semantic_success and changes_only and not extra_labels and
                          not unknown_questions and not duplicate_questions)
    return dict(output_valid=data is not None, validation_error=validation_error,
        semantic_success=semantic_success, strict_success=strict_success, outcome=expected['outcome'],
        outcome_ok=outcome_ok, kind_ok=kind_ok, plan_eligible=eligible, plan_feasible=feasible,
        source_ids_ok=source_ok, supersedes_ok=supersedes_ok, raw_contract_valid=raw_contract,
        duplicate_keys=duplicate_keys, duplicate_existing_ids=duplicate_existing_ids,
        duplicate_dependencies=duplicate_dependencies, completed_entities_unchanged=completed,
        raw_task_count=len(raw), effective_task_count=len(effective), unchanged_existing_tasks=len(unchanged),
        unchanged_task_keys=unchanged, changes_only_contract=changes_only,
        hallucinated_tasks=extracted['tasks']['fp'], missing_information_error=bool(not eligible and effective),
        question_labels_found=sorted(question_labels), question_labels_required=sorted(required),
        missing_question_labels=missing_labels, extra_question_labels=extra_labels,
        unknown_questions=unknown_questions, duplicate_questions=duplicate_questions,
        unexpected_plan_questions=len(questions) if eligible else 0, extraction=extracted, checks=check,
        constraint_passes={code:bool(data and check and code not in violated) for code in CHECK_CODES})


def score(case, output, raw_submission=_UNSET):
    """主指标仅评价 provider 公共输出；原模型候选按同规则单独诊断。"""
    primary = _score_output(case, output)
    raw = _score_output(case, output if raw_submission is _UNSET else raw_submission)
    raw_fields = ('output_valid', 'validation_error', 'source_ids_ok', 'raw_contract_valid',
        'completed_entities_unchanged', 'plan_feasible', 'raw_task_count', 'effective_task_count',
        'unchanged_existing_tasks', 'changes_only_contract', 'hallucinated_tasks',
        'missing_information_error', 'extra_question_labels', 'duplicate_keys', 'duplicate_existing_ids',
        'semantic_success', 'checks')
    for name in raw_fields:
        primary['raw_model_' + name.removeprefix('raw_')] = raw[name]
    primary['strict_success'] = bool(primary['strict_success'] and raw['output_valid'] and
        raw['source_ids_ok'] and raw['raw_contract_valid'] and raw['completed_entities_unchanged'] and
        raw['plan_feasible'] and raw['changes_only_contract'] and not raw['missing_information_error'] and
        not raw['hallucinated_tasks'])
    return primary


def _aggregate(items):
    return counts(**{key:sum(v.get(key, 0) for v in items) for key in ('tp', 'fp', 'fn')})


def _known_sum(values):
    return sum(values) if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values) else None


def summarize(records):
    result = dict(groups={}, limitations=[
        'semantic_success 与旧实验严格成功率使用不同口径，不能直接比较数值。',
        '对比包含版本提示和工具能力的整体方案差异，不能归因于纯工具机制。',
        '严格标签与标题别名在输出前冻结；等义表达可能被机械评分低估，人工意见不得回改标签。',
        '仅完整且按样例和重复次数平衡的 live 评价可排名；not_run 单列，失败保留在实际尝试分母。'])
    for group in sorted({r['group'] for r in records}):
        planned = [r for r in records if r['group'] == group]
        attempts = [r for r in planned if r['status'] != 'not_run']
        scores = [r['score'] for r in attempts if r.get('score') is not None]
        calls = [c for r in attempts for c in r.get('api_calls', [])]
        plans = [s for s in scores if s['plan_eligible']]
        durations = [r['elapsed_ms'] for r in attempts if r.get('elapsed_ms') is not None]
        result['groups'][group] = dict(planned=len(planned), attempted=len(attempts),
            not_run=len(planned) - len(attempts), completed=sum(r['status'] == 'completed' for r in attempts),
            invalid=sum(r['status'] == 'invalid' for r in attempts), failed=sum(r['status'] == 'failed' for r in attempts),
            semantic_success=sum(s['semantic_success'] for s in scores), strict_success=sum(s['strict_success'] for s in scores),
            semantic_success_rate_attempted=sum(s['semantic_success'] for s in scores) / len(attempts) if attempts else None,
            strict_success_rate_attempted=sum(s['strict_success'] for s in scores) / len(attempts) if attempts else None,
            scored_attempts=len(scores), plan_eligible_attempts=len(plans), feasible_plans=sum(s['plan_feasible'] for s in plans),
            completed_entities_unchanged=sum(s['completed_entities_unchanged'] for s in scores),
            changes_only_contract_passes=sum(s['changes_only_contract'] for s in scores),
            unchanged_existing_tasks=sum(s['unchanged_existing_tasks'] for s in scores),
            raw_model_unchanged_existing_tasks=sum(s['raw_model_unchanged_existing_tasks'] for s in scores),
            raw_model_hallucinated_tasks=sum(s['raw_model_hallucinated_tasks'] for s in scores),
            raw_model_missing_information_errors=sum(s['raw_model_missing_information_error'] for s in scores),
            hallucinated_tasks=sum(s['hallucinated_tasks'] for s in scores),
            missing_information_errors=sum(s['missing_information_error'] for s in scores),
            required_question_labels=sum(len(s['question_labels_required']) for s in scores),
            found_required_question_labels=sum(len(set(s['question_labels_required']) & set(s['question_labels_found'])) for s in scores),
            extra_question_labels=sum(len(s['extra_question_labels']) for s in scores),
            unknown_questions=sum(s['unknown_questions'] for s in scores),
            unexpected_plan_questions=sum(s['unexpected_plan_questions'] for s in scores),
            extraction=_aggregate([s['extraction'] for s in scores]),
            task_extraction=_aggregate([s['extraction']['tasks'] for s in scores]),
            field_extraction=_aggregate([s['extraction']['fields'] for s in scores]),
            constraint_pass_counts={code:sum(s['constraint_passes'][code] for s in scores) for code in CHECK_CODES},
            constraint_denominator=len(attempts), api_requests=len(calls),
            cost_usd=_known_sum([c.get('cost_usd') for c in calls]),
            cost_known_requests=sum(c.get('cost_usd') is not None for c in calls),
            tokens={field:_known_sum([(c.get('usage') or {}).get(field) for c in calls])
                    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
            mean_elapsed_ms=sum(durations) / len(durations) if durations else None,
            elapsed_known_attempts=len(durations))
    return result
