import json
import pytest
from experiments.cases import frozen_cases
from experiments.runner import make_jobs, request_messages
from experiments.runner import freeze_value, verify_freeze
from experiments.transport import GuardStopped
from experiments.state import inputs, isolated_state

GROUPS = ['chat_only', 'context_only', 'agent']


def test_seed_order_and_full_manifest_keep_all_samples():
    cases = frozen_cases()
    jobs = make_jobs(cases, GROUPS, repetitions=2, seed=17)
    assert len(jobs) == 60
    assert jobs == make_jobs(cases, GROUPS, repetitions=2, seed=17)
    assert {j['case_id'] for j in jobs} == {c['id'] for c in cases}
    assert {j['status'] for j in jobs} == {'not_run'}


def test_same_context_and_protocol_no_label_leak_chat_only_directory_only():
    case = frozen_cases()[2]
    with isolated_state(case) as db:
        context, messages, directory = inputs(case, db)
    chat = request_messages(case, 'chat_only', context, messages, directory)
    baseline = request_messages(case, 'context_only', context, messages, directory)
    agent = request_messages(case, 'agent', context, messages, directory)
    assert len(chat) == 2
    assert chat[0] == baseline[0] == agent[0]
    assert baseline == agent
    assert json.loads(chat[1]['content'])['project_context'] == {'name_id_directory': directory}
    assert json.loads(agent[1]['content'])['project_context'] == context
    assert all('expected' not in m['content'] and 'E03' not in m['content'] for m in agent)


def test_changed_protocol_freeze_is_rejected(tmp_path):
    value = freeze_value()
    path = tmp_path / 'freeze.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    assert verify_freeze(path) == value
    value['protocol_sha256'] = 'tampered'
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(GuardStopped):
        verify_freeze(path)
