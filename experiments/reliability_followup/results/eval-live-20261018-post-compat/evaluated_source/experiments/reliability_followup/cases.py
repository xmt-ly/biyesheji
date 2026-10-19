"""交付兼容修订后的独立候选题目；3 开发 + 6 评价，尚未真实调用。"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json

VERSION = '2026-10-18-reliability-followup-candidate-1'
STAMP = '2026-11-02T10:00:00+08:00'


def draft(title, requirement_id, assignee_id, hours, start, due, *, key='new_work',
          existing_id=None, dependencies=(), status='todo', progress=0, stage_index=1,
          acceptance='', description='', artifact_url='', blocker=''):
    return dict(key=f'task_{existing_id}' if existing_id else key, existing_id=existing_id,
        title=title, description=description, requirement_id=requirement_id, acceptance=acceptance,
        assignee_id=assignee_id, estimated_hours=hours, remaining_hours=0 if status == 'done' else hours,
        start_date=start, due_date=due, dependencies=list(dependencies), status=status,
        progress=100 if status == 'done' else progress, stage_index=stage_index,
        artifact_url=artifact_url, blocker=blocker)


def base_state():
    # state.py 固定 project_id=1、creator_id=21；21 仍是本轮全新组长。
    return dict(
        course=dict(id=1, teacher_id=12, title='校园公共服务课程实践', description='建设共享场地预约服务',
            acceptance_criteria='完成业务核验、联调与交付展示', required_features=['场地目录', '预约受理'],
            optional_features=['使用提醒'], references=[], status='published', version=1, history=[], stages=[
                dict(name='调研定稿', deadline='2026-10-30', deliverables=['场地开放规则']),
                dict(name='功能联调', deadline='2026-11-20', deliverables=['预约流程联调']),
                dict(name='交付展示', deadline='2026-12-04', deliverables=['使用手册与演示'])]),
        project=dict(id=1, course_id=1, name='校园共享场地预约', description='交付修订后另设的合成评价项目',
            status='active', revision=4, analyzed_message_id=0, created_at='2026-10-26T10:00:00+08:00'),
        users=[dict(id=12, username='yanteacher', name='严老师', identity='teacher'),
               dict(id=21, username='hecheng_fu', name='何澄', identity='student'),
               dict(id=72, username='guning_fu', name='顾宁', identity='student'),
               dict(id=73, username='luolin_fu', name='罗霖', identity='student')],
        members=[dict(user_id=21, role='leader', skills=['服务端', '预约规则'], weekly_hours=15),
                 dict(user_id=72, role='member', skills=['测试', '开放规则核验'], weekly_hours=13),
                 dict(user_id=73, role='member', skills=['界面', '操作说明'], weekly_hours=11)],
        requirements=[dict(id=1701, title='场地目录', description='查找校内可预约场地',
                           acceptance='列出场地名称、位置和开放时段', course_feature='场地目录', priority='must', status='confirmed'),
                      dict(id=1702, title='预约受理', description='按场地和时段受理预约',
                           acceptance='空闲时段可预约，冲突时段被拒绝', course_feature='预约受理', priority='must', status='confirmed'),
                      dict(id=1703, title='预约记录核验', description='核验预约归属和时段记录',
                           acceptance='预约人、场地和时段记录相符', course_feature='', priority='should', status='confirmed'),
                      dict(id=1704, title='使用提醒', description='提示预约者按时使用场地',
                           acceptance='临近使用时间提醒，已取消预约不提醒', course_feature='', priority='should', status='confirmed')],
        tasks=[draft('场地目录整理', 1701, 73, 4, '2026-10-29', '2026-10-30', existing_id=2701,
                     stage_index=0, status='done', acceptance='列出场地名称、位置和开放时段',
                     description='整理体育馆和活动室的开放信息', artifact_url='/artifacts/venue-catalog-v1'),
               dict(draft('场地申请受理', 1702, 21, 7, '2026-11-02', '2026-11-03', existing_id=2702,
                     status='doing', progress=30, dependencies=['task_2701'],
                     acceptance='空闲时段可预约，冲突时段被拒绝', description='实现校内场地时段申请处理'), remaining_hours=5),
               draft('预约记录复核', 1703, 72, 3, '2026-11-04', '2026-11-05', existing_id=2703,
                     dependencies=['task_2702', 'task_2701'], acceptance='预约人、场地和时段记录相符',
                     description='对照申请单核验预约记录')], cards=[])


def label(task, aliases, acceptance_groups=(), *, preserve=False, stage_explicit=False,
          acceptance_reject_patterns=(), acceptance_scope_exclusions=()):
    fields = ['existing_id', 'requirement_id', 'assignee_id', 'estimated_hours', 'remaining_hours',
              'start_date', 'due_date', 'dependencies', 'status', 'progress']
    if stage_explicit:
        fields.append('stage_index')
    if preserve:
        fields += ['title', 'description', 'acceptance', 'artifact_url', 'blocker']
    facts = {key: {'one_of': [task[key]]} if key in ('start_date', 'due_date') else task[key] for key in fields}
    return dict(aliases=list(aliases), facts=facts, acceptance_groups=list(acceptance_groups),
                acceptance_reject_patterns=list(acceptance_reject_patterns),
                acceptance_scope_exclusions=list(acceptance_scope_exclusions),
                stage_explicit=stage_explicit, offline_fixture=deepcopy(task))


def make_case(case_id, split, category, contents, *, tasks=(), outcome='plan', question_labels=(),
              state=None, mode='plan', speakers=None):
    if isinstance(contents, str):
        contents = [contents]
    speakers = speakers or [21] * len(contents)
    origin = datetime.fromisoformat(STAMP)
    return dict(id=case_id, split=split, category=category, mode=mode, state=state or base_state(),
        messages=[dict(id=3701 + index, user_id=speakers[index], kind='human', content=text,
            created_at=(origin + timedelta(minutes=index)).isoformat(), client_id=f'{case_id}-{index}',
            related_type=None, related_id=None, supersedes_card_ids=[]) for index, text in enumerate(contents)],
        expected=dict(outcome=outcome, tasks=list(tasks), question_labels=list(question_labels), supersedes=[]))


def frozen_cases(split='eval'):
    cases = []
    task = draft('场地预约使用说明', 1701, 73, 4, '2026-11-05', '2026-11-06', key='new_venue_guide',
        dependencies=['task_2701'], acceptance='演示查找场地并提交预约')
    cases.append(make_case('FUE01', 'eval', '完整新任务及完成前置保护',
        '我们给新生补一份场地预约使用说明，挂在场地目录需求下。罗霖负责，预计4小时，剩余也是4小时，'
        '11月5日动手，11月6日交付。以前置的场地目录整理为基础，它已经完成，原记录不要改。'
        '说明需要演示查找场地并提交预约；新任务尚未开始，进度0。',
        tasks=[label(task, ['场地预约使用说明', '场地预约操作说明', '预约使用说明'],
            [['查找', '查询', '搜索'], ['场地'], ['提交', '发起'], ['预约']],
            acceptance_reject_patterns=[r'(?:不得|不能|禁止|不允许|无需|不需要|不再|不会|不|未能|未)\s*(?:直接|进行|执行|演示|正常|完成)?\s*(?:查找|查询|搜索|提交|发起)'])]))
    cases.append(make_case('FUE02', 'eval', '新任务缺全部执行承诺',
        '使用提醒需求还要补一个取消预约提醒核验任务。验收先定下来：取消预约后不再提醒，正常预约在使用前只提醒一次。'
        '先把需要确认的执行安排列出来。', outcome='clarify',
        question_labels=['assignee', 'hours', 'start_date', 'due_date']))
    cases.append(make_case('FUE03', 'eval', '仅缺交付日期',
        ['使用提醒页面的文案核对由罗霖做，关联使用提醒需求。预计3小时，剩余3小时，11月9日开始，'
         '不依赖别的任务，还没开始、进度0。',
         '文案验收就是使用时间、场地名称显示正确，取消预约不显示提醒。交付哪天还没商量，请只追问这一个缺项。'],
        outcome='clarify', question_labels=['due_date']))
    task = draft('场地使用时段核验', 1701, 72, 3, '2026-11-02', '2026-11-03', key='new_opening_check',
        dependencies=['task_2701'], acceptance='开放时段与场地目录一致')
    cases.append(make_case('FUE04', 'eval', '本人承诺和相对日期的完整新任务',
        ['再增加场地使用时段核验，关联场地目录，依赖已完成的场地目录整理，放在功能联调阶段。'
         '开放时段与场地目录一致就算验收通过。',
         '这件事交给我吧，预计三小时，剩余也是三小时。今天开始，明天下班前交付。'
         '目前还没动手，进度为零。'], speakers=[21, 72],
        tasks=[label(task, ['场地使用时段核验', '场地开放时段核验', '使用时段核验'],
            [['开放时段', '使用时段'], ['场地目录', '目录'], ['一致', '相符']], stage_explicit=True,
            acceptance_reject_patterns=[r'不一致|未一致|不相符|未相符|无需[^，,。；;]{0,6}(?:一致|相符)|不得[^，,。；;]{0,6}(?:一致|相符)'],
            acceptance_scope_exclusions=[r'(?:^|(?<=[，,。；;]))\s*如不一致则验收不通过'])]))
    state = base_state()
    state['tasks'][2].update(start_date='2026-11-02', due_date='2026-11-03')
    fixed = dict(state['tasks'][2], start_date='2026-11-04', due_date='2026-11-05')
    cases.append(make_case('FUE05', 'eval', '修复既有前置日期冲突',
        '预约记录复核现在和前置的场地申请受理撞在同两天了。请把复核挪到受理截止后的第一个工作日开始，'
        '复核仍用两个工作日。顾宁、预计和剩余3小时、原验收、描述、依赖、阶段、状态、进度及其他字段都保留。'
        '场地申请受理的安排不动，已完成的场地目录整理也不要改。', state=state, mode='adjust',
        tasks=[label(fixed, ['预约记录复核', '预约记录核验复核'], preserve=True, stage_explicit=True)]))
    state = base_state()
    delayed = dict(state['tasks'][1], due_date='2026-11-06')
    propagated = dict(state['tasks'][2], start_date='2026-11-09', due_date='2026-11-10')
    cases.append(make_case('FUE06', 'eval', '延期传播与完成实体保护',
        ['场地申请受理要到11月6日周五才能交付。只改它的截止日期，原开始日期、负责人、预计和剩余工时、'
         '验收、描述、依赖、阶段、状态、进度及其他字段一律保留。',
         '后面的预约记录复核也一起顺延：从前置截止后的第一个工作日开始，仍排两个工作日，其他全部原字段不变。'
         '场地目录整理已经完成，整个任务保持原样。'], state=state, mode='adjust', tasks=[
            label(delayed, ['场地申请受理', '场地预约申请受理'], preserve=True, stage_explicit=True),
            label(propagated, ['预约记录复核', '预约记录核验复核'], preserve=True, stage_explicit=True)]))
    task = draft('场地位置二维码海报', 1701, 73, 2, '2026-11-12', '2026-11-13', key='new_venue_poster',
        acceptance='扫码显示场地名称和位置')
    cases.append(make_case('FUD01', 'dev', '开发完整新增',
        '请安排场地位置二维码海报，关联场地目录需求。罗霖负责，预计和剩余都是2小时，'
        '11月12日开始、13日交付，没有前置。尚未开始、进度0，验收是扫码显示场地名称和位置。',
        tasks=[label(task, ['场地位置二维码海报', '场地二维码海报'], [['扫码', '扫描'], ['场地'], ['名称'], ['位置']])]))
    cases.append(make_case('FUD02', 'dev', '开发只缺工时',
        '何澄来做预约冲突回归测试，关联预约受理需求，11月10日开始，11月11日交付，无前置，'
        '尚未开始、进度0。验收为同一场地同一时段的第二份申请被拒绝。工时还没估，预计和剩余都请先问清楚。',
        outcome='clarify', question_labels=['hours']))
    state = base_state()
    task = dict(state['tasks'][1], assignee_id=73)
    cases.append(make_case('FUD03', 'dev', '开发既有负责人调整',
        '场地申请受理由罗霖接手，负责人改成罗霖。其他原字段都不要动，包括描述、验收、工时、日期、'
        '依赖、阶段、状态和进度。', state=state, mode='adjust',
        tasks=[label(task, ['场地申请受理', '场地预约申请受理'], preserve=True, stage_explicit=True)]))
    if split not in ('dev', 'eval', 'all'):
        raise ValueError('split 必须为 dev、eval 或 all')
    return deepcopy([case for case in cases if split == 'all' or case['split'] == split])


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def offline_oracle(case):
    """仅生成标签测试用数据；runner 不调用，不能计入模型实验。"""
    questions = {'assignee': '这项任务由谁负责？', 'hours': '预计与剩余工时分别多少小时？',
                 'start_date': '哪一天开始？', 'due_date': '截止日期是哪一天？'}
    return dict(kind=case['mode'], title='离线合成标签校验', summary='合成 oracle，不是模型响应',
        tasks=[deepcopy(task['offline_fixture']) for task in case['expected']['tasks']],
        questions=[questions[key] for key in case['expected']['question_labels']],
        source_message_ids=[message['id'] for message in case['messages']], supersedes_card_ids=[])
