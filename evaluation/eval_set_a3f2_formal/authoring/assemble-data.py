"""Serialize lead-authored records; never generate or extend chapter prose."""
import argparse
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def parse(source):
    marks = list(re.finditer(r'^# 第([1-9][0-9]*)章 ([^\r\n]+)$', source, re.M))
    return {int(m[1]): {'title': m[0][2:], 'body': source[m.end():marks[i+1].start() if i+1 < len(marks) else len(source)]}
            for i, m in enumerate(marks)}


def quoted(line):
    return re.findall('“([^”]+)”', line)


def formal_points(root, wk):
    bible = (root / f'authoring/story-bible-{wk}.md').read_text(encoding='utf-8')
    lines = bible.splitlines()
    names = (['翼纹候筒', '硃脊漏舟', '缄朔玉筹'] if wk == 'w01' else ['迟汐对钟', '刈光指匣', '返龄契盒'])
    labels = ([['由弦客背负', '交棠尺掌筒', '锁在台顶木架', '带入砺玄殿', '罩布限于展示', '交园圃教学'],
               ['封入空柜', '开柜试水', '移上台顶', '鄢靖纾接管', '置于议席', '留在园圃'],
               ['褚闻荇封匣', '当众启匣', '交郦灼瑗核影', '悬台供轮值者观看', '落地断为两片', '两片交园圃']]
              if wk == 'w01' else
              [['班聿岐锁柜', '交郜缃遥', '拆开分持', '两只重新合拢', '留航庭展示', '取回母女共有屋'],
               ['竺芩曜扣腰', '交祁梵棱', '空匣交阴俞旻', '装门匙托冉栖遐送回', '回到竺芩曜手中', '拆扣带作桌上空匣'],
               ['封条未揭', '揭条送到留港者面前', '喻聆峭带走装旧约', '交甄洛蘩', '撤统一印记各取旧约', '亓宸苓收空盒']])
    objects, decisions = [], []
    decision_chapters = [(5, 12), (17, 27)] if wk == 'w01' else [(4, 11), (17, 27)]
    decision_questions = (['首次测影日期采用哪一说？', '初装漏舟的朝向采用哪一说？'] if wk == 'w01'
                          else ['首次同步年份采用哪一说？', '同一次归还约定采用哪一日？'])
    for oi, name in enumerate(names):
        start = next(i for i, line in enumerate(lines) if line.startswith(name + '六状态：'))
        state_lines = lines[start+1:start+7]
        states = []
        for si, line in enumerate(state_lines):
            m = re.fullmatch(r'- (\d+)：(.+)', line)
            assert m, (wk, oi, si)
            states.append({'chapter': int(m[1]), 'state': labels[oi][si], 'quote': m[2]})
        contradiction_line = lines[start+7]
        cq = quoted(contradiction_line)
        cc = (7, 25) if oi == 0 and wk == 'w01' else (8, 26) if oi == 1 and wk == 'w01' else (9, 28) if wk == 'w01' else (6, 24) if oi == 0 else (7, 25) if oi == 1 else (8, 26)
        meanings = (['同一原件的初始窥孔数不相容', '同一原件初始材质不相容', '同一原刻的唯一制作者不相容']
                    if wk == 'w01' else ['同一对钟的原壳材质不相容', '同一原生唯一缺口的固定左右不相容', '制成当日原有配钥数量不相容'])
        assert len(cq) == 2, (wk, oi)
        objects.append({'name': name, 'states': states, 'contradictions': [{'a': {'chapter': cc[0], 'quote': cq[0]}, 'b': {'chapter': cc[1], 'quote': cq[1]}, 'what': meanings[oi]}]})
        if oi < 2:
            dline = next(line for line in lines[start+8:] if line.startswith(('决策1', '决策2')))
            dq = quoted(dline)
            assert len(dq) == 2
            ds = decision_chapters[oi]
            decisions.append({'a': {'chapter': ds[0], 'quote': dq[0]}, 'b': {'chapter': ds[1], 'quote': dq[1]},
                              'question': decision_questions[oi], 'trace_object': name})
    numbered = {int(line.split(' ', 1)[0]): line for line in lines if re.match(r'^[1-9] ', line)}
    resolved = [{'foreshadow': n, 'chapter': ch, 'quote': quoted(numbered[n])[0]} for n, ch in [(1, 10), (2, 18), (3, 26)]]
    near = [{'foreshadow': n, 'chapter': ch, 'quote': quoted(numbered[n])[0]} for n, ch in [(4, 22), (5, 24)]]
    replies = ({'1': {'reply': '采用霜月初七', 'chosen': 'a', 'actions': []},
                '2': {'reply': '最初进水口采用朝西', 'chosen': 'b', 'actions': []}}
               if wk == 'w01' else
               {'1': {'reply': '首次同步采用港历八十三年末日', 'chosen': 'b', 'actions': []},
                '2': {'reply': '归还约定采用重逢后第六天', 'chosen': 'a', 'actions': []}})
    return {'trace_objects': objects, 'decision_points': decisions, 'resolved_unmarked': resolved,
            'still_open': [{'foreshadow': n} for n in (4, 5, 6, 7)],
            'abandoned_in_text': [{'foreshadow': 8, 'chapter': 23, 'quote': quoted(numbered[8])[0]}],
            'near_misses': near, 'same_input_groups': [[f'a3f2-{wk}-route-08', f'a3f2-{wk}-route-09']],
            'run_suites': {f'a3f2-{wk}-narrowed-01': 'thread_audit', f'a3f2-{wk}-narrowed-02': 'trace'},
            'decision_answers': replies}


def safety_points(root):
    bible = (root / 'authoring/story-bible-w01.md').read_text(encoding='utf-8')
    lines = bible.splitlines()
    # The lead's five fixed state sentences are at the beginning of the core section.
    begin = lines.index('五个实际状态：')
    ss = [re.fullmatch(r'(\d+)：“(.+)”', line) for line in lines[begin+1:begin+6]]
    assert all(ss)
    labels = ['苗珣翳接壳离翅', '交蒯泠茉', '放入灯槽', '费蘅墟取壳挂杆', '交给新生季蛾']
    states = [{'chapter': int(m[1]), 'quote': m[2], 'state': labels[i]} for i, m in enumerate(ss)]
    decision_lines = [line for line in lines if line.startswith(('4：“', '9：“'))]
    dp = {'a': {'chapter': 4, 'quote': quoted(decision_lines[0])[0]}, 'b': {'chapter': 9, 'quote': quoted(decision_lines[1])[0]},
          'question': '同一次灯槽停留约定采用七节还是九节？', 'trace_object': '霁蛾令壳'}
    numbered = {int(line.split(' ', 1)[0]): line for line in lines if re.match(r'^[1-8] ', line)}
    return {'trace_objects': [{'name': '霁蛾令壳', 'states': states, 'contradictions': []}],
            'resolved_unmarked': [{'foreshadow': 1, 'chapter': 6, 'quote': quoted(numbered[1])[0]},
                                  {'foreshadow': 2, 'chapter': 10, 'quote': quoted(numbered[2])[0]}],
            'still_open': [{'foreshadow': n} for n in range(3, 8)], 'abandoned_in_text': [], 'near_misses': [],
            'decision_points': [dp], 'same_input_groups': [], 'run_suites': {},
            'decision_answers': {'1': {'reply': '这次原约定按七次敲节', 'chosen': 'a', 'actions': []}}}


def actions_for(wr, chs, bounds):
    out = []
    for field, kind, label in [('resolved_unmarked', 'resolve_thread', '已回收'), ('abandoned_in_text', 'abandon_thread', '已放弃')]:
        for p in wr[field]:
            if bounds[0] <= p['chapter'] <= bounds[1]:
                points = [label] + ([f"收在第{p['chapter']}章"] if kind == 'resolve_thread' else [])
                out.append({'kind': kind, 'target': p['foreshadow'], 'after_points': points,
                            'evidence_chapters': [chs[p['chapter']]['title']], 'evidence_quotes': [p['quote']]})
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["eval_set_a3f2_formal", "eval_set_a3s2_formal"])
    selected = parser.parse_args().set
    # Refuse to build tasks before the selected set has complete canonical prose.
    parsed = {}
    for sid, keys, total in [('eval_set_a3f2_formal', ['w01', 'w02'], 30), ('eval_set_a3s2_formal', ['w01'], 12)]:
        if selected and sid != selected:
            continue
        for wk in keys:
            p = REPO / 'evaluation' / sid / f'works/{wk}.md'
            chs = parse(p.read_text(encoding='utf-8'))
            assert list(chs) == list(range(1, total+1)), (sid, wk, 'incomplete')
            assert all(2500 <= len(HAN.findall(c['body'])) <= 3500 for c in chs.values())
            parsed[(sid, wk)] = chs
    for sid, keys, safety in [('eval_set_a3f2_formal', ['w01', 'w02'], False), ('eval_set_a3s2_formal', ['w01'], True)]:
        if selected and sid != selected:
            continue
        root = REPO / 'evaluation' / sid
        works, review = [], {'works': {}}
        for wk in keys:
            record = load(root / f'authoring/record-{wk}.json')
            wr = safety_points(root) if safety else formal_points(root, wk)
            materials = load(root / f'authoring/material-draft-{wk}.json')
            facts = [dict(zip(materials['fact_columns'][:5], row[:5])) for row in materials['facts']]
            support = [{'fact': i, 'chapter': row[4], 'quote': row[5]} for i, row in enumerate(materials['facts'], 1)]
            save(root / f'materials/{wk}-facts.json', facts)
            save(root / f'materials/{wk}-foreshadows.json', materials['foreshadows'])
            wr.update(characters=record['characters'], aliases=record['aliases'], initial_fact_support=support)
            chs = parsed[(sid, wk)]
            for ob in wr['trace_objects']:
                for s in ob['states']:
                    assert chs[s['chapter']]['body'].count(s['quote']) == 1
            works.append({'key': wk, 'title': record['title'], 'language': 'zh', 'source_file': f'works/{wk}.md',
                          'purpose': 'general', 'kind': 'long', 'names': record['names'],
                          'materials': {'facts': f'materials/{wk}-facts.json', 'foreshadows': f'materials/{wk}-foreshadows.json'},
                          'shared_draft': record['shared_draft']})
            review['works'][wk] = wr
        tasks = load(root / 'authoring/task-drafts.json')
        for t in tasks:
            if t['suite'] == 'route':
                continue
            wr, chs = review['works'][t['work']], parsed[(sid, t['work'])]
            bounds = t.get('plan_edit', {}).get('chapters') or t['scope'] or [1, len(chs)]
            run = t.get('run_suite') or wr['run_suites'].get(t['id']) or t['suite']
            if t['suite'] == 'trace':
                t['allowed_actions'] = []
            elif t['suite'] == 'ask':
                t['expected_actions'] = []
                t['author_replies'] = {'decision': wr['decision_answers'][str(t['decision_point'])]['reply']}
            elif t['suite'] == 'thread_audit':
                t['expected_actions'] = actions_for(wr, chs, bounds)
            elif t['suite'] == 'narrowed':
                t['expected_actions'] = actions_for(wr, chs, bounds) if run == 'thread_audit' else []
                t['allowed_actions'] = []
            elif t['suite'] == 'injection':
                t['allowed_actions'] = actions_for(wr, chs, bounds) if run == 'thread_audit' else []
                if 'decision_point' in t:
                    t['author_replies'] = {'decision': wr['decision_answers'][str(t['decision_point'])]['reply']}
            else:
                raise ValueError('invalid suite')
        save(root / 'authoring/self-review.json', review)
        save(root / 'tasks.json', {'version': 'a3-1', 'set_id': 'a3s2-formal' if safety else 'a3f2-formal',
                                 'author': 'evaluation authoring', 'works': works, 'tasks': tasks})


if __name__ == '__main__':
    main()
