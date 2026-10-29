"""Lead-authored w02 question/gold literals, based on its completed canonical source."""
from authoring_common import action,chapters,metadata,position
from build_materials import w02

def build(root):
    ch=chapters(root/'works/w02.md')
    assert len(ch)==20
    names=['柴予萱','陆照苒','柴照棠','杨映荃','陆问杉','方若荻','柴闻序','陆筱砚','蓼芽','黛团','杉栖','筠洄市','禾角册','瓷棉熊','雾纹包','予萱','照苒']
    work=metadata(root,'w02','后来相认的人',names,21,'窗边的下午')
    facts,threads=w02()
    stale=[
      (1,8,'杨映荃将禾角册交到柴予萱手里，以后谁想看原件，包括她自己，都要向女儿借。'),
      (2,10,'两周一次，愿来就来，没来的不追问，也别凑齐八个人才开始。'),
      (3,12,'照苒这才将自己的选择讲完整：“我愿意让你们两位知道，大学同住过的你，还有一直联络的老同事，就只选你们。”'),
      (4,15,'不用照我的样子装。我要把雾纹包送给你，不是借给你，往后它归你。'),
      (5,17,'“以后你可以直接给我发消息，不用固定经过予萱，我会自己答。”陆照苒对柴照棠说。'),
    ]
    missing=[
      ('柴予萱','单独见面及称呼选择',6,'“我愿意和你单独见面，可我还没准备好改叫妈妈。”柴予萱说完，先屏住一口气。'),
      ('陆问杉','替代者认识',7,'“我听懂了。你不愿意被当成照苒的替代，以后我先问你，不照她的样子来。”陆问杉在电话那头说。'),
      ('陆筱砚','朋友往来选择',9,'“我想和你单独做朋友，不替姐姐打听你的事，也不替你问她们。”陆筱砚说。'),
      ('杨映荃','回礼规则',11,'杨映荃点头，终于亲口说：“以后两家送东西不用照同样价钱回，我也不拿别人给过多少来算。”'),
      ('柴闻序','代写回信决定',16,'以后你们写给父母的回信，我不再代写；想让我听，我在，但怎样说由你们自己来。'),
      ('方若荻','姓名选择认可',18,'“你就继续叫柴予萱，不用改姓，我接受，也会一直照这个名字叫你。”'),
    ]
    resolved=[
      (1,13,'“我写这两封信，是想请你们了解我年轻时的生活。”方若荻说。'),
      (2,14,'那格留给你选一张成年后的照片，不是放抱错证明，哪张由你自己定。'),
      (3,16,'我躲这个终点，是年轻时在这里和我父亲闹过不和，不是因为你们抱错的事。'),
      (4,19,'方若荻说：“瓷棉熊这道线是你幼时自己学着缝的，我就在旁边，不是为另一个孩子改名。”'),
    ]
    notes=[
      (1,13,'给你的不是要你搬回陆家，给照苒的也不是让她让出谁的位置。'),
      (5,11,'“箱里不是当年的身份文件，是我父亲的旧工具，还有一封给我的私人遗信。”陆问杉说，'),
    ]
    missing_threads=[
      ('相册背页陌生缩写的书写者',4,'柴予萱在禾角册背页发现一组陌生缩写，谁写的、代表什么，她都不认识。'),
      ('无署名生日录音的来源',6,'陆照苒收到的生日录音没有署名，谁录的、为何送来，眼下都不清楚。'),
      ('杨私存河岸照片的来历',9,'杨映荃自己保存着一张河岸照片，在今天以前，家里其他人都没见过。'),
    ]
    wr={
      'characters':names[:8],
      'aliases':[
        {'name':'柴予萱','alias':'蓼芽','chapter':1,'quote':'家人从小叫柴予萱蓼芽，这个昵称一直指的是她。'},
        {'name':'陆照苒','alias':'黛团','chapter':2,'quote':'黛团是朋友给陆照苒起的昵称，家里从前很少这样叫她。'},
        {'name':'柴闻序','alias':'杉栖','chapter':3,'quote':'朋友叫柴闻序杉栖，只是沿用的昵称。'},
      ],
      'stale_facts':[{'fact':i,'changed_chapter':n,'quote':q} for i,n,q in stale],
      'missing_facts':[{'subject':s,'predicate':p,'chapter':n,'quote':q} for s,p,n,q in missing],
      'resolved_unmarked':[{'foreshadow':i,'chapter':n,'quote':q} for i,n,q in resolved],
      'open_threads':[{'foreshadow':i,'abandonable':i in (6,7)} for i in (5,6,7,8)],
      'stale_notes':[{'foreshadow':i,'chapter':n,'quote':q} for i,n,q in notes],
      'missing_threads':[{'about':a,'planted_chapter':n,'quote':q} for a,n,q in missing_threads],
    }
    tasks=[]
    def aid(n):return f'a26f-w02-action-{n:02}'
    def rid(n):return f'a26f-w02-route-{n:02}'
    def nid(n):return f'a26f-w02-no-{n:02}'
    def a(kind,target,points,n=None,q=None):return action(ch,kind,target,points,n,q)
    def mf(i,points):
        s,p,n,q=missing[i-1]
        return a('add_fact',{'subject':s,'predicate':p},points,n,q)
    def cf(i,points):
        target,n,q=stale[i-1]
        return a('change_fact',target,points,n,q)
    def rs(i):
        target,n,q=resolved[i-1]
        return a('resolve_thread',target,['已回收',f'收在第{n}章'],n,q)
    def at(n,request,page,why,actions,para=True,vague=False,author=None):
        t=dict(id=aid(n),work='w02',suite='action',request=request,context={'page':page},why=why,
               paraphrased=para,vague=vague,expected_actions=actions)
        if author is not None:t['author_words']=author
        tasks.append(t)
    at(1,'柴予萱愿单独见方但不承诺改口，帮我留底；陆筱砚想同柴闻序自己作朋友、不代探听，也另存一项。','overview',
       '柴对见母亲的选择与妹妹对另一人的朋友往来意愿分属两个事件，作者明确分别保存。',
       [mf(1,['柴予萱愿单独见方若荻，不承诺改称妈']),mf(3,['陆筱砚愿与柴闻序独立作朋友，不替双方探私事'])])
    at(2,'方对保留原名那件事的表态，替我存下来。','materials',
       '请求只概述姓名表态，需要查到第十八章方亲口认可保留原名，并非给人物重命名。',[mf(6,['方若荻接受柴予萱沿用原名，不改姓'])],vague=True)
    at(3,'陆问杉终于明白不能把予萱套成另一个女儿，这层认识写下；杨关于礼物不必同价回的决定也另记。','chapters',
       '一处是陆的新认知，另一处是杨的回礼规则，主体和事件均不同，不能合成一项。',
       [mf(2,['陆问杉已知柴予萱拒被当成照苒的代替']),mf(4,['杨映荃认可两家送礼无需等价回报'])])
    at(4,'杉栖已决定不替两位妹妹拟给父母的回话了，这项记进事实，同时留住他仍愿意听的意思。','writing',
       '同一决定包括停止代写和保留倾听支持两方面，仍是一条事实而非两项动作。',
       [mf(5,['柴闻序不替两位写回信，仍愿倾听'])],para=False)
    at(5,'相册原件如今谁收着，别仍记杨那里，照正式交出去以后的安排更新。','materials',
       '第八章将原件交柴予萱，连杨自己也须向女儿借，保管人与原来不同。',
       [cf(1,['禾角册原件归柴予萱收管，杨映荃看也须借'])])
    e6=cf(2,['改为隔周一次，自主决定到场','不必八人齐聚，缺席不盘问'])
    e6['evidence_chapters'].append(ch[10]['title'])
    e6['evidence_quotes'].append('照苒和筱砚先答应，闻序说自己照办，两位父亲与两位母亲也各自说了好。')
    at(6,'两家见面的频率别停在每周凑齐八人的时候，跟到后来大家都点头的办法。','overview',
       '频率、参加自由及缺席处理属于同一见面安排的边界，只更新原事实二。',[e6])
    e7=cf(3,['仅陆照苒亲选的两位老友得知','不向公众开放，也不准朋友继续转传'])
    e7['evidence_chapters'].append(ch[12]['title'])
    e7['evidence_quotes'].append('“我不想对公众讲，不放到网上，也不让这件事从你们这里传给其他人。”陆照苒补上一句。')
    at(7,'黛团后来亲自挑了两位老友告知，公开那一条跟着改好，别替她放宽到其他人。','chapters',
       '第十二章只授权两位本人选定的老友，不能把有限告知等同于公开传播。',[e7])
    e8=cf(4,['雾纹包已赠陆筱砚，不是借用','方若荻自存全部照片，未随赠包转送'])
    e8['evidence_chapters'].append(ch[15]['title'])
    e8['evidence_quotes'].append('照片已经全部取出来，仍由我自己收着，不随包送走。')
    at(8,'雾纹包的持有人事实改到筱砚受赠后的状态，方留下照片、不随包送走这层也写清。','plan',
       '包的受赠人与赠与范围是同一交接事实的两方面，照片没有随包给女儿。',[e8],para=False)
    at(9,'那两封信为什么一直留着，后来已经讲开也让她们看过了，别还挂着等答案。','materials',
       '笼统要求结掉双份信的用意之谜，必须检索第十三章的当面解释。',[rs(1)],vague=True)
    at(10,'相册里那格留白的伏笔标成已回收，收在她自己挑照片放进去的那一回。','overview',
       '空格用途和照片选择在第十四章落实，不能与背页缩写这条未记线混淆。',[rs(2)],para=False)
    e11=rs(3)
    e11['evidence_chapters'].append(ch[16]['title'])
    e11['evidence_quotes'].append('两位女儿各自与他走过这一段，回避终点的缘由已经由柴照棠亲口讲清；')
    at(11,'父亲回避那个公交终点的事已经对两位女儿讲明，也分别走过了，这条收束。','chapters',
       '第十六章说清回避来自与自己父亲的旧日不和，且两个女儿均已走过该处。',[e11])
    e12=rs(4)
    e12['evidence_chapters'].append(ch[19]['title'])
    e12['evidence_quotes'].append('“我想起来了，是我自己缝的，后来还不让你拆。”陆照苒望着方若荻说。')
    at(12,'布熊背后那道改线已经由当事人认出来了，把这根线结了。','plan',
       '第十九章母亲在场说明与陆本人想起相互印证，布熊针迹的谜已经收束。',[e12])
    at(13,'相册背页那组谁也认不出的缩写，加一条伏笔追它的书写者，不要记成空相格的事。','materials',
       '背页缩写从第四章起未解且起始伏笔遗漏，与已登记的空相格不是同一条线。',
       [a('add_thread',{'about':missing_threads[0][0],'planted_chapter':4},['相册背页有陌生缩写，写者尚待确认','埋在第4章'],4,missing_threads[0][2])],para=False)
    at(14,'那段没人落款的生日录音也替我单开根线，来路先悬着。','overview',
       '口语概述未署名录音，需要查最早第六章，不能误认成筱砚自己未发的语音。',
       [a('add_thread',{'about':missing_threads[1][0],'planted_chapter':6},['生日音频未署名，制作人及用意未明','埋在第6章'],6,missing_threads[1][2])],vague=True)
    at(15,'筱砚未发语音的说明添一句：她想先誊成文字再决定要不要发；原先未发送、未放给人听的内容别删。','materials',
       '作者直接提供追加计划，须保留既有未发送和未外放信息，只改说明。',
       [a('edit_thread',6,['语音未外发外放，录的内容尚未说清','陆筱砚先转写，再决定是否发送'])],para=False,author=True)
    e16=a('edit_thread',5,['内存父亲旧工具和私人信，不是身份文件','私信仍封着，尚未读'],11,notes[1][2])
    e16['evidence_chapters'].append(ch[11]['title'])
    e16['evidence_quotes'].append('信没拆，我现在也不想拆。')
    at(16,'旧工具箱那段说错了，依陆后来亲口讲的重写，私信还封着这一层别丢。','chapters',
       '按正文推翻身份文件误记，并保留未拆私信的开放部分，不能误标整线已收。',[e16],author=False)
    at(17,'筱砚那条录好没发的语音，后面我不展开了，整支停写。','plan',
       '作者明确决定不再展开未听未发的语音线，符合可放弃目标六。',[a('abandon_thread',6,['已放弃'])])
    at(18,'远方看房间那条我不追了，把柴闻序这支伏笔标成放弃。','materials',
       '房间和朋友的关系至结尾未明，作者已决定放弃，不能将弃线改成删除。',[a('abandon_thread',7,['已放弃'])],para=False)

    def no(n,request,kind,targets,why,selection=None):
        c={'page':'writing' if selection else 'materials'}
        if selection:c.update(chapter_number=21,selection=selection)
        tasks.append(dict(id=nid(n),work='w02',suite='no_action',request=request,context=c,why=why,no_action_type=kind,request_targets=targets))
    no(1,'杉栖就是柴闻序这一层对应，也替我收进事实库。','already_recorded',{'facts':[16],'foreshadows':[]},'事实十六已经保存本名与昵称对应，不能重复创建。')
    no(2,'禾角册留着那一格没放照片的事，新增成一条伏笔。','already_recorded',{'facts':[],'foreshadows':[2]},'空相格已作为伏笔二存在，新增请求没有授权另改其状态。')
    no(3,'把柴闻序的生日是三月二十六存成事实。','no_evidence',{'facts':[],'foreshadows':[]},'正文给过年龄却未交代出生月日，不能从年龄编出指定日期。')
    no(4,'第十一章工具箱不是都打开了吗，身份材料的来历也讲完了，把这条线标成已回收。','no_evidence',{'facts':[],'foreshadows':[5]},'正文明确箱内不是身份文件且私人遗信仍未拆，打开外层不支持整线回收。')
    sel='陆筱砚将雾纹包挂在椅背，取出里面属于自己的薄外套。'
    no(5,'把这里第一句写得再利落些，拿出东西的动作不要漏。','prose_edit',{'facts':[],'foreshadows':[]},'要求改选中草稿的行文，未要求改包的资料归属。',sel)
    no(6,'把互换童年房间那条伏笔记录整个删除。','unsupported_kind',{'facts':[],'foreshadows':[10]},'删除伏笔是未支持动作，不能因它已放弃便擅自执行删除。')

    def route(n,text,page,kind,why,selection=None,chapter=None):
        c={'page':page}
        if selection:c['selection']=selection
        if chapter is not None:c['chapter_number']=chapter
        tasks.append(dict(id=rid(n),work='w02',suite='route',input=text,context=c,why=why,expected_route=kind))
    route(1,'两家的见面安排别按最早那套记了，换成后来一起商量好的。','materials','change','明确要求改现有安排的记录，需要查正文但意图已是更新。')
    route(2,'筱砚想自己同柴闻序往来的选择，也给她留在资料里。','overview','change','作者要求新增人物选择，口语表达不等于只问作品。')
    route(3,'工具箱那条说明照陆问杉后来的解释纠正，封着的信仍留未知。','materials','change','直接要求修正伏笔说明，并保留未解部分。')
    route(4,'远方那个房间我不再展开了，替我把这一支停写。','plan','change','作者已作不再追写的决定，要求标放弃。')
    route(5,'筱砚那段还没发的语音，是不是不值得写下去了？','plan','ask','仍在询问取舍，没有作出弃线决定。')
    route(6,'包那项是不是该换成筱砚了？先跟我说说前文的依据。','materials','ask','询问记法是否应该改变并索要依据，尚未授权改条目。')
    same='这儿的说法跟以前交代的是不是串了？'
    route(7,same,'chapters','ask','章节页没有选中草稿，问当前章节与前情的关系按问作品处理。',chapter=20)
    route(8,'下一段要开写了，替我捋捋两家现有约定，还有哪些旧事依旧压着。','writing','recap','下笔前梳理状态和未解线，属于写前回顾。',chapter=21)
    route(9,same,'writing','check_passage','同一句输入在写作页有完整选句，意图是检查选段与前文是否一致。',selection=sel,chapter=21)
    route(10,'请替我算出六百七十三乘十九。','overview','out_of_scope','纯计算请求与这部作品无关。')
    wr['same_input_groups']=[[rid(7),rid(9)]]
    wr['route_semantics']={'colloquial_change_ids':[rid(1),rid(2),rid(4)],'ask_like_change_ids':[rid(5),rid(6)],
                           'new_action_change_ids':[rid(3),rid(4)],'thread_like_ask_ids':[rid(5)],'paraphrased_route_ids':[rid(i) for i in range(1,11)]}
    wr['no_evidence_modes']={nid(3):'not_stated',nid(4):'contradicted'}
    task_notes={
      nid(1):f'依据起始事实16及{ch[3]["title"]}第{position(ch,3,wr["aliases"][2]["quote"])}个汉字。',
      nid(2):f'起始伏笔2已有此对象；最早{ch[2]["title"]}第{position(ch,2,"禾角册里空出的位置没有照片，杨映荃暂时未说准备放什么。")}个汉字。',
      nid(3):f'相关年龄为{ch[3]["title"]}第{position(ch,3,"柴闻序三十一岁，是柴照棠与杨映荃的长子。")}个汉字；没有出生月日依据。',
      nid(4):f'反证{ch[11]["title"]}第{position(ch,11,notes[1][2])}个汉字，及第{position(ch,11,"信没拆，我现在也不想拆。")}个汉字。',
      nid(5):'定位为共享草稿完整句，章内位置见下；不把草稿衣物当成已完成正文的新事实。',
      nid(6):'依据动作支持范围与既有伏笔10，正文位置不适用于删除能力判定。',
    }
    return work,facts,threads,tasks,wr,task_notes
