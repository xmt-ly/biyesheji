"""离线测试数据只用于验证实验代码，绝不写入真实实验记录。"""
import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    return importlib.import_module('experiments.reliability_v3.' + name)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'runner.py').exists(), '尚未实现独立 v3 评价器')

    def test_frozen_new_cases_and_no_label_leakage(self):
        cases = module('cases')
        runner = module('runner')
        state = module('state')
        all_cases = cases.frozen_cases('all')
        self.assertEqual((3, 6), tuple(sum(c['split'] == s for c in all_cases) for s in ('dev', 'eval')))
        self.assertEqual(cases.fingerprint(all_cases), cases.fingerprint(cases.frozen_cases('all')))
        for case in all_cases:
            self.assertTrue(all(m['created_at'].startswith('2026-10-20T09:') for m in case['messages']))
            with state.isolated_state(case) as db:
                context, messages = state.inputs(case, db)
            visible = json.dumps(runner.common_input(case, context, messages), ensure_ascii=False)
            self.assertNotIn('expected', visible)
            self.assertNotIn('aliases', visible)
            self.assertNotIn('question_labels', visible)
        all_cases[0]['messages'][0]['content'] = '篡改本地副本'
        self.assertNotEqual(cases.fingerprint(all_cases), cases.fingerprint(cases.frozen_cases('all')))

    def test_baseline_integrity_and_no_settings_startup(self):
        backend = module('backend')
        checks = backend.verify_baseline()
        self.assertEqual(7, len(checks))
        old = backend.baseline_provider_module()
        self.assertEqual('app.agent_v2_frozen', old.__name__)
        self.assertEqual('v2-tools', old.PROMPT_VERSION)
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp) / 'models.py'
            changed.write_text('changed', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'models.py'):
                backend.verify_baseline(overrides={'models.py': changed})

    def test_each_attempt_has_independent_real_sqlite(self):
        state, cases = module('state'), module('cases')
        from app.models import Task
        case = cases.frozen_cases()[0]
        with state.isolated_state(case) as first:
            first_context, first_messages = state.inputs(case, first)
            with first.Session() as db:
                db.get(Task, 632).title = '本次变更'
                db.commit()
        with state.isolated_state(case) as second:
            next_context, next_messages = state.inputs(case, second)
        self.assertEqual(first_context, next_context)
        self.assertEqual(first_messages, next_messages)
        jobs = module('runner').make_jobs(cases.frozen_cases(), ('baseline_v2', 'improved_v3'), 2, 20261020)
        self.assertEqual(24, len(jobs))
        self.assertEqual({'baseline_v2', 'improved_v3'}, {j['group'] for j in jobs[:2]})
        self.assertNotEqual(jobs[0]['group'], jobs[2]['group'])

    def test_default_dry_run_no_sdk_or_environment(self):
        runner = module('runner')
        with tempfile.TemporaryDirectory() as tmp:
            args = runner.parser().parse_args(['--output-dir', tmp])
            with patch.object(runner, 'live_settings', side_effect=AssertionError('dry-run不得读取凭据')), \
                 patch.object(runner, 'preflight', side_effect=AssertionError('dry-run不得联网')):
                self.assertEqual(0, asyncio.run(runner.run(args)))
            manifest = json.loads((Path(tmp) / 'manifest.json').read_text(encoding='utf-8'))
            summary = json.loads((Path(tmp) / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual('dry_run', manifest['run_mode'])
            self.assertIsNone(manifest['model'])
            self.assertEqual(24, summary['planned'])
            self.assertEqual(0, summary['model_requests'])
            self.assertFalse(summary['ranking_permitted'])
            self.assertTrue((Path(tmp) / 'attempts').is_dir())

    def test_labels_have_feasible_expected_plan_and_ignore_unstated_stage(self):
        cases, scoring = module('cases'), module('scoring')
        for case in cases.frozen_cases('all'):
            if case['expected']['outcome'] != 'plan':
                continue
            output = cases.offline_oracle(case)
            result = scoring.score(case, output)
            self.assertTrue(result['semantic_success'], (case['id'], result))
            for task in output['tasks']:
                if not case['expected']['tasks'][output['tasks'].index(task)]['stage_explicit']:
                    task['stage_index'] = 2
            self.assertTrue(scoring.score(case, output)['semantic_success'], case['id'])

    def test_raw_duplicates_wrong_ids_and_completed_mutation_cannot_be_hidden(self):
        cases, scoring = module('cases'), module('scoring')
        case = cases.frozen_cases()[0]
        output = cases.offline_oracle(case)
        unchanged = deepcopy(case['state']['tasks'][0])
        output['tasks'].append(unchanged)
        result = scoring.score(case, output)
        self.assertTrue(result['semantic_success'])
        self.assertEqual(1, result['unchanged_existing_tasks'])
        self.assertFalse(result['changes_only_contract'])
        output['tasks'].append(deepcopy(unchanged))
        self.assertFalse(scoring.score(case, output)['semantic_success'])
        output['tasks'].pop()
        output['tasks'][-1]['title'] = '非法修改完成任务'
        result = scoring.score(case, output)
        self.assertFalse(result['completed_entities_unchanged'])
        self.assertFalse(result['semantic_success'])
        self.assertEqual(0, result['unchanged_existing_tasks'])
        output['tasks'][-1] = dict(unchanged, existing_id=999)
        self.assertFalse(scoring.score(case, output)['semantic_success'])

    def test_source_hallucination_and_missing_information(self):
        cases, scoring = module('cases'), module('scoring')
        case = cases.frozen_cases()[0]
        output = cases.offline_oracle(case)
        output['source_message_ids'] *= 2
        self.assertFalse(scoring.score(case, output)['source_ids_ok'])
        output = cases.offline_oracle(case)
        output['tasks'].append(dict(output['tasks'][0], key='new_made_up', title='从未讨论的预算看板'))
        self.assertEqual(1, scoring.score(case, output)['hallucinated_tasks'])
        missing = cases.frozen_cases()[1]
        result = scoring.score(missing, output)
        self.assertTrue(result['missing_information_error'])
        self.assertFalse(result['semantic_success'])

    def test_only_missing_questions_and_extra_questions_reported_separately(self):
        cases, scoring = module('cases'), module('scoring')
        case = cases.frozen_cases()[2]
        output = cases.offline_oracle(case)
        self.assertTrue(scoring.score(case, output)['strict_success'])
        output['questions'].append('负责人是谁，预计多少工时？')
        result = scoring.score(case, output)
        self.assertTrue(result['semantic_success'])
        self.assertFalse(result['strict_success'])
        self.assertEqual({'assignee', 'hours'}, set(result['extra_question_labels']))

    def test_legal_kind_is_diagnostic_for_clarification_plan_and_adjustment(self):
        cases, scoring = module('cases'), module('scoring')
        for index in (1, 0, 4):  # E02追问、E01新增计划、E05调整。
            case = cases.frozen_cases()[index]
            for kind in ('discussion', 'plan', 'adjust'):
                with self.subTest(case=case['id'], mode=case['mode'], kind=kind):
                    output = cases.offline_oracle(case)
                    output['kind'] = kind
                    result = scoring.score(case, output)
                    self.assertTrue(result['output_valid'])
                    self.assertEqual(kind == case['mode'], result['kind_ok'])
                    self.assertTrue(result['semantic_success'])
                    self.assertTrue(result['strict_success'])

    def test_invalid_kind_remains_a_schema_failure(self):
        cases, scoring = module('cases'), module('scoring')
        for index in (1, 0, 4):
            with self.subTest(case=index):
                case = cases.frozen_cases()[index]
                output = cases.offline_oracle(case)
                output['kind'] = 'unsupported'
                result = scoring.score(case, output)
                self.assertFalse(result['output_valid'])
                self.assertEqual('ValidationError', result['validation_error'])
                self.assertFalse(result['semantic_success'])
                self.assertFalse(result['strict_success'])

    def test_legal_kind_cannot_resolve_questions_in_a_plan(self):
        cases, scoring = module('cases'), module('scoring')
        case = cases.frozen_cases()[0]
        for kind in ('discussion', 'plan', 'adjust'):
            with self.subTest(kind=kind):
                output = cases.offline_oracle(case)
                output.update(kind=kind, questions=['请确认是否采用这份计划？'])
                result = scoring.score(case, output)
                self.assertTrue(result['output_valid'])
                self.assertFalse(result['outcome_ok'])
                self.assertFalse(result['semantic_success'])
                self.assertFalse(result['strict_success'])

    def test_raw_content_accepts_only_bare_or_complete_json_fence_with_wrapper(self):
        cases, runner = module('cases'), module('runner')
        output = cases.offline_oracle(cases.frozen_cases()[1])
        output['title'] = '原模型标题必须原样保留'
        for value in (output, dict(analysis=output, task_evidence=[])):
            text = json.dumps(value, ensure_ascii=False)
            for content in (text, '  ' + text + '\n', '```json\n' + text + '\n```',
                            '```\n' + text + '\n```', ' \n```json\n' + text + '\n```\n '):
                with self.subTest(content=content[:25], wrapper='analysis' in value):
                    calls = [dict(response=dict(choices=[dict(message=dict(content=content))]))]
                    self.assertEqual(output, runner.raw_submission_from_calls(calls))

    def test_raw_content_rejects_multiple_fences_and_surrounding_text(self):
        cases, runner = module('cases'), module('runner')
        text = json.dumps(cases.offline_oracle(cases.frozen_cases()[1]), ensure_ascii=False)
        fence = '```json\n' + text + '\n```'
        for content in (fence + '\n' + fence, '说明\n' + fence, fence + '\n说明',
                        '说明' + text, text + '说明', text + text,
                        '```json\n' + text, '```python\n' + text + '\n```',
                        '```json ' + text + '```', None, '', '{broken'):
            with self.subTest(content=str(content)[:25]):
                calls = [dict(response=dict(choices=[dict(message=dict(content=content))]))]
                self.assertIsNone(runner.raw_submission_from_calls(calls))

    def test_raw_finalize_analysis_keeps_original_arguments_and_last_response_only(self):
        cases, runner = module('cases'), module('runner')
        output = cases.offline_oracle(cases.frozen_cases()[1])
        output['tasks'] = [deepcopy(cases.frozen_cases()[1]['state']['tasks'][0])]
        call = dict(function=dict(name='finalize_analysis', arguments=json.dumps(
            dict(analysis=output, task_evidence=[]), ensure_ascii=False)))
        response = dict(choices=[dict(message=dict(content=None, tool_calls=[call]))])
        calls = [dict(response=response)]
        self.assertEqual(output, runner.raw_submission_from_calls(calls))
        self.assertEqual(1, len(runner.raw_submission_from_calls(calls)['tasks']))
        self.assertIsNone(runner.raw_submission_from_calls(calls + [dict(response=None)]))
        self.assertIsNone(runner.raw_submission_from_calls([]))

    def test_preserve_title_is_exact_even_when_another_alias_matches(self):
        cases, scoring = module('cases'), module('scoring')
        for case in cases.frozen_cases()[4:]:
            output = cases.offline_oracle(case)
            output['tasks'][0]['title'] = case['expected']['tasks'][0]['aliases'][1]
            self.assertFalse(scoring.score(case, output)['semantic_success'], case['id'])

    def test_equivalent_questions_and_asserted_start_context(self):
        cases, scoring = module('cases'), module('scoring')
        case = cases.frozen_cases()[2]
        output = cases.offline_oracle(case)
        for text in ('请问这项任务最晚应在哪天结束？', '已确认10月26日开始，这项任务计划哪天交付？'):
            output['questions'] = [text]
            self.assertTrue(scoring.score(case, output)['strict_success'], text)

    def test_equivalent_video_acceptance_and_plan_questions_are_unresolved(self):
        cases, scoring = module('cases'), module('scoring')
        case = cases.frozen_cases()[0]
        output = cases.offline_oracle(case)
        output['tasks'][0]['acceptance'] = '演示搜索设备并发起预约申请'
        self.assertTrue(scoring.score(case, output)['semantic_success'])
        output['questions'] = ['请确认是否采用这份计划？']
        self.assertFalse(scoring.score(case, output)['semantic_success'])

    def test_explicit_negation_cannot_satisfy_positive_acceptance_labels(self):
        cases, scoring = module('cases'), module('scoring')
        for index, acceptance in ((0, '视频不得查找设备，也不得提交预约'), (3, '盘点数量与设备目录不一致')):
            case = cases.frozen_cases()[index]
            output = cases.offline_oracle(case)
            output['tasks'][0]['acceptance'] = acceptance
            self.assertFalse(scoring.score(case, output)['semantic_success'], acceptance)

    def test_acceptance_failure_condition_and_forbidden_omission_are_positive(self):
        cases, scoring = module('cases'), module('scoring')
        examples = ((3, '盘点数量与设备目录一致；如不一致则验收不通过'),
                    (0, '演示查找设备并提交预约，不允许跳过提交预约步骤'))
        for index, acceptance in examples:
            with self.subTest(acceptance=acceptance):
                case = cases.frozen_cases()[index]
                output = cases.offline_oracle(case)
                output['tasks'][0]['acceptance'] = acceptance
                result = scoring.score(case, output)
                self.assertTrue(result['semantic_success'])
                self.assertTrue(result['strict_success'])

    def test_unknown_usage_costs_and_failures_stay_in_actual_denominator(self):
        scoring, runner, cases = module('scoring'), module('runner'), module('cases')
        jobs = runner.make_jobs(cases.frozen_cases()[:1], ('baseline_v2', 'improved_v3'), 1, 1)
        baseline = next(job for job in jobs if job['group'] == 'baseline_v2')
        baseline.update(status='failed', score=scoring.score(cases.frozen_cases()[0], None), api_calls=[{'usage':None, 'cost_usd':None}])
        result = scoring.summarize(jobs)['groups']['baseline_v2']
        self.assertEqual(1, result['attempted'])
        self.assertEqual(0, result['semantic_success'])
        self.assertEqual(0, result['semantic_success_rate_attempted'])
        self.assertIsNone(result['tokens']['total_tokens'])
        self.assertIsNone(result['cost_usd'])

    def test_budget_and_zero_price_guard(self):
        from experiments.transport import Budget, BudgetExceeded, GuardStopped, validate_preflight
        budget = Budget(1)
        budget.consume()
        with self.assertRaises(BudgetExceeded):
            budget.consume()
        key = {'data': {'free_model_daily_requests': {'remaining': 3}}}
        for pricing in ({'prompt': '0.01', 'completion': '0'}, {'prompt': '0'}, {'prompt': 'unknown', 'completion': '0'}):
            with self.assertRaises(GuardStopped):
                validate_preflight('fixed', {'data': [{'id': 'fixed', 'pricing': pricing}]}, key, 180)
        with self.assertRaises(GuardStopped):
            validate_preflight('fixed', {'data': [{'id':'fixed','pricing':{'prompt':'0','completion':'0'}}]}, {'data':{}}, 180)

    def test_interruption_recovery_without_fabricated_response_and_complete_flag(self):
        cases, runner, scoring = module('cases'), module('runner'), module('scoring')
        with tempfile.TemporaryDirectory() as tmp:
            args = runner.parser().parse_args(['--output-dir', tmp])
            asyncio.run(runner.run(args))
            root = Path(tmp)
            jobs = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            jobs[0].update(status='running', api_calls=[{'sequence':1,'request':{},'response':None,'usage':None,'cost_usd':None,'error':None}])
            runner.write_json(root / 'records.json', jobs)
            args.summarize = True
            self.assertEqual(0, asyncio.run(runner.run(args)))
            restored = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            self.assertEqual('failed', restored[0]['status'])
            self.assertIsNone(restored[0]['api_calls'][0]['response'])
            self.assertFalse(restored[0]['score']['semantic_success'])
            summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
            self.assertFalse(summary['comparison_complete'])
            self.assertFalse(summary['ranking_permitted'])

    def test_interrupted_running_attempt_cannot_count_success_even_with_saved_partial_output(self):
        cases, runner = module('cases'), module('runner')
        with tempfile.TemporaryDirectory() as tmp:
            args = runner.parser().parse_args(['--output-dir', tmp])
            asyncio.run(runner.run(args))
            root = Path(tmp)
            jobs = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            jobs[0].update(status='running', output=cases.offline_oracle(cases.frozen_cases()[0]))
            runner.write_json(root / 'records.json', jobs)
            args.summarize = True
            asyncio.run(runner.run(args))
            restored = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            self.assertEqual('failed', restored[0]['status'])
            self.assertFalse(restored[0]['score']['semantic_success'])

    def test_ranking_requires_complete_exact_case_repeat_matrix(self):
        cases, runner, scoring = module('cases'), module('runner'), module('scoring')
        with tempfile.TemporaryDirectory() as tmp:
            args = runner.parser().parse_args(['--output-dir', tmp])
            asyncio.run(runner.run(args))
            root = Path(tmp)
            manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
            manifest['run_mode'] = 'live'  # 只在临时目录测试汇总判定，绝不是真实实验记录。
            jobs = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            for job in jobs:
                case = next(c for c in cases.frozen_cases() if c['id'] == job['case_id'])
                job.update(status='completed', score=scoring.score(case, cases.offline_oracle(case)))
            self.assertTrue(runner.refresh_summary(root, manifest, jobs)['ranking_permitted'])
            for job in jobs[-2:]:
                job['repetition'] = 1  # 两组同样缺第2重复，但单纯数量仍平衡。
            result = runner.refresh_summary(root, manifest, jobs)
            self.assertFalse(result['ranking_permitted'])
            self.assertFalse(result['comparison_complete'])

    def test_runner_api_also_enforces_global_180_limit(self):
        runner = module('runner')
        from experiments.transport import GuardStopped
        with tempfile.TemporaryDirectory() as tmp:
            args = runner.parser().parse_args(['--max-calls', '181', '--output-dir', tmp])
            with self.assertRaises(GuardStopped):
                asyncio.run(runner.run(args))

    def test_stopped_preflight_preserves_whole_plan_and_saved_score_only_summary(self):
        runner = module('runner')
        from experiments.transport import GuardStopped
        with tempfile.TemporaryDirectory() as tmp:
            args = runner.parser().parse_args(['--live', '--output-dir', tmp])
            settings = SimpleNamespace(llm_api_key='offline-only-secret', llm_model='offline-only-model',
                llm_base_url='https://openrouter.ai/api/v1', agent_timeout_seconds=60, ai_ready=True)
            with patch.object(runner, 'live_settings', return_value=settings), \
                 patch.object(runner, 'verify_freeze', return_value={'offline_test_only': True}), \
                 patch.object(runner, 'preflight', side_effect=GuardStopped('未知免费额度')):
                self.assertEqual(2, asyncio.run(runner.run(args)))
            root = Path(tmp)
            records = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            self.assertEqual(24, len(records))
            self.assertTrue(all(job['status'] == 'not_run' for job in records))
            args.live, args.summarize = False, True
            with patch.object(runner, 'score', side_effect=AssertionError('终态不能重新评分')), \
                 patch.object(runner, 'live_settings', side_effect=AssertionError('汇总不能读取凭据')):
                self.assertEqual(0, asyncio.run(runner.run(args)))
            self.assertEqual(0, json.loads((root / 'summary.json').read_text(encoding='utf-8'))['model_requests'])


class RecoveryTests(unittest.TestCase):
    def _crash_window(self, root, *, completed=False):
        cases, runner = module('cases'), module('runner')
        args = runner.parser().parse_args(['--output-dir', str(root)])
        asyncio.run(runner.run(args))
        output = cases.offline_oracle(cases.frozen_cases()[1])
        sdk = SDKIntegrationTests()
        def handler(request):
            return sdk.response(dict(role='assistant', content=json.dumps(output)))
        terminal, _, snapshots, _ = asyncio.run(sdk._execute('improved_v3', handler))
        attempt = terminal if completed else next(s for s in reversed(snapshots)
            if s['status'] == 'running' and s['api_calls'] and s['api_calls'][0]['response'] is not None
            and s['tools'] and s['tools'][-1]['result'] is not None)
        jobs = json.loads((root / 'records.json').read_text(encoding='utf-8'))
        old = next(job for job in jobs if job['job_id'] == attempt['job_id'])
        old.update(status='running', api_calls=[deepcopy(attempt['api_calls'][0])])
        old['api_calls'][0].update(response=None, usage=None, cost_usd=None, error=None, elapsed_ms=None)
        runner.write_json(root / 'records.json', jobs)
        attempt_path = root / 'attempts' / (attempt['job_id'] + '.json')
        runner.write_json(attempt_path, attempt)
        return runner, jobs, old, attempt, attempt_path

    @staticmethod
    def _saved_files(root):
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*.json')}

    def test_attempt_restores_returned_response_usage_and_tools_after_replace_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner, _, old, attempt, attempt_path = self._crash_window(root)
            self.assertIsNone(old['api_calls'][0]['response'])
            self.assertEqual([], old['tools'])
            self.assertEqual(0, runner.summarize_saved(root))
            jobs = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            recovered = next(job for job in jobs if job['job_id'] == attempt['job_id'])
            self.assertEqual(attempt['api_calls'], recovered['api_calls'])
            self.assertEqual(attempt['tools'], recovered['tools'])
            self.assertIsNotNone(recovered['api_calls'][0]['usage'])
            self.assertEqual('failed', recovered['status'])
            self.assertEqual('InterruptedAnalysis', recovered['error']['type'])
            self.assertFalse(recovered['score']['semantic_success'])
            self.assertEqual(recovered, json.loads(attempt_path.read_text(encoding='utf-8')))
            self.assertEqual(1, json.loads((root / 'summary.json').read_text(encoding='utf-8'))['model_requests'])

    def test_completed_attempt_is_preserved_without_rescoring_stale_running_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner, _, _, attempt, attempt_path = self._crash_window(root, completed=True)
            with patch.object(runner, 'score', wraps=runner.score) as rescore:
                self.assertEqual(0, runner.summarize_saved(root))
            jobs = json.loads((root / 'records.json').read_text(encoding='utf-8'))
            recovered = next(job for job in jobs if job['job_id'] == attempt['job_id'])
            self.assertEqual('completed', recovered['status'])
            self.assertEqual(attempt, recovered)
            rescore.assert_not_called()
            self.assertEqual(attempt, json.loads(attempt_path.read_text(encoding='utf-8')))

    def test_attempt_identity_and_input_hash_conflicts_reject_without_any_writes(self):
        from experiments.transport import GuardStopped
        mutations = {
            'job_id': lambda value: value.update(job_id='wrong-job'),
            'case_id': lambda value: value.update(case_id='V3E01'),
            'group': lambda value: value.update(group='baseline_v2'),
            'repetition': lambda value: value.update(repetition=2),
            'input_hash': lambda value: value.update(common_input_sha256='0' * 64),
            'input_content': lambda value: value['common_input'].update(mode='adjust'),
        }
        for name, mutate in mutations.items():
            with self.subTest(conflict=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                runner, jobs, _, attempt, attempt_path = self._crash_window(root)
                jobs[0]['status'] = 'running'  # 后项冲突时也不得先改写前项。
                runner.write_json(root / 'records.json', jobs)
                mutate(attempt)
                if name == 'input_content':
                    attempt['common_input_sha256'] = module('cases').fingerprint(attempt['common_input'])
                runner.write_json(attempt_path, attempt)
                before = self._saved_files(root)
                with self.assertRaises(GuardStopped):
                    runner.summarize_saved(root)
                self.assertEqual(before, self._saved_files(root))

    def test_attempt_request_prefix_and_known_evidence_conflicts_reject_without_writes(self):
        from experiments.transport import GuardStopped
        for name in ('request', 'sequence', 'response', 'usage', 'cost', 'tool_arguments', 'tool_result', 'regression'):
            with self.subTest(conflict=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                runner, jobs, old, attempt, attempt_path = self._crash_window(root)
                if name == 'request':
                    attempt['api_calls'][0]['request']['model'] = 'changed-model'
                elif name == 'sequence':
                    attempt['api_calls'][0]['sequence'] += 1
                elif name in ('response', 'usage', 'cost'):
                    old['api_calls'] = deepcopy(attempt['api_calls'])
                    if name == 'response':
                        attempt['api_calls'][0]['response']['id'] = 'conflicting-response'
                    elif name == 'usage':
                        attempt['api_calls'][0]['usage']['total_tokens'] += 1
                    else:
                        attempt['api_calls'][0]['cost_usd'] = 1
                elif name.startswith('tool_'):
                    old['tools'] = deepcopy(attempt['tools'])
                    if name == 'tool_arguments':
                        attempt['tools'][0]['arguments'] = {'changed': True}
                    else:
                        attempt['tools'][0]['result'] = {'conflicting': True}
                else:
                    attempt['api_calls'] = []
                runner.write_json(root / 'records.json', jobs)
                runner.write_json(attempt_path, attempt)
                before = self._saved_files(root)
                with self.assertRaises(GuardStopped):
                    runner.summarize_saved(root)
                self.assertEqual(before, self._saved_files(root))

    def test_unknown_attempt_filename_rejects_without_writes(self):
        from experiments.transport import GuardStopped
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner, _, _, attempt, _ = self._crash_window(root)
            runner.write_json(root / 'attempts' / 'unknown-job.json', attempt)
            before = self._saved_files(root)
            with self.assertRaises(GuardStopped):
                runner.summarize_saved(root)
            self.assertEqual(before, self._saved_files(root))


class SDKIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def _execute(self, group, handler, *, budget_limit=180, timeout=None, constructions=None):
        import httpx
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient
        from experiments.transport import Budget
        backend, cases, runner = module('backend'), module('cases'), module('runner')
        provider_module = backend.baseline_provider_module() if group == 'baseline_v2' else importlib.import_module('app.agent')
        case = cases.frozen_cases()[1]
        job = runner.make_jobs([case], (group,), 1, 0)[0]
        settings = SimpleNamespace(llm_api_key='offline-test-only', llm_model='offline-fixture',
            llm_base_url='https://offline.invalid/v1', agent_timeout_seconds=60, ai_ready=True)
        def http_factory(**kwargs):
            if constructions is not None:
                constructions.append(('http', dict(kwargs)))
            return DefaultAsyncHttpxClient(**kwargs, transport=httpx.MockTransport(handler))
        def sdk_factory(**kwargs):
            if 'http_client' not in kwargs:
                kwargs['http_client'] = http_factory()
            if constructions is not None:
                constructions.append(('sdk', dict(kwargs)))
            return AsyncOpenAI(**kwargs)
        snapshots = []
        budget = Budget(budget_limit)
        with patch.object(provider_module, 'AsyncOpenAI', sdk_factory), \
             patch('openai.AsyncOpenAI', sdk_factory), \
             patch('openai.DefaultAsyncHttpxClient', http_factory):
            if timeout is None:
                await runner.execute_job(job, case, settings, budget, lambda: snapshots.append(deepcopy(job)))
            else:
                with patch.object(runner, 'ANALYSIS_TIMEOUT_SECONDS', timeout):
                    await runner.execute_job(job, case, settings, budget, lambda: snapshots.append(deepcopy(job)))
        return job, budget, snapshots, case

    @staticmethod
    def response(message, *, usage=True):
        import httpx
        value = dict(id='offline-http-fixture', object='chat.completion', created=1, model='offline-fixture',
            choices=[dict(index=0, finish_reason='tool_calls' if message.get('tool_calls') else 'stop', message=message)])
        if usage:
            value['usage'] = dict(prompt_tokens=2, completion_tokens=3, total_tokens=5, cost=0)
        return httpx.Response(200, json=value)

    async def test_default_sdk_construction_explicitly_disables_redirects_for_both_groups(self):
        cases = module('cases')
        for group in ('baseline_v2', 'improved_v3'):
            with self.subTest(group=group):
                constructions = []
                def handler(request):
                    output = cases.offline_oracle(cases.frozen_cases()[1])
                    return self.response(dict(role='assistant', content=json.dumps(output)))
                job, _, _, _ = await self._execute(group, handler, constructions=constructions)
                self.assertEqual('completed', job['status'], job)
                http_options = [options for kind, options in constructions if kind == 'http']
                sdk_options = [options for kind, options in constructions if kind == 'sdk']
                self.assertEqual(1, len(http_options), '不得先构造会跟随重定向的默认客户端')
                self.assertIs(False, http_options[0].get('follow_redirects'))
                self.assertEqual(1, len(sdk_options))
                self.assertEqual(0, sdk_options[0]['max_retries'])
                self.assertEqual(60, sdk_options[0]['timeout'])
                self.assertEqual('offline-test-only', sdk_options[0]['api_key'])
                self.assertEqual('https://offline.invalid/v1', sdk_options[0]['base_url'])
                self.assertFalse(sdk_options[0]['http_client'].follow_redirects)

    async def test_default_sdk_redirect_fails_after_one_recorded_post(self):
        import httpx
        cases = module('cases')
        for group in ('baseline_v2', 'improved_v3'):
            with self.subTest(group=group):
                requests = []
                def handler(request):
                    requests.append(request)
                    if len(requests) == 1:
                        return httpx.Response(307, headers={'Location': 'https://offline.invalid/redirected'})
                    output = cases.offline_oracle(cases.frozen_cases()[1])
                    return self.response(dict(role='assistant', content=json.dumps(output)))
                job, budget, _, _ = await self._execute(group, handler, budget_limit=1)
                self.assertEqual(1, len(requests), '重定向不得绕过一次请求预算')
                self.assertEqual('POST', requests[0].method)
                self.assertEqual(1, budget.used)
                self.assertEqual(1, len(job['api_calls']))
                self.assertEqual('failed', job['status'])
                self.assertEqual(307, job['error']['status_code'])
                self.assertIsNone(job['api_calls'][0]['response'])
                self.assertIsNone(job['api_calls'][0]['usage'])
                self.assertFalse(job['score']['semantic_success'])

    async def test_injected_provider_keeps_its_local_sdk_transport(self):
        import httpx
        from openai import AsyncOpenAI
        from experiments.transport import Budget
        cases, runner = module('cases'), module('runner')
        case = cases.frozen_cases()[1]
        output = cases.offline_oracle(case)
        seen = []
        def handler(request):
            seen.append(request)
            return self.response(dict(role='assistant', content=json.dumps(output)))
        client = AsyncOpenAI(api_key='offline-only', base_url='https://offline.invalid/v1', max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        class InjectedProvider:
            def __init__(self, settings):
                self.client = client
            async def analyze(self, context, tools, mode, messages):
                await self.client.chat.completions.create(model='offline-fixture', messages=[])
                return dict(output=output)
            async def close(self):
                await self.client.close()
        job = runner.make_jobs([case], ('baseline_v2',), 1)[0]
        settings = SimpleNamespace(llm_api_key='offline-only')
        await runner.execute_job(job, case, settings, Budget(1), provider_factory=InjectedProvider)
        self.assertEqual(1, len(seen))
        self.assertEqual('completed', job['status'], job)
        self.assertTrue(client.is_closed())

    async def test_real_sdk_local_transport_old_json_and_new_finalize(self):
        cases, scoring = module('cases'), module('scoring')
        seen = []
        for group in ('baseline_v2', 'improved_v3'):
            def handler(request):
                body = json.loads(request.content)
                seen.append(body)
                output = cases.offline_oracle(cases.frozen_cases()[1])
                if group == 'baseline_v2':
                    message = dict(role='assistant', content=json.dumps(output, ensure_ascii=False))
                else:
                    message = dict(role='assistant', content=None, tool_calls=[dict(id='offline-final', type='function',
                        function=dict(name='finalize_analysis', arguments=json.dumps(dict(analysis=output, task_evidence=[]), ensure_ascii=False)))])
                return self.response(message)
            job, budget, snapshots, case = await self._execute(group, handler)
            self.assertEqual('completed', job['status'], job)
            self.assertTrue(job['score']['semantic_success'])
            self.assertEqual(1, budget.used)
            self.assertEqual(1, len(job['api_calls']))
            self.assertTrue(any(s['api_calls'] and s['api_calls'][0]['response'] is None for s in snapshots))
            self.assertTrue(any(s['api_calls'] and s['api_calls'][0]['response'] is not None for s in snapshots))
            self.assertEqual(0, job['api_calls'][0]['cost_usd'])
        self.assertEqual(0.2, seen[0]['temperature'])
        self.assertEqual(seen[0]['messages'][1], seen[1]['messages'][1])
        self.assertEqual('0', seen[0]['provider']['max_price']['prompt'])
        self.assertFalse(seen[0]['provider']['allow_fallbacks'])

    async def test_real_sdk_local_fenced_json_preserves_raw_strict_success(self):
        cases = module('cases')
        output = cases.offline_oracle(cases.frozen_cases()[1])
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                value = dict(analysis=output, task_evidence=[]) if wrapped else output
                content = '```json\n' + json.dumps(value, ensure_ascii=False) + '\n```'
                def handler(request):
                    return self.response(dict(role='assistant', content=content))
                job, budget, _, _ = await self._execute('improved_v3', handler)
                self.assertEqual('completed', job['status'], job)
                self.assertTrue(job['score']['semantic_success'])
                self.assertEqual(output, job['raw_submission'])
                self.assertTrue(job['score']['strict_success'])
                self.assertEqual(1, budget.used)

    async def test_real_sdk_local_discussion_kind_can_return_e02_questions(self):
        cases = module('cases')
        output = cases.offline_oracle(cases.frozen_cases()[1])
        output['kind'] = 'discussion'
        def handler(request):
            return self.response(dict(role='assistant', content=json.dumps(output, ensure_ascii=False)))
        job, budget, _, _ = await self._execute('improved_v3', handler)
        self.assertEqual('completed', job['status'], job)
        self.assertEqual('discussion', job['output']['kind'])
        self.assertEqual([], job['output']['tasks'])
        self.assertFalse(job['score']['kind_ok'])
        self.assertTrue(job['score']['semantic_success'])
        self.assertTrue(job['score']['strict_success'])
        self.assertEqual(1, budget.used)

    async def test_new_provider_normalization_does_not_hide_raw_redundancy(self):
        cases = module('cases')
        def handler(request):
            case = cases.frozen_cases()[1]
            output = cases.offline_oracle(case)
            output['tasks'] = [deepcopy(case['state']['tasks'][0])]
            return self.response(dict(role='assistant', content=None, tool_calls=[dict(id='offline-final', type='function',
                function=dict(name='finalize_analysis', arguments=json.dumps(dict(analysis=output, task_evidence=[]), ensure_ascii=False)))]))
        job, _, _, _ = await self._execute('improved_v3', handler)
        self.assertTrue(job['score']['semantic_success'], job)
        self.assertFalse(job['score']['strict_success'])
        self.assertEqual(0, job['score']['unchanged_existing_tasks'])
        self.assertEqual(1, job['score']['raw_model_unchanged_existing_tasks'])
        self.assertEqual([], job['output']['tasks'])
        self.assertEqual(1, len(job['raw_submission']['tasks']))

    async def test_unsupported_raw_task_becomes_four_safe_questions_in_public_output(self):
        cases = module('cases')
        def handler(request):
            output = cases.offline_oracle(cases.frozen_cases()[0])
            output['tasks'][0]['assignee_id'] = 999
            output['tasks'][0]['requirement_id'] = 999
            return self.response(dict(role='assistant', content=None, tool_calls=[dict(id='offline-final', type='function',
                function=dict(name='finalize_analysis', arguments=json.dumps(dict(analysis=output, task_evidence=[]), ensure_ascii=False)))]))
        job, _, _, _ = await self._execute('improved_v3', handler)
        self.assertEqual('completed', job['status'], job)
        self.assertTrue(job['score']['semantic_success'], job)
        self.assertFalse(job['score']['strict_success'])
        self.assertEqual([], job['output']['tasks'])
        self.assertEqual({'assignee', 'hours', 'start_date', 'due_date'}, set(job['score']['question_labels_found']))
        self.assertTrue(job['score']['raw_model_missing_information_error'])
        self.assertFalse(job['score']['raw_model_plan_feasible'])

    async def test_six_round_limit_and_recorded_tool_checkpoints(self):
        def handler(request):
            return self.response(dict(role='assistant', content=None, tool_calls=[dict(id='offline-query', type='function',
                function=dict(name='get_tasks', arguments='{}'))]))
        job, budget, snapshots, _ = await self._execute('baseline_v2', handler)
        self.assertEqual('failed', job['status'])
        self.assertEqual(6, budget.used)
        self.assertEqual(6, len(job['tools']))
        self.assertTrue(any(s['tools'] and s['tools'][-1]['result'] is not None for s in snapshots))

    async def test_failed_http_counts_once_sdk_retry_disabled_and_cost_unknown(self):
        import httpx
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(503, json={'error': {'message': 'offline failure'}})
        job, budget, _, _ = await self._execute('baseline_v2', handler)
        self.assertEqual('failed', job['status'])
        self.assertEqual(1, len(requests))
        self.assertEqual(1, budget.used)
        self.assertIsNone(job['api_calls'][0]['response'])
        self.assertIsNone(job['api_calls'][0]['usage'])
        self.assertIsNone(job['api_calls'][0]['cost_usd'])

    async def test_total_deadline_and_global_budget_stop(self):
        async def slow_handler(request):
            await asyncio.sleep(0.2)
            return self.response(dict(role='assistant', content='{}'))
        job, budget, _, _ = await self._execute('baseline_v2', slow_handler, timeout=0.01)
        self.assertEqual('failed', job['status'])
        self.assertEqual('TimeoutError', job['error']['type'])
        self.assertEqual(1, budget.used)
        self.assertIsNone(job['api_calls'][0]['response'])
        def tools_handler(request):
            return self.response(dict(role='assistant', content=None, tool_calls=[dict(id='offline-query', type='function',
                function=dict(name='get_tasks', arguments='{}'))]))
        job, budget, _, _ = await self._execute('baseline_v2', tools_handler, budget_limit=1)
        self.assertEqual('BudgetExceeded', job['stop_reason'])
        self.assertEqual(1, budget.used)
        self.assertEqual(1, len(job['api_calls']))

    async def test_actual_nonzero_cost_stops_and_unknown_usage_stays_null(self):
        cases = module('cases')
        def costly_handler(request):
            response = self.response(dict(role='assistant', content=json.dumps(cases.offline_oracle(cases.frozen_cases()[1]))))
            value = response.json()
            value['usage']['cost'] = 0.01
            import httpx
            return httpx.Response(200, json=value)
        job, budget, _, _ = await self._execute('baseline_v2', costly_handler)
        self.assertEqual('GuardStopped', job['stop_reason'])
        self.assertEqual('failed', job['status'])
        self.assertEqual(1, budget.used)
        self.assertEqual(0.01, job['api_calls'][0]['cost_usd'])
        self.assertIsNone(job['output'])
        def unknown_handler(request):
            return self.response(dict(role='assistant', content='null'), usage=False)
        job, _, _, _ = await self._execute('baseline_v2', unknown_handler)
        self.assertEqual('invalid', job['status'])
        self.assertIsNone(job['output'])
        self.assertIsNone(job['api_calls'][0]['usage'])
        self.assertIsNone(job['api_calls'][0]['cost_usd'])


if __name__ == '__main__':
    unittest.main()
