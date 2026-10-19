"""显式初始化演示数据；正常服务启动不会自动插入。"""
from datetime import date, timedelta
from sqlalchemy import select
from .config import Settings
from .database import Database
from .models import Course, Member, Plan, Project, Requirement, Task, User
from .security import hash_password
from .serializers import task_json

PASSWORD='Demo2026!'


def seed_demo(Session):
    with Session() as db:
        if db.scalar(select(User).where(User.username=='teacher')):
            return False
        users={}
        for username,name in [('teacher','演示教师'),('leader','一组组长'),('member1','一组成员甲'),('member2','一组成员乙'),
                              ('leader2','二组组长'),('member3','二组成员甲')]:
            user=User(username=username,name=name,identity='teacher' if username=='teacher' else 'student',password_hash=hash_password(PASSWORD))
            db.add(user)
            db.flush()
            users[username]=user
        today=date.today()
        stages=[{'name':name,'deadline':(today+timedelta(days=days)).isoformat(),'deliverables':[materials]}
                for name,days,materials in [('需求与计划检查',14,'需求清单与开发计划'),('开发中期检查',35,'中期成果与调整说明'),('最终验收',56,'代码、报告、测试与演示材料')]]
        course=Course(teacher_id=users['teacher'].id,title='【演示数据】课程项目智能协作系统',
                      description='仅用于功能演示与权限测试。团队完成账号权限和协作工作区。',
                      acceptance_criteria='必做功能通过接口与界面测试；权限隔离、计划一致性、阶段材料和报告通过教师验收。',
                      required_features=['账号权限','协作工作区'],optional_features=['智能助手'],references=[],stages=stages,status='published')
        db.add(course)
        db.add(Course(teacher_id=users['teacher'].id,title='【演示数据】未发布课程草稿',description='学生不可见草稿'))
        db.flush()
        # 取未来的下周一，便于容量及依赖排期演示。
        monday=today+timedelta(days=(7-today.weekday()) or 7)
        for team,accounts in [('一组',['leader','member1','member2']),('二组',['leader2','member3'])]:
            p=Project(course_id=course.id,name=f'【演示数据】{team}课程项目',description='独立团队；无预制 Agent 输出。',status='active')
            db.add(p)
            db.flush()
            for i,name in enumerate(accounts):
                db.add(Member(project_id=p.id,user_id=users[name].id,role='leader' if i==0 else 'member',skills=['Python'] if i<2 else ['Vue'],weekly_hours=12))
            db.flush()
            tasklist=[]
            for i,feature in enumerate(course.required_features):
                req=Requirement(project_id=p.id,title=feature,description=f'实现{feature}，用于演示需求关联。',acceptance='通过功能与权限测试',
                                course_feature=feature,priority='must',status='confirmed',creator_id=users[accounts[0]].id)
                db.add(req)
                db.flush()
                assignee=users[accounts[min(i+1,len(accounts)-1)]].id
                task=Task(project_id=p.id,title=f'实现{feature}',description='演示任务，可人工更新。',requirement_id=req.id,
                          acceptance='接口与页面通过测试',assignee_id=assignee,estimated_hours=6,remaining_hours=6,
                          start_date=monday.isoformat(),due_date=(monday+timedelta(days=4)).isoformat(),creator_id=users[accounts[0]].id,stage_index=0)
                db.add(task)
                db.flush()
                tasklist.append(task)
            db.add(Plan(project_id=p.id,version=1,created_by=users[accounts[0]].id,summary='演示人工初始计划（非模型输出）',tasks=[task_json(t) for t in tasklist],changes=[]))
        db.commit()
        return True


def main():
    settings=Settings().prepare()
    db=Database(settings.database_url)
    db.create_tables()
    created=seed_demo(db.Session)
    db.engine.dispose()
    print('演示数据已创建。' if created else '演示数据已存在，本次未重复创建。')
    print('账号：teacher / leader / member1 / member2 / leader2 / member3；演示密码：Demo2026!')


if __name__=='__main__':
    main()
