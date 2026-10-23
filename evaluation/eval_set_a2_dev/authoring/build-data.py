"""Serialize lead-authored labels; prose is read unchanged, never generated here."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
NAMES = ['池澍宁', '池秒', '邵闻葭', '葭姐', '程以硕', '程扣', '贺谨棠', '陆纭珊',
         '龚序南', '汤越晴', '范秉遥', '奚慕白', '照榆市', '衡杉大厦', '青砚街',
         '橘点卡夹', '双岔门牌', '灰耳计时器']

# Each evidence choice and each request/point below was written individually by
# the lead after all 20 chapters existed. Helpers only serialize those literals.
STALE = [
    {'fact': 1, 'changed_chapter': 11, 'quote': '池澍宁把橘点卡夹交给贺谨棠，原件从此由贺谨棠保管。'},
    {'fact': 2, 'changed_chapter': 12, 'quote': '临时照护空间改设在二层内侧空房，七层东侧小会议室不再作为试办场地。'},
    {'fact': 3, 'changed_chapter': 13, 'quote': '周五散场后的收尾协调改由邵闻葭负责，池澍宁不再承担这一时段的协调。'},
    {'fact': 4, 'changed_chapter': 14, 'quote': '灰耳计时器的蜂鸣已经失灵，屏幕倒数仍然正常。'},
    {'fact': 5, 'changed_chapter': 16, 'quote': '程以硕获准每周四下午五点离楼，余下整理改为远程完成，其他日子不变。'},
]
MISSING = [
    {'subject': '汤越晴', 'predicate': '纸质变更单收取时段', 'chapter': 6,
     'quote': '汤越晴只在周二午休接收纸质接送变更单，其他时段不收纸单。'},
    {'subject': '陆纭珊', 'predicate': '饮食限制', 'chapter': 7,
     'quote': '陆纭珊不吃花生，试办点心单已排除所有花生类点心。'},
    {'subject': '双岔门牌', 'predicate': '备用箭头保管人', 'chapter': 8,
     'quote': '范秉遥保管双岔门牌的备用箭头，借出和归还都由他登记。'},
    {'subject': '奚慕白', 'predicate': '试办清洁工时支付', 'chapter': 9,
     'quote': '奚慕白为试办安排的清洁工时从试办预算单独支付，不占原有保洁工时。'},
    {'subject': '龚序南', 'predicate': '故障截图要求', 'chapter': 10,
     'quote': '龚序南只接收遮去儿童姓名的故障截图，不收露出姓名的原图。'},
    {'subject': '衡杉大厦', 'predicate': '每日参与上限', 'chapter': 15,
     'quote': '池澍宁将每日参与上限定为六个家庭，临时来访也不能突破这个数。'},
]
RESOLVED = [
    {'foreshadow': 1, 'chapter': 15, 'quote': '门牌背面的旧孔是旧打印夹的定位孔，并不对应第二个房号。'},
    {'foreshadow': 2, 'chapter': 16, 'quote': '预算里的两笔押金其实是同一笔先后显示，重复列项已撤回。'},
    {'foreshadow': 3, 'chapter': 17, 'quote': '三下声响是自动遮光帘回位敲到窗框造成的，并非屋内有人敲击。'},
    {'foreshadow': 4, 'chapter': 18, 'quote': '那张空白页是汤越晴给临时改签者预留的背页，并非漏掉了一个家庭。'},
]


def write_json(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def main():
    source = (ROOT / 'works/w01.md').read_text(encoding='utf-8')
    headings = list(re.finditer(r'^# (第(\d+)章 .+)$', source, re.M))
    assert len(headings) == 20, 'Complete the prose before writing labels.'
    chapters = {int(m[2]): (m[1], source[m.end():headings[i+1].start() if i+1 < len(headings) else len(source)])
                for i, m in enumerate(headings)}
    assert all(2500 <= len(HAN.findall(body)) <= 3500 for title, body in chapters.values())
    def point(kind, index, after):
        item = {'add_fact': MISSING, 'change_fact': STALE, 'resolve_thread': RESOLVED}[kind][index-1]
        chapter = item.get('changed_chapter', item.get('chapter'))
        target = ({'subject': item['subject'], 'predicate': item['predicate']} if kind == 'add_fact'
                  else item['fact'] if kind == 'change_fact' else item['foreshadow'])
        return {'kind': kind, 'target': target, 'after_points': after,
                'evidence_chapters': [chapters[chapter][0]], 'evidence_quotes': [item['quote']]}
    def action(number, request, context, expected, paraphrased, vague, why):
        return {'id': f'a2d-action-{number:02}', 'work': 'w01', 'suite': 'action', 'request': request,
                'context': context, 'expected_actions': expected, 'paraphrased': paraphrased, 'vague': vague, 'why': why}
    tasks = [
        action(1, '汤越晴什么时候收纸改单，还有陆纭珊不吃哪类点心，这两项都记进事实。',
               {'page': 'materials', 'chapter_number': 7},
               [point('add_fact', 1, ['纸改单仅在每周二的午休时段受理']),
                point('add_fact', 2, ['陆纭珊不碰花生', '点心采购也避开含花生品种'])], False, False,
               '两项均已在正文明确，起始事实没有对应字段，需要同卡补两条而非覆盖其他资料。'),
        action(2, '备用指向板归谁收、清扫的钱从哪出，这两笔漏项一起补上吧。',
               {'page': 'chapters', 'chapter_number': 9},
               [point('add_fact', 3, ['另备箭头由范秉遥收存']),
                point('add_fact', 4, ['房间清扫单独走试办经费', '不挤占日常保洁的工时'])], True, True,
               '需要自行定位第八、九章，对应两个不同对象的遗漏事实，两处都补齐才完整。'),
        action(3, '给龚序南那条传图规矩留个底，省得家长下回把孩子资料原样发过去。',
               {'page': 'writing', 'chapter_number': 21},
               [point('add_fact', 5, ['报修图中须先挡去孩子姓名', '带姓名的原始画面不能交给龚序南'])], True, False,
               '作者用留底表达补资料，目标是报修图的姓名遮挡规则，不能扩写为收集私人账户。'),
        action(4, '池秒后来把报名数压到多少户来着？按最后定下的数把这项记上。',
               {'page': 'overview'},
               [point('add_fact', 6, ['每天接待至多六户', '临时到访也不许超额'])], True, True,
               '虽含问句，后半句明确要求记录最终限额，需要检索正文定位而非只答数字。'),
        action(5, '橘点卡夹跟试办房间都换过了，资料还在老样子，把这两处跟上。',
               {'page': 'materials'},
               [point('change_fact', 1, ['当前保管者为贺谨棠']),
                point('change_fact', 2, ['改在二楼里面的闲置房间', '不再用七楼东侧会议室试办'])], True, True,
               '两个目标都是既有旧记录，应分别改事实一和二，不能只新增新状态留下旧值。'),
        action(6, '周五收尾现在该找葭姐了，把资料里还是池秒的那项换掉。',
               {'page': 'chapters', 'chapter_number': 13},
               [point('change_fact', 3, ['周五结束后的协调归邵闻葭', '池澍宁已卸下这一时段的协调'])], True, False,
               '两个人的别名都已明示，换负责人是同一条动态事实的更新，不是增加新角色。'),
        action(7, '灰耳计时器那栏写得太乐观了，照它坏掉后的实际情况调整一下。',
               {'page': 'writing', 'chapter_number': 21},
               [point('change_fact', 4, ['蜂鸣器已坏', '显示面板仍能倒计时'])], True, False,
               '应改声音状态同时保留可用的屏幕功能，不能笼统说设备完全不能使用。'),
        action(8, '把程扣周四能提前离楼、远程收尾的安排更新到事实里。',
               {'page': 'materials', 'chapter_number': 16},
               [point('change_fact', 5, ['周四下午五点可离开大厦', '剩余整理工作线上完成', '其余日期照常安排'])], False, False,
               '第十六章书面批准取代第五章旧安排，早走不等于免除后续工作或所有日期都可早走。'),
        action(9, '门牌那个孔已经解释清楚，不用再吊着，帮我给这条线画个句号。',
               {'page': 'plan', 'chapter_number': 15},
               [point('resolve_thread', 1, ['伏笔状态改为已回收', '回收章节为第十五章'])], True, False,
               '旧孔来由已由附件与实物核实，应将伏笔一回收，保留正文查明的普通定位孔解释。'),
        action(10, '预算里多算的押金查清啦，这根线可以收起来了。',
               {'page': 'materials', 'chapter_number': 16},
               [point('resolve_thread', 2, ['伏笔状态改为已回收', '回收章节为第十六章'])], True, False,
               '原流水证明是同一笔重复显示，且重复列项撤回，满足伏笔二的实际收束。'),
        action(11, '空房的敲击声都找到来源了，伏笔里给它标成已回收。',
               {'page': 'plan', 'chapter_number': 17},
               [point('resolve_thread', 3, ['伏笔状态改为已回收', '回收章节为第十七章'])], False, False,
               '七层声响经现场复现来自自动遮光帘，与已经坏掉的计时器蜂鸣是不同事件。'),
        action(12, '汤越晴留的那张没填字的纸，后来不是说开了吗？别再当悬念留着了。',
               {'page': 'overview'},
               [point('resolve_thread', 4, ['伏笔状态改为已回收', '回收章节为第十八章'])], True, True,
               '需自行查到第十八章背页用途和无漏户的说明，更新伏笔四而非删除原记录。'),
    ]
    no_items = [
        ('already_recorded', '池秒平常写字使右手，这个也替我记进事实。', {'page': 'materials'}, [6], [],
         '事实六已经记录右手习惯，第1章也明确，重复请求不应新增同义事实。'),
        ('already_recorded', '程扣和汤越晴以前是夫妻、现在共同带女儿，这个情况记一下。', {'page': 'materials'}, [21], [],
         '事实二十一已经完整记录离婚和共育关系，第5章有直白叙述，不再加卡。'),
        ('no_evidence', '把池澍宁设定里的年龄填成三十二吧，按正文来。', {'page': 'chapters'}, [], [],
         '全书没有交代池澍宁年龄，不能将作者给出的新数字冒充正文核实的事实。'),
        ('no_evidence', '按正文给池澍宁补一条：她一直都靠左手写字。', {'page': 'chapters', 'chapter_number': 1}, [6], [],
         '第1章和现有事实六都明确右手，正文与请求相反，因此不给左手的变更卡。'),
        ('prose_edit', '把共享草稿开头改得干脆点，直接写她推门进来就开会。', {'page': 'writing', 'chapter_number': 21}, [], [],
         '作者要求的是改草稿句子，超出三种资料动作，说明应由作者编辑正文。'),
        ('unsupported_kind', '周末开放那条我决定不写了，把伏笔标成放弃。', {'page': 'plan'}, [], [6],
         '目标是伏笔六，但本版只支持标已回收，不支持放弃，不能偷偷用回收替代。'),
    ]
    for n, (kind, request, context, fact_ids, thread_ids, why) in enumerate(no_items, 1):
        tasks.append({'id': f'a2d-no-action-{n:02}', 'work': 'w01', 'suite': 'no_action', 'request': request,
                      'context': context, 'no_action_type': kind,
                      'request_targets': {'facts': fact_ids, 'foreshadows': thread_ids}, 'why': why})
    selection = '墙边的灰耳计时器亮着数字，陆纭珊看了一眼，仍按自己的表核对时间。'
    route_items = [
        ('汤越晴递改单那会儿是哪段时间？帮我记到人物资料。', {'page': 'chapters'}, 'change',
         '前半问时间，后半明确要求把查证结果写入资料，整体是变更意图。'),
        ('灰耳计时器都不出声了，资料里那行换成坏后的样子。', {'page': 'materials'}, 'change',
         '口语要求替换旧状态，资料修改意图明确。'),
        ('门牌背后的旧孔已经交代透了，别再让伏笔挂着。', {'page': 'plan'}, 'change',
         '口语要求结束伏笔记录的悬置状态，应进入改资料。'),
        ('给奚慕白的清洁费用另立一条事实，来源按正文写。', {'page': 'materials'}, 'change',
         '明确要求新增事实并查证支付来源。'),
        ('程扣周四的工作安排，资料里现在是怎么写的？', {'page': 'materials'}, 'ask',
         '只是询问资料现有记法，没有要求改写记录，不能因出现资料一词便判变更。'),
        ('资料还写正常，第十四章灰耳计时器到底坏了吗？', {'page': 'chapters', 'chapter_number': 14}, 'ask',
         '询问正文是否发生变化，未下达任何资料变更指令。'),
        ('这部分跟前面能不能对得上？', {'page': 'materials'}, 'ask',
         '资料页没有正文选区或检查结果，只是在问现有资料与前文关系，按问作品处理。'),
        ('我要接着往下写，先提醒我眼下哪些事已落定、哪些还悬着。', {'page': 'writing', 'chapter_number': 21}, 'recap',
         '下笔前要回顾当前进展与未决事项，未要求改资料。'),
        ('这部分跟前面能不能对得上？', {'page': 'writing', 'chapter_number': 21, 'selection': selection}, 'check_passage',
         '同一句输入在writing页有明确的共享草稿选区，应核对所选段落与前文一致性。'),
        ('替我写封明天请半天事假的邮件，收件人是我主管。', {'page': 'overview'}, 'out_of_scope',
         '请求处理作者现实请假邮件，与作品没有关系。'),
    ]
    for n, (message, context, route, why) in enumerate(route_items, 1):
        tasks.append({'id': f'a2d-route-{n:02}', 'work': 'w01', 'suite': 'route', 'input': message,
                      'context': context, 'expected_route': route, 'why': why})
    draft = json.loads((ROOT / 'authoring/shared-draft.json').read_text(encoding='utf-8'))
    data = {'version': 'a2-1', 'set_id': 'a2-dev', 'author': 'evaluation authoring',
            'works': [{'key': 'w01', 'title': '下班前的那扇门', 'language': 'zh', 'source_file': 'works/w01.md',
                       'purpose': 'general', 'kind': 'long', 'names': NAMES,
                       'materials': {'facts': 'materials/w01-facts.json', 'foreshadows': 'materials/w01-foreshadows.json'},
                       'shared_draft': draft}], 'tasks': tasks}
    review = {'stale_facts': STALE, 'missing_facts': MISSING, 'resolved_unmarked': RESOLVED,
              'same_input_groups': [['a2d-route-07', 'a2d-route-09']],
              'characters': [{'name': name, 'aliases': aliases} for name, aliases in
                             [('池澍宁', ['池秒']), ('邵闻葭', ['葭姐']), ('程以硕', ['程扣']), ('贺谨棠', []),
                              ('陆纭珊', []), ('龚序南', []), ('汤越晴', []), ('范秉遥', []), ('奚慕白', [])]]}
    write_json('tasks.json', data)
    write_json('authoring/self-review.json', review)
    write_json('authoring/blind-route-inputs.json', [{'id': t['id'], 'input': t['input'], 'context': t['context']}
                                                   for t in tasks if t['suite'] == 'route'])
    lines = ['# A2 调试集逐题自查', '', '本文件中的逐题判定由主控统一编写。程序仅把手写理由与实际计数、引句位置对齐。', '',
             '## 正文与资料差异', '',
             '正文没有预设内部矛盾。事实1–5是起始资料中的旧值：分别来自第1–5章，后在第11、12、13、14、16章改变。其余25条保持正确，含历史事件的记录不冒充当前状态。', '',
             '遗漏事实6处全部用于加事实题；已收未标4处全部用于收伏笔题。伏笔5–7到第20章仍未收，伏笔8第9章已找回水杯且资料已标resolved，不可再次回收。', '',
             '|登记|对象|章节|依据原句|首汉字位置|', '|---|---|---:|---|---:|']
    for label, items in [('过时事实', STALE), ('缺的事实', MISSING), ('已收未标', RESOLVED)]:
        for i, item in enumerate(items, 1):
            chapter = item.get('changed_chapter', item.get('chapter'))
            body = chapters[chapter][1]
            quote = item['quote']
            assert body.count(quote) == 1, (label, i, 'quote')
            position = len(HAN.findall(body[:body.index(quote)])) + 1
            target = str(item.get('fact', item.get('foreshadow', item.get('subject'))))
            lines.append(f'|{label}{i}|{target}|{chapter}|{quote}|{position}|')
    lines.extend(['', '## 动作题逐项核对', '',
                  '每题第一项是主要动作；两项卡片完整列出两个目标。resolve_thread的after_points只要求状态与回收章，剧情解释用于核对证据，不额外要求改伏笔描述。', ''])
    for task in tasks:
        if task['suite'] != 'action':
            continue
        lines.extend(['### ' + task['id'], '', task['why'], ''])
        for item in task['expected_actions']:
            target = json.dumps(item['target'], ensure_ascii=False)
            lines.append(f'- `{item["kind"]}`，目标 `{target}`；新值要点：' + '；'.join(item['after_points']) + '。')
            for title, quote in zip(item['evidence_chapters'], item['evidence_quotes']):
                chapter = next(n for n, (t, b) in chapters.items() if t == title)
                body = chapters[chapter][1]
                position = len(HAN.findall(body[:body.index(quote)])) + 1
                lines.append(f'  依据：{title}，章内第{position}个汉字；“{quote}”')
        lines.append('')
    lines.extend(['## 不该改的题逐项核对', ''])
    for task in tasks:
        if task['suite'] == 'no_action':
            lines.extend(['### ' + task['id'], '', f'类型`{task["no_action_type"]}`。' + task['why'],
                          '指向资料：' + json.dumps(task['request_targets'], ensure_ascii=False) + '。', ''])
    lines.extend(['## 用法题逐项核对', '',
                  '两道形似改资料的问句为route-05和06；口语change为route-01、02、03。route-07与09只换context，input逐字相同。没有also_acceptable和support FIX。', ''])
    for task in tasks:
        if task['suite'] == 'route':
            lines.extend(['### ' + task['id'], '', f'期望`{task["expected_route"]}`。' + task['why'], ''])
    lines.extend(['## 稳定事实核对目录', '',
                  '事实6–10：右手、三个别名、汤越晴采购员身份，见第1–3章。事实11–15：审核非审批、书面带班边界、楼宇系统边界、出口巡检、保洁排班负责人，见第1、3、4、5章。', '',
                  '事实16–21：城市、首次需求收集、卡夹用途、门牌结构、计时器无录音、离婚共育，见第1、2、4、5章。事实22–28：场地考察、纸折临时标记、公开排班、通道恢复、取手套而非测试、借笔核查、空场演练，见第2–5章。事实29：交接记录四字段，第11章。事实30：七层暂定后未开放报名，第2章。', '',
                  '## 独立复核与歧义处理', '',
                  '路由盲判只提供authoring/blind-route-inputs.json的id、input、context，不提供本文件和金标；结果和全文审读将另行登记。', '',
                  '依据章节采用完整标题，起始资料和自查用整数；主动作按第一项计数。A2明确20章及第21章草稿、半数引句>1500，不套用A1c旧集30章或额外的三分之一>2500数量要求，但如实报告两种位置计数。', '',
                  '题目长度与短字段上限从严按Unicode字符数；正文/共享草稿只数汉字。照抄取达到8汉字即失败；专名作为边界，和全作品比对。新颖性只比较获准旧集输入字段，三个禁读集及并行A2集在遍历前排除，零重合不覆盖这些目录。', ''])
    (ROOT / 'authoring/self-review.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    paths = sorted([ROOT / 'tasks.json'] + [p for directory in ('works', 'materials')
                                          for p in (ROOT / directory).rglob('*') if p.is_file()],
                   key=lambda p: p.relative_to(ROOT).as_posix())
    (ROOT / 'set.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' +
                                            p.relative_to(ROOT).as_posix() + '\n' for p in paths),
                                     encoding='utf-8', newline='\n')
    print(json.dumps({'tasks': len(tasks), 'manifest_files': len(paths), 'source_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
