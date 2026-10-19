"""从归档源码加载 v2，只导入无启动副作用的当前公共模块。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parents[1] / 'backend'
DEPENDENCIES = ('schemas.py', 'planning.py', 'models.py', 'serializers.py', 'database.py', 'permissions.py')
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_baseline(overrides=None):
    manifest = json.loads((ROOT / 'baseline' / 'manifest.json').read_text(encoding='utf-8'))
    results = {}
    for name in ('agent.py',) + DEPENDENCIES:
        archived = ROOT / 'baseline' / name
        expected = manifest['backend/app/' + name]
        if sha256(archived) != expected:
            raise RuntimeError('归档基线源码 SHA 不匹配：' + name)
        current = (overrides or {}).get(name, BACKEND / 'app' / name)
        if name != 'agent.py' and sha256(current) != expected:
            raise RuntimeError('v2 公共依赖与归档不一致：' + name)
        results[name] = expected
    return results


def baseline_provider_module():
    verify_baseline()
    name = 'app.agent_v2_frozen'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / 'baseline' / 'agent.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


# 不调用 Settings/prepare，不导入 app.main，不接触正式数据库或凭据文件。
from app.agent import OpenAIProvider, ProjectTools
from app.database import Database
from app.models import Card, Course, Member, Message, Project, Requirement, Task, User
from app.planning import check_plan
from app.schemas import AgentOutput
from app.serializers import message_json


def provider_class(group):
    if group == 'baseline_v2':
        return baseline_provider_module().OpenAIProvider
    if group == 'improved_v3':
        return OpenAIProvider
    raise ValueError('未知比较组')
