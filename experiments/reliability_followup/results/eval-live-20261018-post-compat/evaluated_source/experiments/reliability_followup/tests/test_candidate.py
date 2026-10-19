"""修订后新题目与归档边界；只运行离线合成数据。"""
from datetime import datetime, timedelta
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
OLD = ROOT.parent / 'reliability_v3'


def module(name):
    return importlib.import_module('experiments.reliability_followup.' + name)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'cases.py').is_file(), '新业务题目尚未准备')

    def test_execution_sources_are_byte_identical_to_reviewed_v3(self):
        for name in ('runner.py', 'scoring.py', 'state.py', 'backend.py', '__init__.py'):
            with self.subTest(file=name):
                self.assertEqual((OLD / name).read_bytes(), (ROOT / name).read_bytes())
        old_files = {p.name: p.read_bytes() for p in (OLD / 'baseline').iterdir() if p.is_file()}
        new_files = {p.name: p.read_bytes() for p in (ROOT / 'baseline').iterdir() if p.is_file()}
        self.assertEqual(old_files, new_files)

    def test_preexisting_sources_results_and_locks_remain_unchanged(self):
        before = json.loads((ROOT / 'protected_before.json').read_text(encoding='utf-8'))
        self.assertTrue(any('/results/' in path for path in before))
        self.assertIn('experiments/reliability_v3/freeze.json', before)
        for name, expected in before.items():
            with self.subTest(file=name):
                self.assertEqual(expected, hashlib.sha256((PROJECT / name).read_bytes()).hexdigest())

    def test_business_cases_are_new_and_deep_copied(self):
        cases = module('cases')
        old = importlib.import_module('experiments.reliability_v3.cases')
        new_cases = cases.frozen_cases('all')
        self.assertEqual((3, 6), tuple(sum(c['split'] == split for c in new_cases) for split in ('dev', 'eval')))
        self.assertEqual(9, len({c['id'] for c in new_cases}))
        self.assertTrue(all(c['id'].startswith(('FUE', 'FUD')) for c in new_cases))
        self.assertNotEqual(old.VERSION, cases.VERSION)
        self.assertNotEqual(old.STAMP, cases.STAMP)
        old_state, new_state = old.base_state(), cases.base_state()
        for group in ('requirements', 'tasks'):
            field = 'id' if group == 'requirements' else 'existing_id'
            self.assertTrue({t[field] for t in old_state[group]}.isdisjoint(t[field] for t in new_state[group]))
        self.assertTrue({u['name'] for u in old_state['users']}.isdisjoint(u['name'] for u in new_state['users']))
        old_texts = {m['content'] for c in old.frozen_cases('all') for m in c['messages']}
        self.assertTrue(old_texts.isdisjoint(m['content'] for c in new_cases for m in c['messages']))
        new_cases[0]['state']['tasks'][0]['title'] = '副本修改'
        self.assertNotEqual(new_cases[0], cases.frozen_cases('all')[0])

    def test_fixed_timezone_message_identity_and_creator_integrity(self):
        cases, state = module('cases'), module('state')
        stamp = datetime.fromisoformat(cases.STAMP)
        self.assertEqual(timedelta(hours=8), stamp.utcoffset())
        for case in cases.frozen_cases('all'):
            users = {u['id'] for u in case['state']['users']}
            members = {m['user_id'] for m in case['state']['members']}
            self.assertIn(21, members)  # 固定 state.py 的 creator_id，仍为团队组长。
            self.assertTrue(all(m['user_id'] in users & members for m in case['messages']))
            self.assertEqual(len(case['messages']), len({m['id'] for m in case['messages']}))
            for index, message in enumerate(case['messages']):
                self.assertEqual(stamp + timedelta(minutes=index), datetime.fromisoformat(message['created_at']))
                self.assertGreaterEqual(message['id'], 3701)
                self.assertTrue(message['client_id'].startswith(case['id']))
            with state.isolated_state(case) as database:
                from sqlalchemy import text
                with database.Session() as db:
                    self.assertEqual([], db.execute(text('PRAGMA foreign_key_check')).all())

    def test_initial_state_is_feasible_except_explicit_dependency_repair(self):
        cases, state, backend = module('cases'), module('state'), module('backend')
        for case in cases.frozen_cases('all'):
            with state.isolated_state(case) as database, database.Session() as db:
                check = backend.check_plan(db, db.get(backend.Project, 1), [])
            if case['id'] == 'FUE05':
                self.assertEqual({'dependency_time'}, {v['code'] for v in check['violations']})
            else:
                self.assertTrue(check['valid'], (case['id'], check))

    def test_all_oracle_labels_pass_local_scorer_and_public_constraints(self):
        cases, scoring = module('cases'), module('scoring')
        for case in cases.frozen_cases('all'):
            with self.subTest(case=case['id']):
                output = cases.offline_oracle(case)
                result = scoring.score(case, output)
                self.assertTrue(result['semantic_success'], result)
                self.assertTrue(result['strict_success'], result)
                self.assertTrue(result['plan_feasible'])
                self.assertTrue(result['completed_entities_unchanged'])

    def test_expected_dates_and_hard_preservation_are_explicit(self):
        cases = module('cases')
        evaluation = {c['id']: c for c in cases.frozen_cases()}
        self.assertEqual(['assignee', 'hours', 'start_date', 'due_date'], evaluation['FUE02']['expected']['question_labels'])
        self.assertEqual(['due_date'], evaluation['FUE03']['expected']['question_labels'])
        self.assertEqual('2026-11-04', evaluation['FUE05']['expected']['tasks'][0]['offline_fixture']['start_date'])
        self.assertEqual('2026-11-09', evaluation['FUE06']['expected']['tasks'][1]['offline_fixture']['start_date'])
        for case in cases.frozen_cases('all'):
            for label in case['expected']['tasks']:
                for field in ('start_date', 'due_date'):
                    self.assertEqual({'one_of': [label['offline_fixture'][field]]}, label['facts'][field])
                self.assertEqual(label['stage_explicit'], 'stage_index' in label['facts'])
                if label['offline_fixture']['existing_id'] is not None:
                    self.assertTrue({'title', 'description', 'acceptance', 'artifact_url', 'blocker'} <= set(label['facts']))

    def test_completed_task_protection_covers_every_entity_field(self):
        cases, scoring = module('cases'), module('scoring')
        case = cases.frozen_cases()[0]
        for field, value in (('title', '改名'), ('description', '被改'), ('artifact_url', '/changed'),
                             ('blocker', '被改'), ('progress', 99), ('remaining_hours', 1)):
            with self.subTest(field=field):
                output = cases.offline_oracle(case)
                changed = deepcopy(case['state']['tasks'][0])
                changed[field] = value
                output['tasks'].append(changed)
                result = scoring.score(case, output)
                self.assertFalse(result['semantic_success'])
                self.assertFalse(result['completed_entities_unchanged'])

    def test_no_expectation_or_oracle_fields_enter_serialized_input(self):
        cases, state, runner = module('cases'), module('state'), module('runner')
        forbidden = {'expected', 'aliases', 'facts', 'question_labels', 'offline_fixture', 'stage_explicit',
                     'acceptance_groups', 'acceptance_reject_patterns', 'acceptance_scope_exclusions'}
        def keys(value):
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(child) for child in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(child) for child in value))
            return set()
        for case in cases.frozen_cases('all'):
            with state.isolated_state(case) as database:
                context, messages = state.inputs(case, database)
            visible = runner.common_input(case, context, messages)
            self.assertFalse(forbidden & keys(visible))
            self.assertEqual({'mode', 'project_context', 'messages'}, set(visible))

    def test_candidate_documents_budget_and_synthetic_oracle_limits(self):
        limits = {'PROTOCOL.md': '不是真实模型证据', 'README.md': '不能当模型质量结果'}
        for name in ('PROTOCOL.md', 'README.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn('CANDIDATE', text)
            self.assertIn('144', text)
            self.assertIn('180', text)
            self.assertIn('oracle', text)
            self.assertIn(limits[name], text)


if __name__ == '__main__':
    unittest.main()
