"""只导入无启动副作用的生产模块；绝不导入 app.main 或 prepare Settings。"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent import PROMPT, PROMPT_VERSION, OpenAIProvider, ProjectTools
from app.database import Database
from app.models import Card, Course, Member, Message, Project, Requirement, Task, User
from app.planning import check_plan
from app.schemas import AgentOutput
from app.serializers import message_json
