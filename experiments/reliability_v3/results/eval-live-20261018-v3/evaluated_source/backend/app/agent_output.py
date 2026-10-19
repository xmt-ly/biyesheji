"""真实模型输出的纯规范化与保守事实核对；不改变公共卡片协议。"""
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import Field, model_validator

from .schemas import AgentOutput, DraftTask, Payload, SqlId, TaskKey


class FactEvidence(Payload):
    task_key: TaskKey
    field: Literal['assignee_id', 'estimated_hours', 'remaining_hours', 'start_date', 'due_date']
    message_id: SqlId | None = None
    quote: str | None = Field(default=None, min_length=1, max_length=20000)
    card_id: SqlId | None = None
    source_task_key: TaskKey | None = None

    @model_validator(mode='after')
    def one_source(self):
        message = self.message_id is not None and self.quote is not None
        card = self.card_id is not None and self.source_task_key is not None
        if message == card or (message and (self.card_id is not None or self.source_task_key is not None)) or (
                card and (self.message_id is not None or self.quote is not None)):
            raise ValueError('证据必须完整引用一条消息或一张卡片')
        return self


class AnalysisSubmission(Payload):
    analysis: AgentOutput
    task_evidence: list[FactEvidence] = Field(default_factory=list, max_length=1500)


_CONDITIONAL = re.compile(r'如果|假如|若|假设|要是|也许|可能|暂定|待定|不确定|能否|是否|[?？]')
_NEGATIVE = re.compile(r'尚未|还没|不能|不要|不想|不负责|不承担|不做|不接|不会|不愿|不由|并非|不是|没有|未确定')
_NUMBER = r'(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百]+)'
_HOURS = re.compile(r'(?<![\d.])(?P<number>' + _NUMBER + r')(?P<half_before>个?半)?(?:个)?'
                    r'(?:小时|钟头|hours?\b|h\b)(?P<half_after>半)?|(?P<half>半)(?:个)?小时', re.I)
_DATE = re.compile(r'(?<!\d)(?:(?P<iso_y>\d{4})-(?P<iso_m>\d{1,2})-(?P<iso_d>\d{1,2})(?!\d)|'
                   r'(?:(?P<cn_y>\d{4})年)?(?P<cn_m>\d{1,2})月(?P<cn_d>\d{1,2})日?|'
                   r'(?P<day>\d{1,2})[日号]|(?P<relative>今天|明天|(?<!大)后天))')
_ROLES = {'start_date': r'开始|启动|开工', 'due_date': r'截止|完成|结束|交付|提交'}
_QUESTIONS = {'assignee_id': '请确认“{title}”的负责人姓名。',
              'estimated_hours': '请确认“{title}”的预计工时（小时）。',
              'remaining_hours': '请确认“{title}”当前剩余工时（小时）。',
              'start_date': '请确认“{title}”的开始日期。',
              'due_date': '请确认“{title}”的截止日期。'}


def _number(text):
    try:
        return float(text)
    except ValueError:
        digits = dict(zip('零〇一二两三四五六七八九', [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
        total, value = 0, 0
        for char in text:
            if char in digits:
                value = digits[char]
            elif char in '十百':
                total += (value or 1) * (10 if char == '十' else 100)
                value = 0
            else:
                return None
        return float(total + value)



def _task_scope(clause, title, previous, members):
    """True/False 绑定或切断；None 只保持话题，不从元数据提取承诺。"""
    text = clause.strip().rstrip('。！？!?').strip()
    name = re.escape(title)
    if re.fullmatch(r'(?:(?:请)?(?:.+需求下)?(?:需要)?新增)?'
                    r'(?:任务(?:是|为)?[:：]?\s*)?' + name + r'(?:任务)?', text):
        return True
    if re.fullmatch(r'(?:关联|对应|归属).+需求|(?:依赖|前置(?:任务)?(?:是|为|[:：])?).+|'
                    r'验收(?:标准|条件)?(?:是|为|[:：]|须|需).+|(?:放在|安排在).+阶段', text):
        return None
    action = re.search(r'(?:负责(?!人)|承担|接手|来做|完成|做)\s*(.+)$', text)
    if action:
        return action.group(1).strip() == title
    if text.startswith(title):
        suffix = text[len(title):]
        if re.match(r'(?:任务)?(?:的)?(?:负责人|由|安排|预计|估时|估计|剩余|还需|开始|启动|截止|待|需要)', suffix) or _DATE.match(suffix):
            return True
    people = '|'.join(re.escape(member['name']) for member in members.values())
    owner = r'(?:我' + ('|' + people if people else '') + r')'
    if re.fullmatch(r'(?:这项(?:任务)?|这个任务|该任务)?\s*' + owner +
                    r'\s*(?:来|会)?\s*(?:负责|承担|接手|来做|完成|做)', text) or re.fullmatch(
                    r'负责人(?:是|为|[:：])?\s*' + owner, text):
        return previous
    if re.match(r'预计|估时|估计|剩余|还需|还剩|(?:开始|启动|截止|完成|交付)(?:日期|时间)', text) or _DATE.match(text) or _HOURS.match(text):
        return previous
    return False  # 另一任务或无法唯一归属的描述切断前文继承。


def _task_clauses(content, title, previous, members):
    allowed = set()
    for sentence in re.finditer(r'[^。！？!?\n]+[。！？!?]?', content):
        if _CONDITIONAL.search(sentence.group()):
            previous = False
            continue
        for clause in re.finditer(r'[^，,；;、]+', sentence.group()):
            scope = _task_scope(clause.group(), title, previous, members)
            if scope is None:
                continue
            previous = scope
            if previous:
                allowed.add(sentence.start() + clause.start())
    return allowed, previous


def _fact_fragments(content, quote, scoped_clauses=None):
    """只用引文覆盖的原文，条件保留整句作用域，否定保留所在分句作用域。"""
    start = content.find(quote)
    while start >= 0:
        end = start + len(quote)
        for sentence_match in re.finditer(r'[^。！？!?\n]+[。！？!?]?', content):
            if sentence_match.end() <= start or sentence_match.start() >= end:
                continue
            sentence = sentence_match.group()
            if _CONDITIONAL.search(sentence):
                continue
            for clause_match in re.finditer(r'[^，,；;、]+', sentence):
                clause = clause_match.group()
                if _NEGATIVE.search(clause):
                    continue
                absolute = sentence_match.start() + clause_match.start()
                if scoped_clauses is not None and absolute not in scoped_clauses:
                    continue
                left, right = max(start, absolute), min(end, absolute + len(clause))
                if left < right:
                    yield content[left:right], clause, sentence[:left - sentence_match.start()]
        start = content.find(quote, start + 1)


def _hours_match(quote, field, expected, clause):
    matches, quoted = [], False
    for match in _HOURS.finditer(clause):
        prefix = clause[max(0, match.start() - 24):match.start()]
        if re.search(_NUMBER + r'\s*(?:到|至|或|~|～|-)\s*$', prefix):
            return False  # 不把工时区间或候选值的末端当作已确认的单个估时。
        remaining = bool(re.search(r'剩余|还需|还剩', prefix))
        shared = bool(re.search(r'(?:预计|估时|估计)(?:工时)?\s*(?:与|和|及)\s*剩余(?:工时)?\s*(?:均|都)(?:为|是)?\s*$', prefix))
        if not shared and remaining != (field == 'remaining_hours'):
            continue
        value = .5 if match.group('half') else _number(match.group('number'))
        if value is None:
            continue
        if match.group('half_before') or match.group('half_after'):
            value += .5
        matches.append(value)
        quoted = quoted or match.group() in quote
    return quoted and bool(matches) and set(matches) == {float(expected)}


def _local_day(message):
    try:
        timestamp = datetime.fromisoformat(message['created_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is not None:
            return timestamp.astimezone(timezone(timedelta(hours=8))).date()
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    return None


def _parsed_dates(text, message, year=None, month=None):
    base = _local_day(message)
    year = year if year is not None else (base.year if base else None)
    month = month if month is not None else (base.month if base else None)
    parsed = []
    for match in _DATE.finditer(text):
        try:
            if match.group('iso_y'):
                value = date(*(int(match.group(i)) for i in ('iso_y', 'iso_m', 'iso_d')))
            elif match.group('cn_m'):
                value = date(int(match.group('cn_y')) if match.group('cn_y') else year,
                             int(match.group('cn_m')), int(match.group('cn_d')))
            elif match.group('day'):
                value = date(year, month, int(match.group('day')))
            else:
                if base is None:
                    return None, year, month
                value = base + timedelta(days={'今天': 0, '明天': 1, '后天': 2}[match.group()])
        except (ValueError, TypeError, KeyError, OverflowError):
            return None, year, month
        year, month = value.year, value.month
        parsed.append((match, value.isoformat()))
    return parsed, year, month


def _date_match(quote, field, expected, message, leading, clause):
    _, year, month = _parsed_dates(leading, message)
    # 引文须明确支持该日期，原分句中的其他候选也不能被裁剪掉。
    for text in (clause, quote):
        parsed, _, _ = _parsed_dates(text, message, year, month)
        if parsed is None:
            return False
        candidates = []
        for index, (match, value) in enumerate(parsed):
            before, after = text[:match.start()], text[match.end():]
            role = _ROLES[field]
            if re.search(r'(?:' + role + r')(?:日期|时间)?\s*(?:是|为|[:：])?\s*$', before) or re.match(
                    r'\s*(?:开始|启动|开工)' if field == 'start_date' else r'\s*(?:截止|完成|结束|交付|提交)', after):
                candidates.append(value)
            if index + 1 < len(parsed):
                next_match, next_value = parsed[index + 1]
                between = text[match.end():next_match.start()]
                if re.search(r'或|还是', between):
                    return False
                if re.fullmatch(r'\s*(?:到|至|—|~|～|-)\s*', between):
                    if value > next_value:
                        return False  # 不擅自跨月或跨年解释一个倒序区间。
                    candidates.append(value if field == 'start_date' else next_value)
        if not candidates or set(candidates) != {expected}:
            return False
    return True


def _message_supports(fact, task, members, messages, all_messages):
    message = messages.get(fact.message_id)
    if not message or fact.quote not in message.get('content', ''):
        return False
    previous = False
    for source in all_messages.values():
        if source['id'] not in messages:
            previous = False  # 不能靠省略中间讨论来源来跨任务继承。
            continue
        scoped_clauses, previous = _task_clauses(source['content'], task['title'], previous, members)
        if source['id'] == fact.message_id:
            return any(_fragment_supports(fragment, clause, leading, fact.field, task[fact.field], members, message)
                       for fragment, clause, leading in _fact_fragments(message['content'], fact.quote, scoped_clauses))
    return False


def _fragment_supports(quote, clause, leading, field, value, members, message):
    if field == 'assignee_id':
        if re.search(r'或|还是|二选一', clause):
            return False
        member = members.get(value)
        if not member:
            return False
        name = re.escape(member['name'])
        named = re.search(name + r'\s*(?:来|会)?\s*(?:负责|承担|接手|来做)', quote) or re.search(
            r'(?:负责人(?:是|为|[:：])?|由|安排)\s*' + name, quote)
        self_nomination = message.get('user_id') == value and re.search(
            r'我\s*(?:来|会)?\s*(?:负责|承担|接手|来做|完成|做)', quote)
        return bool(named or self_nomination)
    if field in ('estimated_hours', 'remaining_hours'):
        return _hours_match(quote, field, value, clause)
    return _date_match(quote, field, value, message, leading, clause)


def _card_inherited_fields(content, title):
    """只认同分句内原任务名与明确字段列表，不跨任务或跨字段借用沿用词。"""
    labels = {'负责人': {'assignee_id'}, '预计工时': {'estimated_hours'},
              '剩余工时': {'remaining_hours'}, '工时': {'estimated_hours', 'remaining_hours'},
              '开始日期': {'start_date'}, '截止日期': {'due_date'},
              '日期': {'start_date', 'due_date'}}
    label = '(?:' + '|'.join(labels) + ')'
    fields = r'(?P<fields>(?:所有|全部)字段|' + label + r'(?:\s*[、和与及]\s*' + label + r')*)'
    declaration = re.compile(re.escape(title) + r'(?:任务)?(?:的)?\s*' + fields +
                             r'\s*(?:都|均|全部)?(?:照旧|不变|保持(?:不变|原样)?|沿用(?:原值|原安排)?)')
    inherited = set()
    for sentence in re.finditer(r'[^。！？!?\n]+', content):
        if _CONDITIONAL.search(sentence.group()):
            continue
        for clause in re.finditer(r'[^，,；;]+', sentence.group()):
            if _NEGATIVE.search(clause.group()):
                continue
            match = declaration.fullmatch(clause.group().strip())
            if not match:
                continue
            if re.fullmatch(r'(?:所有|全部)字段', match['fields']):
                inherited.update(_QUESTIONS)
            else:
                for field in re.split(r'\s*[、和与及]\s*', match['fields']):
                    inherited.update(labels[field])
    return inherited


def _card_supports(fact, task, cards, supersedes, messages):
    card = cards.get(fact.card_id)
    if not card or fact.card_id not in supersedes or fact.source_task_key != task['key']:
        return False
    if not any(fact.field in _card_inherited_fields(m['content'], task['title']) for m in messages.values()):
        return False
    source = next((t for t in card.get('tasks', []) if t.get('key') == fact.source_task_key), None)
    if source is None:
        return False
    normalized = DraftTask.model_validate(source).model_dump(mode='json')
    return normalized[fact.field] == task[fact.field]


def prepare_agent_output(analysis, context, messages, task_evidence=()):
    """先验证来源和标识，再去除精确未变项；新承诺缺证据时整体转成追问。

    新任务按来源原名及前文单一任务作用域核对，不借用另一任务的承诺。
    仅识别明确的姓名/自荐、数字及常见中文小时、日期/相对日/明确区间；
    中文月日和省略月份的日号按来源消息上海年月及同句前一明确日期补全。
    这不是通用自然语言蕴含判断器；歧义、条件和否定采取保守处理。
    """
    output = AgentOutput.model_validate(analysis).model_dump(mode='json')
    human = {m['id']: m for m in messages if m.get('kind') == 'human'}
    source_ids = set(output['source_message_ids'])
    if not source_ids <= human.keys():
        raise ValueError('模型来源引用无效')
    if human and not source_ids and (output['tasks'] or output['questions']):
        raise ValueError('模型缺少讨论来源')
    if not source_ids and output['tasks']:
        raise ValueError('任务缺少真实讨论来源')
    referenced = {key: value for key, value in human.items() if key in source_ids}
    keys, ids = set(), set()
    for task in output['tasks']:
        key, existing_id = task['key'], task['existing_id']
        if key in keys or (existing_id is not None and existing_id in ids):
            raise ValueError('草案任务标识重复')
        keys.add(key)
        if existing_id is not None:
            ids.add(existing_id)
            if key != f'task_{existing_id}':
                raise ValueError('现有任务标识不匹配')
        elif not key.startswith('new_'):
            raise ValueError('新任务标识必须以 new_ 开头')
    originals = {t['key']: DraftTask.model_validate(t).model_dump(mode='json')
                 for t in context.get('tasks', [])}
    output['tasks'] = [t for t in output['tasks'] if t['existing_id'] is None or originals.get(t['key']) != t]
    facts = [FactEvidence.model_validate(f) for f in task_evidence]
    members = {m['user_id']: m for m in context.get('members', [])}
    cards = {c['id']: c for c in context.get('pending_cards', [])}
    missing = []
    for task in output['tasks']:
        if task['existing_id'] is not None:
            continue  # 既有任务允许排程推导，生产 check_plan 仍保护完成项及所有引用。
        fields = ['assignee_id', 'estimated_hours', 'start_date', 'due_date']
        if not (task['status'] == 'todo' and task['progress'] == 0 and task['remaining_hours'] == task['estimated_hours']):
            fields.append('remaining_hours')
        for field in fields:
            supported = any(f.task_key == task['key'] and f.field == field and (
                _message_supports(f, task, members, referenced, human) if f.message_id is not None else
                _card_supports(f, task, cards, output['supersedes_card_ids'], referenced)) for f in facts)
            if not supported:
                missing.append(_QUESTIONS[field].format(title=task['title']))
    if missing:
        output['tasks'] = []  # 不保留可能依赖被移除新任务的部分计划。
        output['title'] = '任务信息待确认'
        output['summary'] = '相关任务信息仍需确认，暂时保留原计划。'
        output['questions'] = list(dict.fromkeys([*missing, *output['questions']]))[:100]
    return output
