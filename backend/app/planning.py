"""所有草案都叠加到完整任务集合，发布前重复执行约束检查。"""
import math
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy import select
from .models import Course, Member, Requirement, Task
from .serializers import draft_json
from .permissions import require_public_course


def check_plan(db, project, drafts, require_coverage=True):
    existing=db.scalars(select(Task).where(Task.project_id==project.id)).all()
    original={f'task_{t.id}':draft_json(t) for t in existing}
    overlay={k:dict(v) for k,v in original.items()}
    members={m.user_id:m for m in db.scalars(select(Member).where(Member.project_id==project.id))}
    requirements={r.id:r for r in db.scalars(select(Requirement).where(Requirement.project_id==project.id))}
    course=require_public_course(db,project.course_id)
    violations=[]

    def fail(code,message,keys=None,**extra):
        violations.append(dict(code=code,message=message,task_keys=keys or [],**extra))

    seen=set()
    for d in drafts:
        d=dict(d)
        key=d['key']
        if key in seen:
            fail('duplicate_key','草案任务 key 重复',[key])
        seen.add(key)
        eid=d.get('existing_id')
        if eid is not None:
            if f'task_{eid}' not in original or key!=f'task_{eid}':
                fail('invalid_task','现有任务不属于当前项目，或 key 与 existing_id 不匹配',[key])
                continue
            if original[key]['status']=='done' and d!=original[key]:
                fail('completed_task','规划草案不能修改已完成任务',[key])
        elif key in original or key.startswith('task_'):
            fail('reserved_key','新任务 key 不能以 task_ 开头，请使用 new_ 开头的稳定名称',[key])
            continue
        overlay[key]=d

    ranges={}
    weekly=defaultdict(float)
    covered=set()
    for key,t in overlay.items():
        req=requirements.get(t['requirement_id'])
        if not req or req.status!='confirmed':
            fail('invalid_requirement','任务必须关联当前项目已确认需求',[key])
        else:
            covered.add(req.id)
        if t['assignee_id'] not in members:
            fail('invalid_assignee','负责人必须是当前项目成员',[key])
        if not t['acceptance'].strip():
            fail('missing_acceptance','任务缺少验收条件',[key])
        for field in ('estimated_hours','remaining_hours'):
            if not math.isfinite(t[field]) or t[field]<0:
                fail('invalid_hours','工时必须是有限的非负数',[key],field=field)
        try:
            start=date.fromisoformat(t['start_date'])
            end=date.fromisoformat(t['due_date'])
        except (ValueError,TypeError):
            fail('invalid_date','任务日期无效',[key])
            continue
        if start>end:
            fail('date_order','开始日期不能晚于截止日期',[key])
            continue
        if (end-start).days>3660:
            fail('date_range','单项任务日期跨度不能超过 3660 天',[key])
            continue
        ranges[key]=(start,end)
        stage=t.get('stage_index',2)
        if stage not in range(3) or len(course.stages)!=3:
            fail('invalid_stage','课程或任务阶段无效',[key])
        elif end>date.fromisoformat(course.stages[stage]['deadline']):
            fail('stage_deadline','任务超过所属必需阶段的截止日期',[key],stage_index=stage,deadline=course.stages[stage]['deadline'])
        if t['status']=='done':
            continue
        days=[]
        for ordinal in range(start.toordinal(),end.toordinal()+1):
            cursor=date.fromordinal(ordinal)
            if cursor.weekday()<5:
                days.append(cursor)
        if not days:
            days=[start]  # 纯周末任务仍计入该周容量，不忽略工时
        for day in days:
            week=(day-timedelta(days=day.weekday())).isoformat()
            weekly[(t['assignee_id'],week)]+=t['remaining_hours']/len(days)

    if require_coverage:
        for req in requirements.values():
            if req.status=='confirmed' and req.priority=='must' and req.id not in covered:
                fail('requirement_coverage','已确认必做需求没有对应任务',requirement_id=req.id)
        for feature in course.required_features:
            linked=[r for r in requirements.values() if r.status=='confirmed' and (r.course_feature==feature or r.title==feature)]
            if not linked or not any(r.id in covered for r in linked):
                fail('course_feature_coverage','课程必做功能没有已确认需求与任务的结构关联',course_feature=feature)

    # 显式栈替代 Python 递归，已有长链不受调用栈深度限制。
    colors={}
    for root in overlay:
        if colors.get(root):
            continue
        colors[root]=1
        active=[root]
        positions={root:0}
        stack=[(root,iter(overlay[root].get('dependencies',[])))]
        while stack:
            key,dependencies=stack[-1]
            dep=next(dependencies,None)
            if dep is None:
                colors[key]=2
                stack.pop()
                positions.pop(key)
                active.pop()
                continue
            if dep not in overlay:
                fail('invalid_dependency','依赖任务不存在或不属于当前项目',[key,dep])
                continue
            if key in ranges and dep in ranges and overlay[dep]['status']!='done' and ranges[dep][1]>=ranges[key][0]:
                fail('dependency_time','后续任务应在前置任务截止日之后开始',[dep,key])
            if colors.get(dep)==1:
                fail('dependency_cycle','任务依赖存在循环',active[positions[dep]:]+[dep])
            elif not colors.get(dep):
                colors[dep]=1
                positions[dep]=len(active)
                active.append(dep)
                stack.append((dep,iter(overlay[dep].get('dependencies',[]))))
    for (uid,week),hours in weekly.items():
        if uid in members and hours>members[uid].weekly_hours+1e-6:
            week_start=date.fromisoformat(week)
            week_end=date.fromordinal(min(date.max.toordinal(),week_start.toordinal()+6))
            keys=[k for k,t in overlay.items() if t['assignee_id']==uid and t['status']!='done' and k in ranges
                  and ranges[k][0]<=week_end and ranges[k][1]>=week_start]
            fail('weekly_capacity','该成员当周剩余工作量超过所填容量',keys,user_id=uid,week=week,
                 allocated_hours=round(hours,3),capacity_hours=members[uid].weekly_hours)
    return {'valid':not violations,'violations':violations,
            'calculation':'剩余工时按任务日期范围内的周一至周五均匀分配到各周；纯周末任务计入开始日所在周；已完成任务不占容量'}
