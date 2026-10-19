"""开发集与冻结评价集；标签仅用于本地评分，禁止加入模型输入。"""
from copy import deepcopy
import hashlib
import json

VERSION = '2026-10-16-v2'
STAMP = '2026-10-16T09:00:00+08:00'


def draft(title, req, owner, hours, start, due, *, existing_id=None,
          dependencies=(), status='todo', stage_index=1, acceptance='按验收要求完成'):
    return dict(key=f'task_{existing_id}' if existing_id else 'new_work',
                existing_id=existing_id, title=title, description='', requirement_id=req,
                acceptance=acceptance, assignee_id=owner, estimated_hours=hours,
                remaining_hours=0 if status == 'done' else hours,
                dependencies=list(dependencies), start_date=start, due_date=due,
                status=status, progress=100 if status == 'done' else 0,
                artifact_url='', blocker='', stage_index=stage_index)


def base_state():
    return dict(course=dict(id=1, teacher_id=1, title='软件协作课程', description='完成可运行团队项目',
        acceptance_criteria='按三个阶段提交成果', required_features=['账号登录'], optional_features=['结果导出'],
        references=[], status='published', version=1, history=[], stages=[
            dict(name='需求', deadline='2026-10-18', deliverables=['需求清单']),
            dict(name='实现', deadline='2026-11-06', deliverables=['功能演示']),
            dict(name='交付', deadline='2026-11-13', deliverables=['项目材料'])]),
        project=dict(id=1, course_id=1, name='课程协作平台', description='固定评价状态', status='active',
                     revision=1, analyzed_message_id=0, created_at=STAMP),
        users=[dict(id=1, username='teacher', name='陈老师', identity='teacher'),
               dict(id=11, username='zhangming', name='张明', identity='student'),
               dict(id=12, username='lihua', name='李华', identity='student'),
               dict(id=13, username='wangfang', name='王芳', identity='student')],
        members=[dict(user_id=11, role='leader', skills=['后端', '文档'], weekly_hours=8),
                 dict(user_id=12, role='member', skills=['测试', '文档'], weekly_hours=8),
                 dict(user_id=13, role='member', skills=['前端', '文档'], weekly_hours=6)],
        requirements=[dict(id=101, title='账号登录', description='实现账号认证', acceptance='正确凭据可登录，错误凭据被拒绝',
                           course_feature='账号登录', priority='must', status='confirmed'),
                      dict(id=102, title='结果导出', description='导出项目结果', acceptance='能下载导出文件',
                           course_feature='', priority='should', status='confirmed'),
                      dict(id=103, title='操作文档', description='编写使用说明', acceptance='包含部署步骤和操作截图',
                           course_feature='', priority='should', status='confirmed')],
        tasks=[draft('登录接口', 101, 11, 6, '2026-10-19', '2026-10-20', existing_id=201,
                     acceptance='正确凭据可登录，错误凭据被拒绝'),
               draft('登录测试', 101, 12, 4, '2026-10-21', '2026-10-22', existing_id=202,
                     dependencies=['task_201'], acceptance='正确和错误凭据用例均通过'),
               draft('导出功能', 102, 13, 4, '2026-10-19', '2026-10-20', existing_id=203,
                     status='done', acceptance='能下载导出文件')], cards=[])


def label_task(task, aliases, acceptance_groups=(), *, preserve_acceptance=False):
    fields = ('existing_id', 'requirement_id', 'assignee_id', 'estimated_hours', 'remaining_hours',
              'start_date', 'due_date', 'dependencies', 'status', 'progress', 'stage_index')
    facts = {k: task[k] for k in fields}
    if preserve_acceptance:
        facts['acceptance'] = task['acceptance']
    return dict(aliases=aliases, facts=facts,
                acceptance_groups=list(acceptance_groups))


def make_case(ident, split, message, *, state=None, expected_tasks=(), outcome='plan',
              question_groups=(), summary_groups=(), supersedes=(), mode='plan', category=''):
    return dict(id=ident, split=split, category=category, mode=mode, state=state or base_state(),
        messages=[dict(id=401, user_id=11, kind='human', content=message, created_at=STAMP,
                       client_id='fixed-401', related_type=None, related_id=None,
                       supersedes_card_ids=list(supersedes))],
        expected=dict(outcome=outcome, tasks=list(expected_tasks), question_groups=list(question_groups),
                      summary_groups=list(summary_groups), supersedes=list(supersedes)))


def frozen_cases(split='eval'):
    cases = []
    doc = draft('操作文档', 103, 11, 2, '2026-10-23', '2026-10-23',
                dependencies=['task_202'], acceptance='包含部署步骤和操作截图')
    cases.append(make_case('E01', 'eval', '新增操作文档任务，张明负责，预计和剩余均为2小时，'
        '登录测试完成后于10月23日开始并当天交付，关联操作文档需求，验收包括部署步骤和操作截图。请形成计划。',
        expected_tasks=[label_task(doc, ['操作文档', '使用文档', '操作说明'], [['部署'], ['截图']])], category='明确新增任务'))
    cases.append(make_case('E02', 'eval', '我们还需要给结果导出加一个校验任务，验收是导出文件内容与页面一致。请安排。',
        outcome='clarify', question_groups=[['谁', '负责人', '哪位'], ['工时', '小时'], ['开始'], ['截止', '交付', '完成日期']],
        category='缺负责人和工时和日期'))
    s = base_state()
    s['cards'] = [dict(id=301, kind='plan', title='操作文档草案', summary='文档安排待核对', questions=[],
        source_message_ids=[400], supersedes_card_ids=[], tasks=[doc], checks={}, status='pending',
        base_revision=1, feedback=[], creator_id=None, created_at='2026-10-16T08:30:00+08:00', published_plan_id=None)]
    revised = dict(doc, assignee_id=12)
    cases.append(make_case('E03', 'eval', '上一张操作文档草案负责人写错了，改成李华，其余工时、日期、验收和依赖都照旧，不要重复追问。',
        state=s, expected_tasks=[label_task(revised, ['操作文档', '使用文档', '操作说明'], preserve_acceptance=True)],
        supersedes=[301], mode='adjust', category='更正负责人及旧卡关联'))
    s = base_state()
    s['tasks'][1].update(start_date='2026-10-20', due_date='2026-10-21')
    repair = dict(s['tasks'][1], start_date='2026-10-21', due_date='2026-10-22')
    cases.append(make_case('E04', 'eval', '检查登录接口与登录测试的依赖日期冲突。保持测试的李华负责人、4小时和两个工作日工期，'
        '测试在接口截止后的第一个工作日开始，接口日期保持不变。请给出修正计划。', state=s,
        expected_tasks=[label_task(repair, ['登录测试', '认证测试'])], mode='adjust', category='依赖时间冲突'))
    extra = draft('操作文档', 103, 11, 4, '2026-10-26', '2026-10-27', acceptance='包含部署步骤和操作截图')
    cases.append(make_case('E05', 'eval', '本周想再给张明加4小时操作文档，原希望10月22日至23日做。若超过他的周容量，'
        '允许挪到下一周的10月26日至27日，最晚27日完成；保留登录接口安排，不换负责人。'
        '关联操作文档需求，验收包含部署步骤和操作截图。请检查容量后安排。',
        expected_tasks=[label_task(extra, ['操作文档', '使用文档', '操作说明'], [['部署'], ['截图']])], category='容量需重排'))
    s = base_state()
    s['requirements'][2].update(priority='must', course_feature='操作文档')
    s['course']['required_features'].append('操作文档')
    extra = draft('操作文档', 103, 13, 2, '2026-10-22', '2026-10-23', acceptance='包含部署步骤和操作截图')
    cases.append(make_case('E06', 'eval', '请检查所有必做需求，给遗漏的操作文档补齐计划：王芳负责2小时，'
        '10月22日开始、23日交付，验收包含部署步骤和操作截图。已有登录与导出任务保持不变。', state=s,
        expected_tasks=[label_task(extra, ['操作文档', '使用文档', '操作说明'], [['部署'], ['截图']])], category='必做需求遗漏'))
    s = base_state()
    s['tasks'][0]['dependencies'] = ['task_202']
    repair = dict(s['tasks'][0], dependencies=[])
    cases.append(make_case('E07', 'eval', '登录接口与登录测试出现循环依赖。业务顺序应是先接口、再测试，'
        '删除接口对测试的依赖，保留测试对接口的依赖。负责人、工时与日期均不变，请形成修正。', state=s,
        expected_tasks=[label_task(repair, ['登录接口', '认证接口'])], mode='adjust', category='循环依赖'))
    s = base_state()
    s['tasks'] = [dict(s['tasks'][0], estimated_hours=20, remaining_hours=20)]
    s['members'][0]['weekly_hours'] = 2
    s['course']['stages'][1]['deadline'] = '2026-10-20'
    cases.append(make_case('E08', 'eval', '登录接口还有20小时，只能张明做，10月19日开工、20日必须交付。'
        '不能减少工时、更换负责人或改变课程期限。请判断容量和期限是否允许，若不可行请说明并保留原计划。',
        state=s, outcome='infeasible', summary_groups=[['不可行', '无法', '不能满足', '超过'], ['容量', '工时', '小时'], ['截止', '期限', '20日', '10-20']],
        category='不可行容量和期限'))
    extra = draft('导出回归测试', 102, 11, 2, '2026-10-23', '2026-10-23', dependencies=['task_203'],
                  acceptance='导出文件与页面一致')
    cases.append(make_case('E09', 'eval', '导出功能已完成，不能改动它。现在张明另做导出回归测试，2小时，'
        '10月23日开始并当天交付，依赖已完成的导出功能，关联结果导出需求，验收是导出文件与页面一致。请安排。',
        expected_tasks=[label_task(extra, ['导出回归', '导出测试'], [['导出'], ['一致']])], category='已完成任务保护'))
    s = base_state()
    delayed = dict(s['tasks'][0], due_date='2026-10-23')
    downstream = dict(s['tasks'][1], start_date='2026-10-26', due_date='2026-10-27')
    cases.append(make_case('E10', 'eval', '登录接口确认要到10月23日周五才完成，开始日期和工时不变；'
        '测试仍由李华负责，4小时、占两个工作日，验收不变。请把后续依赖受到的影响一起调整。',
        expected_tasks=[label_task(delayed, ['登录接口', '认证接口'], preserve_acceptance=True),
                        label_task(downstream, ['登录测试', '认证测试'], preserve_acceptance=True)],
        mode='adjust', category='隐含延期传播'))
    extra = draft('导出操作说明', 103, 13, 2, '2026-10-28', '2026-10-29', acceptance='包含导出操作截图')
    cases.append(make_case('D01', 'dev', '王芳负责导出操作说明，关联操作文档需求，预计和剩余2小时，'
        '10月28日开始、29日交付，无前置任务，验收包含导出操作截图。请给计划。',
        expected_tasks=[label_task(extra, ['导出操作说明', '导出文档'], [['导出'], ['截图']])], category='开发新增'))
    cases.append(make_case('D02', 'dev', '李华负责结果导出的异常测试，10月28日开始、29日交，'
        '验收是错误输入得到明确提示，但工时还没估计。', outcome='clarify', question_groups=[['小时', '工时']], category='开发澄清'))
    s = base_state()
    s['tasks'][1].update(start_date='2026-10-19', due_date='2026-10-20')
    repair = dict(s['tasks'][1], start_date='2026-10-21', due_date='2026-10-22')
    cases.append(make_case('D03', 'dev', '登录测试排得太早了，请改在登录接口截止后的第一个工作日开始，'
        '保持两个工作日、4小时与李华负责人，其余不变。', state=s,
        expected_tasks=[label_task(repair, ['登录测试', '认证测试'])], mode='adjust', category='开发依赖修复'))
    if split not in ('dev', 'eval', 'all'):
        raise ValueError('split 必须为 dev、eval 或 all')
    return deepcopy([c for c in cases if split == 'all' or c['split'] == split])


def fingerprint(cases):
    raw = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
