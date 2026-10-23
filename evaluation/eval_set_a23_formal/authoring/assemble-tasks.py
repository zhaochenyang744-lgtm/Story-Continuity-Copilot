"""Serialize the main author's individually written cases; never generates story prose."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
W01_ONLY = '--w01-only' in sys.argv
data = json.loads((ROOT / 'tasks.json').read_text(encoding='utf-8'))
review = json.loads((ROOT / 'authoring/self-review.json').read_text(encoding='utf-8'))
titles = {}
for work in data['works']:
    titles[work['key']] = {int(n): '第' + n + '章 ' + title for n, title in re.findall(
        r'^# 第([0-9]+)章 ([^\r\n]+)$', (ROOT / work['source_file']).read_text(encoding='utf-8'), re.M)}

def proof(wk, kind, number, points):
    wr = review['works'][wk]
    if kind == 'add_fact':
        p = wr['missing_facts'][number - 1]
        target, chapter = {'subject': p['subject'], 'predicate': p['predicate']}, p['chapter']
    elif kind == 'change_fact':
        p = next(p for p in wr['stale_facts'] if p['fact'] == number)
        target, chapter = number, p['changed_chapter']
    else:
        p = next(p for p in wr['resolved_unmarked'] if p['foreshadow'] == number)
        target, chapter = number, p['chapter']
        points = ['已回收', f'收在第{chapter}章']
    return {'kind': kind, 'target': target, 'after_points': points,
            'evidence_chapters': [titles[wk][chapter]], 'evidence_quotes': [p['quote']]}

tasks = []
def action(wk, n, request, page, chapter, why, paraphrased, vague, entries):
    if W01_ONLY and wk != 'w01':
        return
    tasks.append({'id': f'a23f-{wk}-action-{n:02}', 'work': wk, 'suite': 'action',
                  'request': request, 'context': {'page': page, 'chapter_number': chapter},
                  'why': why, 'paraphrased': paraphrased, 'vague': vague,
                  'expected_actions': [proof(wk, *entry) for entry in entries]})

def no_action(wk, n, request, page, chapter, why, category, facts=(), threads=()):
    if W01_ONLY and wk != 'w01':
        return
    tasks.append({'id': f'a23f-{wk}-no-action-{n:02}', 'work': wk, 'suite': 'no_action',
                  'request': request, 'context': {'page': page, 'chapter_number': chapter},
                  'why': why, 'no_action_type': category,
                  'request_targets': {'facts': list(facts), 'foreshadows': list(threads)}})

def route(wk, n, text, context, expected, why):
    if W01_ONLY and wk != 'w01':
        return
    tasks.append({'id': f'a23f-{wk}-route-{n:02}', 'work': wk, 'suite': 'route',
                  'input': text, 'context': context, 'expected_route': expected, 'why': why})

# Every request, rationale and semantic point below was written individually by the main author.
action('w01', 1, '巫迟雁看得懂旧流水缩写，蔺闻瓷辨警示靠形状，给这两项各添一条资料。', 'chapters', 6,
       '第5章本人说明旧缩写识读能力，第6章本人说明不辨红绿及形状判断限制，两项均未入资料。', True, False,
       [('add_fact', 1, ['能读旧磁条缩写', '须先辨纸型']), ('add_fact', 2, ['红绿难辨', '凭轮廓判警示'])])
action('w01', 2, '颂钮那晚决定留下本案的失败回执，给这项决定留个底。', 'materials', 8,
       '第8章明确保留本案失败回执且当晚不销毁，原资料没有这项决定。', True, False,
       [('add_fact', 3, ['本案失败回执全留', '当晚不销毁'])])
action('w01', 3, '午夜重号最后查出的缘由，往资料里添一笔，我不想再翻半天。', 'overview', 20,
       '请求只给重号成因这一宽泛线索，须回查第10章的旧测试任务结论，不能扩大为实际损失归责。', True, True,
       [('add_fact', 4, ['源自旧测试任务', '不是顾客再刷'])])
action('w01', 4, '灰翅筹剩余归倪序葵、本案顾客免核验费，这两件分别记进事实。', 'plan', 20,
       '第17章交接本次待用和回收筹，第18章免除本案受影响顾客核验费，两项均是资料缺项。', False, False,
       [('add_fact', 5, ['未发出筹由倪序葵收存', '回收筹也交倪序葵']), ('add_fact', 6, ['本案受影响者免核验费'])])
action('w01', 5, '楔蓝盘该归颂钮收着了，七孔袋也进了封存柜，资料两处旧说法一块儿跟上。', 'materials', 12,
       '第11章完成盘的保管交接，第12章完成袋的移存，事实1和2仍是旧值。', True, False,
       [('change_fact', 1, ['现由祁苒颂保管']), ('change_fact', 2, ['存于岫棱支行封存柜'])])
action('w01', 6, '调查牵头已经换成杭疏岑，把应迢夏还挂在那里的事实改一下。', 'chapters', 13,
       '第13章正式交接调查牵头，经理身份不变，只更新事实3的本案负责人。', False, False,
       [('change_fact', 3, ['改由杭疏岑牵头'])])
action('w01', 7, '芒灯的肩后来不是好了吗，资料还写不能举，给跟上吧。', 'overview', 20,
       '请求没有指定恢复章节，须定位第16章痊愈及举臂动作，更新事实4而不改职业。', True, True,
       [('change_fact', 4, ['右肩康复', '右臂可过肩'])])
action('w01', 8, '那把岔尾钳现在裂了，资料还把它算能用的，替我换成后来的情况。', 'writing', 21,
       '第15章钳口开裂并停用，事实5的完好可用状态已经过时。', True, False,
       [('change_fact', 5, ['钳嘴开裂', '停止使用'])])
action('w01', 9, '白点那条在第7章说清了，把这条伏笔标成已回收。', 'chapters', 7,
       '第7章直接解释盘壳白点来自旧封条纤维，伏笔1尚为planted。', False, False,
       [('resolve_thread', 1, [])])
action('w01', 10, '两声短鸣第9章就交代清楚了，去伏笔页给这根线落个结尾。', 'plan', 9,
       '第9章区分两台设备轮流自检与付款行为，伏笔2可以登记回收而不是新增支付事实。', True, False,
       [('resolve_thread', 2, [])])
action('w01', 11, '缺蓝线那根线第14章结清了，资料里别让它一直悬着。', 'materials', 14,
       '第14章发现旧夹中的断线并用原照片排除事后拆封，伏笔3已经实际收束。', True, False,
       [('resolve_thread', 3, [])])
action('w01', 12, '倒序数的来路第19章已经弄明白，给对应伏笔标成已回收。', 'overview', 20,
       '第19章用对应工作底稿确认维护排查次序，伏笔4可回收，不能连带收掉三条长期未知线。', False, False,
       [('resolve_thread', 4, [])])
no_action('w01', 1, '给衡隼补一条惯用手：平常拿笔用左手。', 'materials', 20,
          '事实19已经记录惯用左手，别名指向同一人，重复添加无必要。', 'already_recorded', [19])
no_action('w01', 2, '灰翅筹不能抵付款，只能约人工核验，这个用途也加一条。', 'overview', 20,
          '事实15已完整覆盖预约用途及不是付款凭证，无需再出卡片。', 'already_recorded', [15])
no_action('w01', 3, '我印象里杭疏岑小时候练过拳，替我添到她的经历里。', 'plan', 20,
          '全书没有交代童年练拳经历，作者的不确定回忆不能替代正文依据。', 'no_evidence')
no_action('w01', 4, '衡隼其实一直用右手，现有惯用手那条给我改回来。', 'materials', 20,
          '第1章及后文动作支持惯用左手，请求所称右手与正文冲突，不能据此改事实19。', 'no_evidence', [19])
no_action('w01', 5, '第20章最后一句绕得有点长，帮我拆短，读起来别那么费劲。', 'chapters', 20,
          '请求编辑的是章节正文句子，不是起始事实或伏笔状态，不应出资料变更卡。', 'prose_edit')
no_action('w01', 6, '柜台下面那个三角痕我不打算追了，把那条伏笔标成放弃。', 'plan', 20,
          '作者要求放弃伏笔7，属于当前不支持的abandon_thread，不能伪装成已回收。', 'unsupported_kind', threads=[7])

action('w02', 1, '食铺那位能读反刻，封核师上高处会发怵，给两人各补一条资料。', 'overview', 20,
       '须先解析角色身份，再分别找到第5章反刻识读与第6章怕高及实地操作限制，两个键均未记录。', True, False,
       [('add_fact', 1, ['会辨反刻衡纹', '按刻制方向核读']), ('add_fact', 2, ['惧高', '试验须在实地操作'])])
action('w02', 2, '绯签把废蜡模留下了，不再往炉里送，这个决定给她留在资料中。', 'chapters', 8,
       '第8章保留作废蜡模而不熔回，资料中没有这项决定。', True, False,
       [('add_fact', 3, ['留住作废蜡模', '不熔回'])])
action('w02', 3, '桥上那回偏重的最后解释，添到资料里，别让我再翻整段。', 'plan', 20,
       '请求只指偏重解释，须回查第10章两批载货相叠的验证，不能将它直接等同核的身份判定。', True, True,
       [('add_fact', 4, ['两拨货一道上桥', '并非重核漏重'])])
action('w02', 4, '双齿筹交伍燃缇收了，本轮证人也可留在实地，两项都补到事实页。', 'materials', 20,
       '第17章轮次筹交接和第18章本轮见证选择均未入事实，需要两张独立合法卡片。', False, False,
       [('add_fact', 5, ['交伍燃缇收存']), ('add_fact', 6, ['本轮证人可自选实地见证'])])
action('w02', 5, '任绯棘接回珀坠核，棱脊箱在坠石厅内柜了，这两项存量资料一并同步。', 'materials', 12,
       '第11章核已另行封存交任，第12章移的是原箱，分别更新事实1和2，不能说核仍在箱里。', True, False,
       [('change_fact', 1, ['保管者为任绯棘']), ('change_fact', 2, ['现放坠石厅内柜'])])
action('w02', 6, '主持这案子的已经是柯沉芷，事实里那条还挂纪烛绫，给我改掉。', 'chapters', 13,
       '第13章经权限安排及双方同意后由柯临时接任，事实3过时，不能改掉乌的代诉身份。', False, False,
       [('change_fact', 3, ['柯沉芷临时主持本案'])])
action('w02', 7, '测量员那只脚后来康复了吧，资料怎么还是旧伤，替我跟上。', 'overview', 20,
       '请求未给章号或原句，须定位第16章左踝恢复并可久站的进展，更新事实4。', True, True,
       [('change_fact', 4, ['左踝康复', '可久站'])])
action('w02', 8, '岐臂衡横梁都歪了，资料别再当它能比重，换成如今的状态。', 'writing', 21,
       '第15章横梁弯折导致停用，事实5不再成立，替代称量办法不等于旧衡器恢复。', True, False,
       [('change_fact', 5, ['横梁弯折', '停用不再比对'])])
action('w02', 9, '核颈白丝在第7章有了着落，把相关伏笔记为已回收。', 'chapters', 7,
       '第7章白丝逐股对应旧核座衬线，伏笔1可登记回收，不表示核身份已完全验真。', False, False,
       [('resolve_thread', 1, [])])
action('w02', 10, '第三锤第9章就解释完了，伏笔栏给它补个收束章吧。', 'materials', 9,
       '第9章第三声是换盘校准而非第三次寄重，伏笔2的正文收线与资料状态不同步。', True, False,
       [('resolve_thread', 2, [])])
action('w02', 11, '第14章已经查出箱角小孔怎么来的，那条别再挂着没结局了。', 'plan', 14,
       '第14章原制作资料与旧漆层共同确认排蜡孔，足以收束伏笔3。', True, False,
       [('resolve_thread', 3, [])])
action('w02', 12, '尾页那七个痕第19章说透了，把对应伏笔标成已回收。', 'overview', 20,
       '第19章旧衡器校零次序解释契约尾页刻痕，伏笔4已经收束，三条真正未知线仍开放。', False, False,
       [('resolve_thread', 4, [])])
no_action('w02', 1, '缄砝平时用右手，给他添上惯用手这一项。', 'materials', 20,
          '事实19已记录仇照缄惯用右手，别名不产生另一人，无需重复添加。', 'already_recorded', [19])
no_action('w02', 2, '轮次那种双齿筹不管谁拥有石头，这个用途限制再存一条吧。', 'chapters', 20,
          '事实24已记录只示轮次且不是所有权凭证，与本请求语义相同。', 'already_recorded', [24])
no_action('w02', 3, '给蓝契野添段旧经历吧，我记得他以前在军中当过斥候。', 'overview', 20,
          '全书未交代从军或斥候经历，不能把作者不确定的记忆当成原文依据。', 'no_evidence')
no_action('w02', 4, '重核明明能封活人的重量，把资料里那个限制改回来。', 'materials', 20,
          '第2章明确术法仅作用于无生命物件，事实15正确，请求与固定规则相反。', 'no_evidence', [15])
no_action('w02', 5, '第20章结尾那一句太硬，替我换个柔和些的写法。', 'writing', 21,
          '作者要润色既有正文措辞，没有要求事实更新或伏笔回收。', 'prose_edit')
no_action('w02', 6, '双齿筹的用途那条我不想留在资料里了，直接删掉。', 'materials', 20,
          '请求删除事实24，delete_fact不在首批支持的三种动作内。', 'unsupported_kind', [24])

pair1 = '这处说法照着前文核一遍，有没有互相顶着的？'
pair2 = '这儿和前面能不能同时说通，替我比一比。'
drafts = {w['key']: w['shared_draft']['body'] for w in data['works']}
# Selection literals are chosen only after reading the completed shared drafts.
selections = json.loads((ROOT / 'authoring/route-selections.json').read_text(encoding='utf-8'))
route('w01', 1, '盘都交给颂钮了，资料那边也换人呗。', {'page': 'materials'}, 'change', '陈述交接后明确要求资料同步，是口语更新请求。')
route('w01', 2, '那回午夜重号的来由，帮我往事实页上留一笔。', {'page': 'overview'}, 'change', '口语要求新增成因事实，需查原文后给资料变更。')
route('w01', 3, '七孔袋已经进封存柜，把旧位置替换掉。', {'page': 'chapters', 'chapter_number': 12}, 'change', '明确替换资料中的旧存放位置。')
route('w01', 4, '白点那根线结了，伏笔页给它落个收束章。', {'page': 'plan'}, 'change', '明确要求把已收束的伏笔状态与章号更新。')
route('w01', 5, '楔蓝盘那项保管人，现在资料里仍写着最开始那位吗？', {'page': 'materials'}, 'ask', '问资料目前写法，没有命令修改或确认新的值。')
route('w01', 6, '我想补免核验费这件事，现有事实会不会已经记过？', {'page': 'overview'}, 'ask', '询问是否已记录以决定之后是否添加，当前没有授权添加。')
route('w01', 7, pair1, {'page': 'overview'}, 'ask', '没有选区、草稿定位或已有issue，泛指一致性询问，按默认问答处理。')
route('w01', 8, '接着写第二十一章前，盘、袋、人手三头的现状给我捋顺。', {'page': 'writing', 'chapter_number': 21}, 'recap', '要继续写作前的多项现状回顾。')
route('w01', 9, pair1, {'page': 'writing', 'chapter_number': 21, 'selection': selections['w01']}, 'check_passage', '同句在写作页带草稿完整选句，明确对该片段做连续性检查。')
route('w01', 10, '跟这本没关系，教我折一个能站在桌上的纸支架。', {'page': 'overview'}, 'out_of_scope', '与作品无关的折纸操作请求。')
route('w02', 1, '核已经还给任绯棘了，资料那一格别再留旧名字。', {'page': 'materials'}, 'change', '口语命令更新保管人资料。')
route('w02', 2, '宋织宵那手认反刻的本领，也给事实页留一条呗。', {'page': 'overview'}, 'change', '口语要求新增人物能力事实。')
route('w02', 3, '棱脊箱现在得去坠石厅内柜找，把资料的地点换过来。', {'page': 'chapters', 'chapter_number': 12}, 'change', '要求用当前地点替换旧资料。')
route('w02', 4, '第三锤的疑问已经结清，去伏笔页把结局补齐。', {'page': 'plan'}, 'change', '要求更新伏笔收束资料，而非仅口头解释。')
route('w02', 5, '我若把左踝康复补一条，和旧事实会不会撞上？', {'page': 'materials'}, 'ask', '条件式询问新增与旧资料是否冲突，不是实际新增命令。')
route('w02', 6, '棱脊箱的地点在资料里已经改过了吗？', {'page': 'overview'}, 'ask', '询问修改是否已经发生，当前没有发出修改请求。')
route('w02', 7, pair2, {'page': 'overview'}, 'ask', '无选区及问题卡定位，泛指比较一致性的问答。')
route('w02', 8, '第21章还没动笔，把核、箱、伤势和没收的线先给我理一遍。', {'page': 'writing', 'chapter_number': 21}, 'recap', '需要多对象及开放线索的写作前回顾。')
route('w02', 9, pair2, {'page': 'writing', 'chapter_number': 21, 'selection': selections['w02']}, 'check_passage', '相同输入在写作页带完整草稿选句，检查对象明确。')
route('w02', 10, '先不聊这本，给我讲讲保温杯盖为什么总拧不开。', {'page': 'overview'}, 'out_of_scope', '与作品无关的日常物理问题。')

for wk in ('w01', 'w02'):
    wr = review['works'][wk]
    wr['same_input_groups'] = [[f'a23f-{wk}-route-07', f'a23f-{wk}-route-09']]
    wr['route_semantics'] = {
        'colloquial_change_ids': [f'a23f-{wk}-route-{n:02}' for n in (1, 2)],
        'ask_like_change_ids': [f'a23f-{wk}-route-{n:02}' for n in (5, 6)],
        'paraphrased_route_ids': [f'a23f-{wk}-route-{n:02}' for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]}
    wr['no_evidence_modes'] = {f'a23f-{wk}-no-action-03': 'not_stated', f'a23f-{wk}-no-action-04': 'contradicted'}
    assert selections[wk] in drafts[wk]
data['tasks'] = sorted(tasks, key=lambda t: (t['work'], {'action': 0, 'no_action': 1, 'route': 2}[t['suite']], t['id']))
outputs = [('tasks.json', data), ('authoring/self-review.json', review)]
if W01_ONLY:
    data['works'] = [w for w in data['works'] if w['key'] == 'w01']
    outputs = [('authoring/w01-review-package.json', data)]
for path, obj in outputs:
    (ROOT / path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({'tasks': len(tasks), 'works': len(data['works'])}))
