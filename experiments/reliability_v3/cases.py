"""3 开发 + 6 独立评价样例；标签及测试 oracle 不得进入模型输入。"""
from copy import deepcopy
import hashlib
import json

VERSION = '2026-10-20-reliability-v3.1'
STAMP = '2026-10-20T09:00:00+08:00'


def draft(title, requirement_id, assignee_id, hours, start, due, *, key='new_work',
          existing_id=None, dependencies=(), status='todo', progress=0, stage_index=1, acceptance=''):
    return dict(key=f'task_{existing_id}' if existing_id else key, existing_id=existing_id,
        title=title, description='', requirement_id=requirement_id, acceptance=acceptance,
        assignee_id=assignee_id, estimated_hours=hours, remaining_hours=0 if status == 'done' else hours,
        start_date=start, due_date=due, dependencies=list(dependencies), status=status,
        progress=100 if status == 'done' else progress, stage_index=stage_index, artifact_url='', blocker='')


def base_state():
    return dict(
        course=dict(id=1, teacher_id=2, title='实验室服务软件实践', description='构建设备借用服务',
            acceptance_criteria='完成阶段评审与运行演示', required_features=['设备目录', '预约申请'],
            optional_features=['归还提醒'], references=[], status='published', version=1, history=[], stages=[
                dict(name='需求确认', deadline='2026-10-16', deliverables=['需求清单']),
                dict(name='实现联调', deadline='2026-11-04', deliverables=['功能联调']),
                dict(name='验收交付', deadline='2026-11-18', deliverables=['演示材料'])]),
        project=dict(id=1, course_id=1, name='实验室设备借用平台', description='全新固定评价项目',
            status='active', revision=3, analyzed_message_id=0, created_at='2026-10-12T09:00:00+08:00'),
        users=[dict(id=2, username='tangteacher', name='唐老师', identity='teacher'),
               dict(id=21, username='zhouchen', name='周辰', identity='student'),
               dict(id=22, username='linyue', name='林悦', identity='student'),
               dict(id=23, username='sunhao', name='孙浩', identity='student')],
        members=[dict(user_id=21, role='leader', skills=['服务端', '脚本'], weekly_hours=16),
                 dict(user_id=22, role='member', skills=['测试', '联调'], weekly_hours=16),
                 dict(user_id=23, role='member', skills=['前端', '演示'], weekly_hours=12)],
        requirements=[dict(id=421, title='设备目录', description='查询可借设备', acceptance='展示设备名称与借用状态',
                           course_feature='设备目录', priority='must', status='confirmed'),
                      dict(id=422, title='预约申请', description='提交预约申请', acceptance='可提交申请且重复申请被拒绝',
                           course_feature='预约申请', priority='must', status='confirmed'),
                      dict(id=423, title='借用核对', description='核对借用记录', acceptance='借用人和设备记录一致',
                           course_feature='', priority='should', status='confirmed'),
                      dict(id=424, title='归还提醒', description='提示逾期归还', acceptance='逾期提醒且已归还不提醒',
                           course_feature='', priority='should', status='confirmed')],
        tasks=[draft('设备目录发布', 421, 23, 5, '2026-10-15', '2026-10-16', existing_id=631,
                     stage_index=0, status='done', acceptance='展示设备名称与借用状态'),
               dict(draft('预约申请处理', 422, 21, 6, '2026-10-20', '2026-10-21', existing_id=632,
                     status='doing', progress=25, dependencies=['task_631'],
                     acceptance='可提交申请且重复申请被拒绝'), remaining_hours=4),
               draft('借用记录核对', 423, 22, 4, '2026-10-22', '2026-10-23', existing_id=633,
                     dependencies=['task_632', 'task_631'], acceptance='借用人和设备记录一致')],
        cards=[])


def label(task, aliases, acceptance_groups=(), *, preserve=False, stage_explicit=False,
          acceptance_reject_patterns=(), acceptance_scope_exclusions=()):
    fields = ['existing_id', 'requirement_id', 'assignee_id', 'estimated_hours', 'remaining_hours',
              'start_date', 'due_date', 'dependencies', 'status', 'progress']
    if stage_explicit:
        fields.append('stage_index')
    if preserve:
        fields += ['title', 'description', 'acceptance', 'artifact_url', 'blocker']
    # 日期允许集在首次冻结前显式枚举；不能看模型结果后扩大。
    facts = {k: {'one_of': [task[k]]} if k in ('start_date', 'due_date') else task[k] for k in fields}
    return dict(aliases=list(aliases), facts=facts, acceptance_groups=list(acceptance_groups),
                acceptance_reject_patterns=list(acceptance_reject_patterns),
                acceptance_scope_exclusions=list(acceptance_scope_exclusions),
                stage_explicit=stage_explicit, offline_fixture=deepcopy(task))


def make_case(case_id, split, category, contents, *, tasks=(), outcome='plan', question_labels=(),
              state=None, mode='plan', speakers=None):
    if isinstance(contents, str):
        contents = [contents]
    speakers = speakers or [21] * len(contents)
    return dict(id=case_id, split=split, category=category, mode=mode, state=state or base_state(),
        messages=[dict(id=821 + i, user_id=speakers[i], kind='human', content=text,
            created_at=f'2026-10-20T09:{i:02d}:00+08:00', client_id=f'{case_id}-{i}',
            related_type=None, related_id=None, supersedes_card_ids=[]) for i, text in enumerate(contents)],
        expected=dict(outcome=outcome, tasks=list(tasks), question_labels=list(question_labels), supersedes=[]))


def frozen_cases(split='eval'):
    cases = []
    task = draft('设备借用操作视频', 421, 23, 3, '2026-10-22', '2026-10-23', key='new_video',
        dependencies=['task_631'], acceptance='演示查找设备并提交预约')
    cases.append(make_case('V3E01', 'eval', '完整新增并依赖已完成项',
        '请新增设备借用操作视频，关联设备目录需求，孙浩负责，预计与剩余均3小时，10月22日开始、23日交付。'
        '前置是已完成的设备目录发布，保持这个已完成任务原样。视频验收须演示查找设备并提交预约，'
        '新视频尚未开始，进度为0。', tasks=[label(task, ['设备借用操作视频', '设备借用演示视频', '借用操作视频'],
            [['查找', '查询', '搜索'], ['设备'], ['提交', '发起'], ['预约']],
            acceptance_reject_patterns=[r'(?:不得|不能|禁止|不允许|无需|不需要|不再|不会|不|未能|未)\s*(?:直接|进行|执行|演示|正常|完成)?\s*(?:查找|查询|搜索|提交|发起)'])]))
    cases.append(make_case('V3E02', 'eval', '只有验收条件',
        '归还提醒需求要加一个短信验证任务。验收条件确定为：逾期设备只发送一次提醒，已归还设备不发送提醒。请安排这个新任务。',
        outcome='clarify', question_labels=['assignee', 'hours', 'start_date', 'due_date']))
    cases.append(make_case('V3E03', 'eval', '仅缺截止日期',
        ['孙浩负责归还提醒页面核对，关联归还提醒需求，预计和剩余都是3小时，10月26日开始，无前置任务，尚未开始、进度0。',
         '验收是逾期标记可见、已归还状态不显示提醒；截止日期还没有定下来，请只问尚缺的信息。'],
        outcome='clarify', question_labels=['due_date']))
    task = draft('设备库存盘点核对', 421, 22, 2, '2026-10-20', '2026-10-21', key='new_inventory',
        dependencies=['task_631'], acceptance='盘点数量与设备目录一致')
    cases.append(make_case('V3E04', 'eval', '本人自荐中文工时和相对日期',
        ['设备目录需求下需要新增设备库存盘点核对，依赖已完成的设备目录发布。验收是盘点数量与设备目录一致，放在实现联调阶段。',
         '这项我来做。预计两小时，剩余也两小时，今天开始，明天交付；现在还未开始，进度为零。'],
        speakers=[21, 22], tasks=[label(task, ['设备库存盘点核对', '设备盘点核对', '库存盘点核对'],
            [['盘点'], ['数量'], ['目录'], ['一致']], stage_explicit=True,
            acceptance_reject_patterns=[r'不一致|未一致|无需[^，,。；;]{0,6}一致|不得[^，,。；;]{0,6}一致'],
            acceptance_scope_exclusions=[r'(?:^|(?<=[，,。；;]))\s*如不一致则验收不通过'])]))
    state = base_state()
    state['tasks'][2].update(start_date='2026-10-20', due_date='2026-10-21')
    fixed = dict(state['tasks'][2], start_date='2026-10-22', due_date='2026-10-23')
    cases.append(make_case('V3E05', 'eval', '既有依赖日期修复',
        '借用记录核对排早了，应在预约申请处理截止后的第一个工作日开始，仍占两个工作日。'
        '保持原林悦负责人、预计和剩余4小时、验收、依赖、状态、进度、阶段及其他原字段；'
        '预约申请处理日期保持原样，已完成的设备目录发布也原样保留。请修复排期。', state=state, mode='adjust',
        tasks=[label(fixed, ['借用记录核对', '借用核对'], preserve=True, stage_explicit=True)]))
    state = base_state()
    delayed = dict(state['tasks'][1], due_date='2026-10-23')
    propagated = dict(state['tasks'][2], start_date='2026-10-26', due_date='2026-10-27')
    cases.append(make_case('V3E06', 'eval', '延期传播及明确原字段保护',
        ['预约申请处理确认延到10月23日周五才完成，开始日期、负责人、预计与剩余工时、验收、依赖、状态、进度、阶段和其他原字段全部保持。',
         '请一并顺延借用记录核对：它仍占两个工作日，在前置任务截止后的第一个工作日开工，所有其他原字段不变。设备目录发布已经完成，保持原样。'],
        state=state, mode='adjust', tasks=[
            label(delayed, ['预约申请处理', '预约申请'], preserve=True, stage_explicit=True),
            label(propagated, ['借用记录核对', '借用核对'], preserve=True, stage_explicit=True)]))
    task = draft('设备借用标签打印', 421, 21, 1, '2026-10-28', '2026-10-29', key='new_labels',
        acceptance='打印标签包含设备编号和借用人')
    cases.append(make_case('V3D01', 'dev', '开发完整新增',
        '新增设备借用标签打印，关联设备目录需求，周辰负责，预计和剩余1小时，10月28日开始、29日交付。'
        '无前置，尚未开始、进度0，验收为打印标签包含设备编号和借用人。',
        tasks=[label(task, ['设备借用标签打印', '借用标签打印'], [['设备'], ['编号'], ['借用人']])]))
    cases.append(make_case('V3D02', 'dev', '开发仅缺工时',
        '孙浩负责预约负载测试，关联预约申请需求，10月27日开始、28日交付，无前置，尚未开始、进度0，'
        '验收为十个并发申请无重复记录；预计和剩余工时尚未估算，请只追问这个缺项。',
        outcome='clarify', question_labels=['hours']))
    state = base_state()
    task = dict(state['tasks'][1], assignee_id=23)
    cases.append(make_case('V3D03', 'dev', '开发既有负责人更正',
        '预约申请处理的负责人改为孙浩，其他全部原字段保持，包括验收、工时、日期、依赖、阶段、状态和进度。',
        mode='adjust', state=state, tasks=[label(task, ['预约申请处理', '预约申请'], preserve=True, stage_explicit=True)]))
    if split not in ('dev', 'eval', 'all'):
        raise ValueError('split 必须为 dev、eval 或 all')
    return deepcopy([c for c in cases if split == 'all' or c['split'] == split])


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def offline_oracle(case):
    """只供单元测试构造数据；runner 不使用此函数，不能作为模型结果。"""
    questions = {'assignee': '这项任务由谁负责？', 'hours': '预计与剩余工时分别多少小时？',
                 'start_date': '哪一天开始？', 'due_date': '截止日期是哪一天？'}
    return dict(kind=case['mode'], title='离线测试专用草案', summary='离线 fixture，不是模型输出',
        tasks=[deepcopy(t['offline_fixture']) for t in case['expected']['tasks']],
        questions=[questions[key] for key in case['expected']['question_labels']],
        source_message_ids=[m['id'] for m in case['messages']], supersedes_card_ids=[])
