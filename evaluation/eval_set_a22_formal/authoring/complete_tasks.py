"""Literal lead-authored question records; no source prose is generated here."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


data = load(ROOT / 'authoring/lead-authored.json')
route_tasks = [t for t in data['tasks'] if t['suite'] == 'route']
assert len(route_tasks) == 20
literal = {
    'w01': [
        ('洛拓读字那点能耐，替我记进事实，我忘了是哪回露出来的。', 'overview', None, False, True,
         [('add_fact', 1, ['能直接识读反向封泥字'])], '正文第五章明确交代识读反印封泥的能力，起始资料没有此项；别名有全名绑定，忘记章号不妨碍定位。'),
        ('第六章副手碰封护材料的忌讳也收着，后文别又让他空手上。', 'materials', None, True, False,
         [('add_fact', 2, ['松脂接触会引起皮疹', '处理封护物需要手套'])], '第六章从误触、皮肤反应和当事人说明写明松脂限制，资料缺失；请求绕开原句表达限制和处理要求。'),
        ('陶爰宁对那层蓝色东西的处置，按第八章留个底，先别擦掉的意思要有。', 'chapters', 8, True, False,
         [('add_fact', 3, ['蓝色附着物暂予留存'])], '第八章明确要求暂留铜片上的蓝色附着物，现有资料未记；请求以不要擦掉的日常说法新增同一安排。'),
        ('第十章辨沟的结论记进事实；第十七章那枚陶筹落在谁手里，也一并补上。', 'writing', 21, False, False,
         [('add_fact', 4, ['西侧斜沟是过去的探沟']), ('add_fact', 5, ['梁霁衡保管那枚陶筹'])], '两个并列请求分别由第十章的辨沟结论和第十七章的交接直接支持，均不在起始事实中；它们没有互相替代。'),
        ('第十一章已把匣子交出去了，保管那格别还挂洵铲，照新交接换过来。', 'materials', None, True, False,
         [('change_fact', 1, ['保管者是于蓁洛'])], '第十一章完成保管交接，起始资料仍指旧保管人；请求用别名和交接指向唯一事实，现保管人应据正文更正。'),
        ('袋子现在别再放驻地架上了，按第十二章挪库后的落脚点改那格。', 'chapters', 12, True, False,
         [('change_fact', 2, ['现存北侧临时库'])], '第十二章写明袋子移到北侧临时库，旧架位置失效；请求改的是位置，不是袋子外观或新的保管人。'),
        ('帮我改事实：第十三章现场带班换人了，原负责人那条跟上交接。', 'materials', None, False, False,
         [('change_fact', 3, ['许珈岚不再指挥现场', '褚临禾接任现场负责人'])], '第十三章只更换现场负责人，许珈岚的项目负责人身份仍保留；更正应局限于失效的现场职责。'),
        ('第十六章拍照那人的手已经能使劲了，状态跟上；尺子折过的事也改掉旧说法。', 'writing', 21, True, False,
         [('change_fact', 4, ['左拇指已经恢复健康']), ('change_fact', 5, ['中段断损', '不可再作现场比对'])], '第十六章的恢复与第十五章的断尺是两个独立变化，均有旧事实可改；断裂不否认尺尾旧墨仍可观察。'),
        ('匣盖漏砂那桩已经查明了吧，把那条挂着的疑问收一收，具体章数我想不起来。', 'plan', None, True, True,
         [('resolve_thread', 1, ['已回收', '收在第9章'])], '第九章给出砂粒来自垫袋的直接验证，起始伏笔还未回收；含糊章号仍有唯一对象，评分点只写状态和回收章。'),
        ('把铜片缺角的伏笔标成已回收，依据用第十四章能拼上的那段。', 'plan', None, False, False,
         [('resolve_thread', 2, ['已回收', '收在第14章'])], '第十四章通过实物边缘拼合查清缺角，伏笔仍列未结；题目只要求标回收，金标不强制补写回收经过。'),
        ('第十八章都讲清旧墨画的是啥了，尺尾那根线可以落账了。', 'chapters', 18, True, False,
         [('resolve_thread', 3, ['已回收', '收在第18章'])], '第十八章将尺尾旧墨与旧测线直接对照，足以回收；口语落账表示收线，未要求把解释写成新的要点。'),
        ('棚后的双印不用再吊着，第二十章把来路交代够了，让这条退到结清那边。', 'overview', None, True, False,
         [('resolve_thread', 4, ['已回收', '收在第20章'])], '第二十章用同车往返的连续证据交代双印来路，原伏笔仍未标回收；只登记回收状态和该章。'),
    ],
    'w02': [
        ('谌溪允辨颜色那个限制，帮我记进事实，章数我忘了。', 'overview', None, False, True,
         [('add_fact', 1, ['红绿辨色受限', '识别标记要借助形状'])], '第五章交代红绿辨色限制及形状补偿，起始资料没有此项；虽未给章号，人物和能力限制指向明确。'),
        ('第六章门自己关上的那套先停了，资料也记住现在只能手动锁。', 'materials', None, True, False,
         [('add_fact', 2, ['外门自闭设备停用', '修复前人工锁住'])], '第六章明确停用外门自闭装置并改人工锁闭，资料缺该现行安排；请求以日常描述转述设备状态。'),
        ('第八章兽医说这回没另添镇静药，这个安排给她留一格，免得我下回想当然。', 'chapters', 8, True, False,
         [('add_fact', 3, ['本次迁护未另加镇静药'])], '第八章限定本次迁护没有新增镇静药，资料中没有这一安排；不把本次决定外推为永久禁药规则。'),
        ('第十章叫声从哪来的结论记进事实，顺带把第十七章秤归谁看管也补上。', 'writing', 21, False, False,
         [('add_fact', 4, ['短叫来自内侧兽舍', '并非栏外流浪狗']), ('add_fact', 5, ['错点秤归温奉苇收管'])], '第十章确认声音来源，第十七章另交接秤的保管；两个缺失事实可各自引用，不能以外侧猜测替代内舍结论。'),
        ('十一章匣子换了接手的人，别再把川笛填作保管，按交接改。', 'materials', None, True, False,
         [('change_fact', 1, ['谌溪允接管匣子'])], '第十一章完成保管责任交接，旧事实仍在旧人名下；别名已有绑定，只改保管人而不改变匣的外观。'),
        ('第十二章那个铃已经跟着值班台走了，原来的位置一栏跟着挪。', 'chapters', 12, True, False,
         [('change_fact', 2, ['位置是岩洄隔离区的值班台'])], '第十二章下午另行迁铃至新值班台，旧兽舍位置已失效；不能把狼迁入和铃迁移混作同一瞬间。'),
        ('帮我改事实：第十三章以后谁管夜里的巡看，别还写原先那位。', 'materials', None, False, False,
         [('change_fact', 3, ['薄映苓交出夜巡负责工作', '温奉苇接任夜巡负责人'])], '第十三章夜巡负责人交接明确，旧负责人记录需更正；薄映苓的饲养组协调身份并未随之失效。'),
        ('十六章麦恺寻走路已经不用撑着了，那格改改；旧入口牌也不再挂着，别漏这一处。', 'writing', 21, True, False,
         [('change_fact', 4, ['右踝恢复', '行走无需拐杖']), ('change_fact', 5, ['旧入口牌已被卸下'])], '第十六章确认踝伤恢复和不再用拐，第十五章入口牌已卸存；两个旧状态都需跟进，不要求新增身份。'),
        ('铃多响一下那事有了着落，把这根一直悬着的线收掉，我找不到具体章号。', 'plan', None, True, True,
         [('resolve_thread', 1, ['已回收', '收在第9章'])], '第九章以挂环现象解释多响，伏笔仍未标回收；不知道章号不等于没有正文依据，评分只要求状态和回收章。'),
        ('门边灰团那条伏笔按第十四章标成已回收，别还留个问号。', 'plan', None, False, False,
         [('resolve_thread', 2, ['已回收', '收在第14章'])], '第十四章通过旧遮帘断口和搬运证词确定灰团来路；题目只要标回收，不额外要求写解释。'),
        ('十八章两道线讲明白了，旧表那项疑问可以从待查里退出来。', 'chapters', 18, True, False,
         [('resolve_thread', 3, ['已回收', '收在第18章'])], '第十八章把旧表双线明确为换班界限，起始伏笔仍悬置；待查退出来是口语的回收指令。'),
        ('第二十章已经把窗边那点亮光解释完了，给那条线结个尾吧。', 'overview', None, True, False,
         [('resolve_thread', 4, ['已回收', '收在第20章'])], '第二十章直接复现并说明窗边亮点来源，原伏笔未回收；不将仍未解决的空白、低啸或便条也一起收掉。'),
    ],
}
no_action_literals = {
    'w01': [
        ('already_recorded', '洵铲干的是地层记录，这项身份存到人物事实里，省得漏。', 'materials', None, None, 'fact_subject', '孟庭洵', '身份',
         '起始事实已记录地层记录员身份，正文第一章与之相符；重复添加同一主体、谓词没有新信息。',
         [{'chapter': 1, 'quote': '他在砾汀遗址任地层记录员'}]),
        ('already_recorded', '出土的东西得先把位置记全再挪，这条规矩也替我补进库。', 'overview', None, None, 'fact_subject', '砾汀遗址', None,
         '移动出土物前保留原位记录的规则已在起始事实，正文第一章也直接交代；无需重复添卡。',
         [{'chapter': 1, 'quote': '砾汀遗址移动出土物前必须保留原位记录，连随手捡起再放回也不能省略这一步。'}]),
        ('no_evidence', '洛拓的生日按八月十二号加进去，人物资料别空着。', 'materials', None, None, None, None, None,
         '全书和起始资料均未交代该人物生日；用户自带日期不构成作品依据，不能新增生日事实。', []),
        ('no_evidence', '第十二章袋子已进余灿市的展厅了，位置那条替我换过去。', 'chapters', 12, None, 'fact_index', 2, None,
         '第十二章实际位置是北侧临时库而非市内展厅；虽然旧事实确实需改，也不能照错误目的地出卡。', 'stale2'),
        ('prose_edit', '我选的这句转折太松，拆短一点，语气别那么郑重。', 'writing', 21,
         '孟庭洵把写到一半的说明纸按在桌上，等于蓁洛把空出的椅子推近。', None, None, None,
         '请求只编辑共享草稿的句式和语气，没有添加、更正事实或回收伏笔的资料意图。', []),
        ('unsupported_kind', '地形测绘员那项不用留了，把梁霁衡的身份事实删掉。', 'materials', None, None, 'fact_subject', '梁霁衡', '身份',
         '明确要求删除已有身份事实；删除事实不在A2支持的三类动作中，不替用户改写成更正或新增。', []),
    ],
    'w02': [
        ('already_recorded', '麦恺寻就是面向孩子做讲解的那位，这份工作身份帮我存一下。', 'materials', None, None, 'fact_subject', '麦恺寻', '身份',
         '起始事实已经登记教育活动员身份，第三章正文相符；日常讲解描述未改变同一身份信息。',
         [{'chapter': 3, 'quote': '麦恺寻是园里的教育活动员，习惯把复杂的动物习性讲成孩子能听懂的小事。'}]),
        ('already_recorded', '一个人只走外侧的员工路也得先告诉值班人，这个规矩补到资料。', 'overview', None, None, 'fact_index', 20, None,
         '独自进入外侧工作通道也要报到的规则在起始资料已存在，第二章正文直接支持；请求没有新条件。',
         [{'chapter': 2, 'quote': '荫阔保育园的规矩是，独自进入外侧工作通道也要向值班人报到。'}]),
        ('no_evidence', '裴汀晏出生那年填一九九〇年，人物信息别缺着了。', 'materials', None, None, None, None, None,
         '正文没有给出该人物出生年份，现有资料也没有；用户指定年份不是证据，不能据此出资料卡。', []),
        ('no_evidence', '沉叶铃到了游客问询处，位置那条替我写成服务台后面的抽屉。', 'chapters', 12, None, 'fact_index', 2, None,
         '第十二章迁铃终点是隔离区值班台，不是游客服务台抽屉；不能仅因位置旧而把错误新值接受为金标。', 'stale2'),
        ('prose_edit', '选中的动作太零碎，把人来回犹豫的那股劲写得干脆些。', 'writing', 21,
         '郗弥川在门边停下，没有马上回答薄映苓递来的那张纸。', None, None, None,
         '要求重写选段节奏和动作表达，不涉及资料变动；共享草稿不是自动形成新事实的来源。', []),
        ('unsupported_kind', '旧观察表空着那条线我不追了，把这条伏笔改为放弃。', 'plan', None, None, 'thread_index', 5, None,
         '请求放弃仍未解的伏笔；A2只支持回收且正文并未解决此线，不将放弃伪装成已回收。', []),
    ],
}
new_tasks = []
data['no_action_review'] = {}
data['no_action_evidence'] = {}
for wk in ['w01', 'w02']:
    bible = load(ROOT / 'authoring' / f'{wk}-bible.json')
    facts = load(ROOT / 'materials' / f'{wk}-facts.json')
    if isinstance(facts, dict):
        facts = facts['facts']
    for i, (request, page, chapter, para, vague, actions, why) in enumerate(literal[wk], 1):
        context = {'page': page}
        if chapter is not None:
            context['chapter_number'] = chapter
        new_tasks.append({'id': f'a22f-{wk}-action-{i:02d}', 'work': wk, 'suite': 'action',
                          'request': request, 'context': context, 'expected_actions': actions,
                          'paraphrased': para, 'vague': vague, 'why': why})
    for i, (kind, request, page, chapter, selection, target_mode, subject, predicate, why, proofs) in enumerate(no_action_literals[wk], 1):
        tid = f'a22f-{wk}-no-action-{i:02d}'
        context = {'page': page}
        if chapter is not None:
            context['chapter_number'] = chapter
        if selection is not None:
            context['selection'] = selection
        targets = {'facts': [], 'foreshadows': []}
        if target_mode == 'fact_subject':
            matches = [j for j, f in enumerate(facts, 1) if f['subject'] == subject and (predicate is None or f['predicate'] == predicate)]
            # The site has several properties; the pre-move recording rule is the sole intended duplicate.
            if wk == 'w01' and i == 2:
                matches = [19]
            assert len(matches) == 1, (wk, i, len(matches))
            targets['facts'] = matches
        elif target_mode == 'fact_index':
            targets['facts'] = [subject]
        elif target_mode == 'thread_index':
            targets['foreshadows'] = [subject]
        if proofs == 'stale2':
            p = bible['stale_facts'][1]
            proofs = [{'chapter': p['changed_chapter'], 'quote': p['quote']}]
        new_tasks.append({'id': tid, 'work': wk, 'suite': 'no_action', 'request': request, 'context': context,
                          'no_action_type': kind, 'request_targets': targets, 'why': why})
        data['no_action_review'][tid] = why
        data['no_action_evidence'][tid] = proofs
    new_tasks.extend(t for t in route_tasks if t['work'] == wk)
assert len(new_tasks) == 56
data['tasks'] = new_tasks
(ROOT / 'authoring/lead-authored.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({'tasks': len(new_tasks), 'route_preserved': len(route_tasks)}, sort_keys=True))
