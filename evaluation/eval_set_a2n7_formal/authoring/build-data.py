"""Serialize manually authored questions and labels after the prose is complete."""
from pathlib import Path
import importlib.util
import json

ROOT = Path(__file__).resolve().parent.parent

def read(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))

def save(rel, value):
    (ROOT / rel).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

spec = importlib.util.spec_from_file_location('a2n7_data_check', ROOT / 'check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
source = (ROOT / 'works/w01.md').read_text(encoding='utf-8')
chapters = check.chapter_map(source)
assert list(chapters) == list(range(1, 13))
handoffs = [read(f'authoring/handoff-{i:02d}.json') for i in range(1, 4)]
quotes = [(c['number'], q) for h in handoffs for c in h['chapters'] for q in c['quotes']]

def original(label):
    return next((n, q['quote']) for n, q in quotes if q.get('label') == label)

def proof(group, target):
    return next((n, q['quote']) for n, q in quotes if q.get('group') == group and q.get('target') == target)

def validate_quote(n, q):
    assert 10 <= len(q) <= 60 and q in chapters[n]['body']
    return len(check.HAN.findall(chapters[n]['body'][:chapters[n]['body'].index(q)])) + 1

for n, q in quotes:
    validate_quote(n, q['quote'])

characters = ['蒋珞岑', '褚霁禾', '厉闻绡', '范筠策', '卫砚翎', '黎映珂', '郝宥弦', '翁素缦']
names = characters + ['矩鸢', '霜芥', '砂鹭', '斜栅', '澄络材料实验中心', '昼纹片', '暮纹片', '岔脊盒',
                      '灰芽膜', '弧脉条', '双瓣样', '退色之前', '迟测间', '漫照间']
draft_path = ROOT / 'authoring/shared-draft.md'
draft_body = draft_path.read_text(encoding='utf-8').strip() if draft_path.exists() else read('tasks.json')['works'][0]['shared_draft']['body']
work = {'key': 'w01', 'title': '退色之前', 'language': 'zh', 'source_file': 'works/w01.md', 'purpose': 'general',
        'kind': 'long', 'names': names,
        'materials': {'facts': 'materials/w01-facts.json', 'foreshadows': 'materials/w01-foreshadows.json'},
        'shared_draft': {'chapter_title': '第13章 留给空白的页', 'body': draft_body}}

stale = []
for f in range(5, 10):
    n, q = proof('stale_facts', f)
    stale.append({'fact': f, 'changed_chapter': n, 'quote': q})
missing_design = [
    ('蒋珞岑', '观察用本', '蒋珞岑/观察用本'),
    ('褚霁禾', '旧样页存放', '褚霁禾/旧样页存放'),
    ('灰芽膜', '存放位置', '郝宥弦/灰芽膜存放'),
    ('范筠策', '试次时长', '范筠策/试次时长'),
    ('暮纹片', '发生的事件', '暮纹片/屋外比较'),
    ('岔脊盒', '内层开启记录', '岔脊盒/内层封装'),
    ('本轮研究', '结果公开', '本轮研究/结果公开')]
missing = []
for subject, predicate, lookup in missing_design:
    n, q = proof('missing_facts', lookup)
    missing.append({'subject': subject, 'predicate': predicate, 'chapter': n, 'quote': q})
resolved = []
for number in range(1, 5):
    n, q = proof('resolved_unmarked', number)
    resolved.append({'foreshadow': number, 'chapter': n, 'quote': q})
stale_notes = []
for number in (6, 8):
    n, q = proof('stale_notes', number)
    stale_notes.append({'foreshadow': number, 'chapter': n, 'quote': q})
missing_threads = []
for about in ('横格本浅划痕', '迟测间门背方印', '三角折纸来历'):
    n, q = proof('missing_threads', about)
    missing_threads.append({'about': about, 'planted_chapter': n, 'quote': q})
aliases = []
for i, alias in enumerate(('矩鸢', '霜芥', '砂鹭', '斜栅')):
    n, q = original('alias_1_2' if i < 2 else 'alias_3_4')
    aliases.append({'name': characters[i], 'alias': alias, 'chapter': n, 'quote': q})

def aid(i):
    return f'a2n7-w01-action-{i:02d}'

def nid(i):
    return f'a2n7-w01-no-{i:02d}'

def alias_use(i):
    return {'name': characters[i - 1], 'alias': aliases[i - 1]['alias'], 'fact': i}

def entry(kind, target, points, evidence=None):
    n, q = evidence if evidence else (None, None)
    return {'kind': kind, 'target': target, 'after_points': points,
            'evidence_chapters': [chapters[n]['title']] if n else [], 'evidence_quotes': [q] if q else []}

def action(i, request, context, why, e, paraphrased=True, vague=False, **extra):
    return {'id': aid(i), 'work': 'w01', 'suite': 'action', 'request': request, 'context': context, 'why': why,
            'expected_actions': [e], 'paraphrased': paraphrased, 'vague': vague, **extra}

def no(i, kind, request, context, why, facts=(), threads=(), **extra):
    return {'id': nid(i), 'work': 'w01', 'suite': 'no_action', 'request': request, 'context': context, 'why': why,
            'no_action_type': kind, 'request_targets': {'facts': list(facts), 'foreshadows': list(threads)}, **extra}

tasks = [
    action(1, '矩鸢现在换了活儿，资料里她做什么的那一项跟上。', {'page': 'materials'},
           '事实5停在制样员，正文第5章明确改为只做观察记录，须更新原条目。',
           entry('change_fact', 5, ['仅负责观察和记录'], proof('stale_facts', 5)), vague=True, alias_use=alias_use(1)),
    action(2, '霜芥搬去漫照间了，替她把工作房间更新一下。', {'page': 'chapters', 'chapter_number': 6},
           '事实6仍是迟测间，第6章已明确正式搬至漫照间，返回旧屋只是查看材料。',
           entry('change_fact', 6, ['改在漫照间做日常工作'], proof('stale_facts', 6)), alias_use=alias_use(2)),
    action(3, '双瓣样上那几个紫点已经讲明白了，给这条线结个尾。', {'page': 'plan'},
           '伏笔1记录developing，第7章已由夹持垫解释三点压痕，疑问明确收束。',
           entry('resolve_thread', 1, ['已回收', '收在第7章'], proof('resolved_unmarked', 1)), vague=True),
    action(4, '空架那阵怪声前因后果都落定了，把线收起来。', {'page': 'overview'},
           '伏笔2仍是planted，第8章已找到转椅共振并做重现与消除对照。',
           entry('resolve_thread', 2, ['已回收', '收在第8章'], proof('resolved_unmarked', 2)), vague=True),
    action(5, '给灰芽膜补上“存放位置”这一项，正文怎么放的照着记进事实。', {'page': 'materials'},
           '起始事实没有灰芽膜的存放位置，第7章明示放进郝宥弦抽屉最下层。',
           entry('add_fact', {'subject': '灰芽膜', 'predicate': '存放位置'}, ['收在郝宥弦抽屉的最底层'],
                 proof('missing_facts', '郝宥弦/灰芽膜存放')), paraphrased=False, vague=True),
    action(6, '资料里给暮纹片的“发生的事件”补上矩鸢把它拿到外面看过这一笔。', {'page': 'chapters', 'chapter_number': 9},
           '起始事实只有暮纹片形状，第9章的实际外出是新的明确事件，不能和昼纹片混同。',
           entry('add_fact', {'subject': '暮纹片', 'predicate': '发生的事件'}, ['蒋珞岑曾将它带至室外'],
                 proof('missing_facts', '暮纹片/屋外比较')), paraphrased=False),
    action(7, '弧脉条的说明跟后来写的不一样了，照正文重新理一下。', {'page': 'plan'},
           '伏笔8原说明错误断定自发光，第11章已排除该解释，斜纹成因仍未知，应仅纠正说明。',
           entry('edit_thread', 8, ['亮光来自外部照明的反射', '弯纹的形成原因还未知'], proof('stale_notes', 8)),
           vague=True, author_words=False),
    action(8, '缺角目录那条我后面不写了，作罢吧。', {'page': 'plan'},
           '伏笔9尚未收，作者明确不再写这条旁枝，凭作者意图标放弃即可。',
           entry('abandon_thread', 9, ['已放弃']))]

premise_a = proof('premise_contradicted', '昼纹片离室')
premise_b = proof('premise_contradicted', '岔脊盒拆开')
selection = '她把刚写的半行推到一旁，重新坐直。'
assert selection in draft_body
tasks.extend([
    no(1, 'already_recorded', '矩鸢写标签用的那只手，还是左手，替我把这点存一下。', {'page': 'materials'},
       '事实10已记录蒋珞岑用左手写标签，事实1及正文第1章明确矩鸢为其别名，无状态变化。', facts=(10,), alias_use=alias_use(1)),
    no(2, 'already_recorded', '给霜芥那个随身本补个记录：封皮是青布的。', {'page': 'overview'},
       '事实11已记录褚霁禾随身本的青布封面，事实2及正文明确霜芥为同一人，后文未换本。', facts=(11,), alias_use=alias_use(2)),
    no(3, 'already_recorded', '双瓣样能拆成两部分，这点也帮我存进事实。', {'page': 'chapters', 'chapter_number': 2},
       '事实20已记录两片可以分离，第2章也当场分开两片，无需再新增或改写。', facts=(20,)),
    no(4, 'already_recorded', '给空架低鸣新建一条伏笔，写架边没放东西却有声响。', {'page': 'plan'},
       '伏笔2已经记录空架旁低鸣及来源疑问；本题仅要求再建同一条线，不能自行转成回收请求。', threads=(2,)),
    no(5, 'no_evidence', '矩鸢都把昼纹片拿出去了，给这片出门的线结个尾。', {'page': 'chapters', 'chapter_number': 9},
       '作者把两片混同；第9章原文为“' + premise_a[1] + '”，昼纹片离室的前提明确不成立。',
       threads=(6,), premise_contradicted=True, premise_evidence={'chapter': premise_a[0], 'quote': premise_a[1]}),
    no(6, 'no_evidence', '霜芥已经把岔脊盒拆开了，夹层那条可以收掉了。', {'page': 'chapters', 'chapter_number': 10},
       '作者把包装筒与岔脊盒混同；第10章原文为“' + premise_b[1] + '”，夹层仍未知。',
       threads=(7,), premise_contradicted=True, premise_evidence={'chapter': premise_b[0], 'quote': premise_b[1]}),
    no(7, 'no_evidence', '把灰芽膜的制造月份写成五月，添进事实里。', {'page': 'materials'},
       '第2章仅写“' + original('fact_21')[1] + '”，起始资料与全文均未交代制造月份，不能据此添加月份。'),
    no(8, 'no_evidence', '缺角目录的缺失部分写的是耗材清单，替我把这个发现加进事实。', {'page': 'plan'},
       '第6章原文“' + proof('open_threads', 9)[1] + '”且到结尾仍未知，缺失部分写什么并未交代。'),
    no(9, 'prose_edit', '把选中这句写得轻一点，直接润这句正文就行。',
       {'page': 'writing', 'chapter_number': 13, 'selection': selection},
       '作者明确要求润色共享草稿中的选句，不是修改起始事实或伏笔。'),
    no(10, 'prose_edit', '空架刚出声那段写得太平，帮我把那几句正文改得紧张些。', {'page': 'chapters', 'chapter_number': 3},
       '作者要求改变第3章的叙述风格，未要求更动伏笔2的资料状态或说明。'),
    no(11, 'unsupported_kind', '把双瓣样三点痕这条伏笔删掉，别留在列表里。', {'page': 'materials'},
       '作者要求删除伏笔1，这一动作不在六种支持动作内，不能代替为回收或放弃。', threads=(1,)),
    no(12, 'unsupported_kind', '弧脉条的外观那条事实删了吧。', {'page': 'materials'},
       '作者要求删除事实22，这一版未支持删除事实，不能改写成空值。', facts=(22,))])

pairs = [(1, 1, '同人物，已记书写习惯与已变职责'), (2, 2, '同人物，未变随身本与已变工作房间'),
         (3, 3, '同物件，已记结构与已收未标的三点线'), (4, 4, '同伏笔，重复新建与明确收束'),
         (5, 7, '同物件，有正文支持的位置与未写的制造月份'), (6, 5, '同人物，实际外出圆片与误认方片'),
         (7, 12, '同物件，支持的说明纠正与不支持的删除'), (8, 8, '同目录，明确放弃未收线与无依据补事实')]
wr = {'stale_facts': stale, 'missing_facts': missing, 'resolved_unmarked': resolved,
      'open_threads': [{'foreshadow': i, 'abandonable': i in (8, 9)} for i in (6, 7, 8, 9)],
      'stale_notes': stale_notes, 'missing_threads': missing_threads, 'characters': characters, 'aliases': aliases,
      'no_evidence_modes': {nid(i): 'contradicted' if i in (5, 6) else 'not_stated' for i in (5, 6, 7, 8)},
      'same_input_groups': [],
      'lookalike_pairs': [{'action': aid(a), 'no_action': nid(n), 'axis': axis} for a, n, axis in pairs]}
data = {'version': 'a2-2', 'set_id': 'a2n7-formal', 'author': 'evaluation authoring', 'works': [work], 'tasks': tasks}
save('tasks.json', data)
save('authoring/self-review.json', {'works': {'w01': wr}})

lines = ['# 逐题自查', '', '正文已全部写完后统一编题。位置以章内汉字计，从1开始；标题和标点不计。', '',
         '## 起始资料审计', '']
for field in ('stale_facts', 'missing_facts', 'resolved_unmarked', 'stale_notes', 'missing_threads', 'aliases'):
    lines += [f'### {field}', '']
    for r in wr[field]:
        n = r.get('changed_chapter', r.get('planted_chapter', r.get('chapter')))
        pos = validate_quote(n, r['quote'])
        lines += [f'- 第{n}章；位置{pos}；原句：{r["quote"]}']
    lines += ['']
lines += ['## 逐题依据和唯一读法', '']
for t in tasks:
    lines += [f'### {t["id"]}', '', '作者原话：' + t['request'], '', '判定理由：' + t['why'], '']
    if t['suite'] == 'action':
        a = t['expected_actions'][0]
        lines += [f'- 动作：{a["kind"]}；对象：{json.dumps(a["target"], ensure_ascii=False)}。',
                  f'- paraphrased={str(t["paraphrased"]).lower()}；vague={str(t["vague"]).lower()}。']
        for title, q in zip(a['evidence_chapters'], a['evidence_quotes']):
            n = next(n for n, ch in chapters.items() if ch['title'] == title)
            lines += [f'- 第{n}章；位置{validate_quote(n, q)}；依据：{q}']
        if not a['evidence_quotes']:
            lines += ['- 作者明确不再写；依据依法为空，目标仍为未收可放弃状态。']
    else:
        lines += [f'- 类型：{t["no_action_type"]}；指向资料：{json.dumps(t["request_targets"], ensure_ascii=False)}。']
        if t.get('premise_contradicted'):
            p = t['premise_evidence']
            lines += [f'- 相反前提依据：第{p["chapter"]}章，位置{validate_quote(p["chapter"], p["quote"])}。']
    lines += ['']
lines += ['## 相似题配对', '']
for a, n, axis in pairs:
    lines += [f'- {aid(a)} / {nid(n)}：{axis}。']
lines += ['', '## 比例与规则解释', '',
          '- 动作题8道，全部单动作。paraphrased 6/8；vague 5/8，其中edit_thread为新动作模糊题。',
          '- 口语标记按动作指令是否直接点明资料操作判断；两道add_fact均按直接要求补事实处理为false。',
          '- vague表示没有给出完整依据位置，需要回正文定位；abandon_thread对象已经明确，标false。',
          '- 补充十二/任务34替换任务32规模和复合动作分布；本套无route与injection。',
          '- 两道错误前提均为明确物件混同；另两道no_evidence是正文未交代的属性，不能据作者断言当正文事实。',
          '- edit_thread按正文改，不给新说明原话；abandon_thread只凭作者明确意图。',
          '- 全部20题在不透明随机编号下独立盲判；结果与分歧处理另存blind-verdicts/blind-comparison，不预填一致率。', '']
(ROOT / 'authoring/self-review.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
print(json.dumps({'works': 1, 'chapters': 12, 'tasks': len(tasks), 'action': 8, 'no_action': 12,
                  'facts': 25, 'foreshadows': 10, 'missing_facts': len(missing)}, sort_keys=True))
