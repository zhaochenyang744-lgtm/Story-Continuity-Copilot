"""Lead-authored w01 question/gold literals, serialized after the completed source."""
from authoring_common import action,chapters,metadata,position
from build_materials import w01

def build(root):
    ch=chapters(root/'works/w01.md')
    assert len(ch)==20
    names=['黎见棠','许泊垣','周砚荞','宁晏菱','贺以蘅','任澄蓁','姜序弥','樊予蔚','荻瓣','榛屿','柑芽','澜苒市','莳页册','萼弧坠','卷云杯']
    work=metadata(root,'w01','未约定的星期天',names,21,'桌边的一点空处')
    facts,threads=w01()
    stale=[
      (1,8,'黎见棠把莳页册原件正式交给许泊垣保管，自己只保留完整扫描件。'),
      (2,10,'许泊垣已经把萼弧坠赠给宁晏菱，从今天起所有权归宁晏菱。'),
      (3,12,'她已经签租并搬入自己的小套间，不再住周砚荞家的客房。'),
      (4,15,'姜序弥返城后不再只在线上联系，决定从本周起每周参加一次线下散步。'),
      (5,17,'黎见棠本人给出许可，任澄蓁只公开两人选定的一张私人合照，其余合照仍不公开。'),
    ]
    missing=[
      ('贺以蘅','关系选择',6,'贺以蘅只愿与黎见棠保持同学往来，不接受朋友撮合两人谈恋爱。'),
      ('周砚荞','取消婚约原因所知',7,'周砚荞已知道，黎见棠与许泊垣取消婚约不是因为第三人。'),
      ('黎见棠','放映作伴选择',9,'黎见棠选择独自参加这次电影放映，不接受朋友另为她配伴。'),
      ('许泊垣','旅行订金处理',11,'共同旅行的订金按两人各自实际付款的数额，分别原路退回黎见棠和许泊垣的付款账户。'),
      ('樊予蔚','私人联系方式转交',16,'樊予蔚也正式向任确认：她答应不替任澄蓁向陌生人转交私人联系方式。'),
      ('宁晏菱','星期天安排',18,'宁晏菱决定接下来的星期天先陪自己的朋友，不再固定协调黎见棠与许泊垣见面。'),
    ]
    resolved=[
      (1,13,'那半张纸是许泊垣替姜序弥写给弟弟的道歉草稿，不是写给黎见棠的复合信。'),
      (2,14,'周砚荞已经邀请任澄蓁一起看展，两人当面说清此前都误以为对方不愿同行。'),
      (3,16,'那张未签名便条确是宁晏菱所写，意思是让许泊垣亲自说完自己的话，不再请她代传。'),
      (4,19,'萼弧坠内侧的短刻痕，是宁晏菱幼时与许泊垣量身高时被尺角碰出的，不是订婚日期暗记。'),
    ]
    notes=[(1,13,resolved[0][2]),(5,11,'贺以蘅已拒绝外地常驻，只考虑短期探访，何时探访仍未确定。')]
    missing_threads=[
      ('无图明信片的寄件者',4,'黎见棠收到一张无图明信片，写信人没有留下姓名或可辨认的落款。'),
      ('旧模型下的月份纸片',6,'许泊垣在旧模型底下发现一张写着另一个月份的纸片，月份与模型正面所标不同。'),
      ('陌生人喊出周的童年称呼',9,'周砚荞听到陌生人叫出自己小时候的称呼柑芽，却认不出那个人。'),
    ]
    wr={
      'characters':names[:8],
      'aliases':[
        {'name':'黎见棠','alias':'荻瓣','chapter':1,'quote':'黎见棠应声后笑了笑，解释从读书时起，周砚荞便叫她荻瓣，叫久了连她自己也习惯了。'},
        {'name':'许泊垣','alias':'榛屿','chapter':2,'quote':'她从小叫许泊垣榛屿，这个别名如今仍由熟悉的朋友沿用。'},
        {'name':'周砚荞','alias':'柑芽','chapter':3,'quote':'周砚荞的别名叫柑芽，是黎见棠与几个老朋友一直沿用的称呼。'},
      ],
      'stale_facts':[{'fact':i,'changed_chapter':n,'quote':q} for i,n,q in stale],
      'missing_facts':[{'subject':s,'predicate':p,'chapter':n,'quote':q} for s,p,n,q in missing],
      'resolved_unmarked':[{'foreshadow':i,'chapter':n,'quote':q} for i,n,q in resolved],
      'open_threads':[{'foreshadow':i,'abandonable':i in (6,7)} for i in (5,6,7,8)],
      'stale_notes':[{'foreshadow':i,'chapter':n,'quote':q} for i,n,q in notes],
      'missing_threads':[{'about':a,'planted_chapter':n,'quote':q} for a,n,q in missing_threads],
    }
    tasks=[]
    def aid(n):return f'a26f-w01-action-{n:02}'
    def rid(n):return f'a26f-w01-route-{n:02}'
    def nid(n):return f'a26f-w01-no-{n:02}'
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
        t=dict(id=aid(n),work='w01',suite='action',request=request,context={'page':page},why=why,
               paraphrased=para,vague=vague,expected_actions=actions)
        if author is not None:t['author_words']=author
        tasks.append(t)
    at(1,'贺不想被凑成一对的态度留个底；柑芽弄清取消婚约并非有旁人插进来，也另存一项。','materials',
       '贺的关系选择和周的新认知是两个独立新事实，起始库都没有记，不能混成一条关系判断。',
       [mf(1,['贺以蘅只作同学，不接受恋爱撮合']),mf(2,['周砚荞知道婚约取消与第三者无涉'])])
    at(2,'荻瓣在那回放映上对作伴的选择，替我留个底。','overview',
       '口语只指放映时的选择，需要查正文才知她拒绝配伴并独自前往。',[mf(3,['黎见棠决定一人观影，不另找同伴'])],vague=True)
    at(3,'那趟旅行预付的钱按什么办法退，帮我存下；樊替任守住私号那事，也单独记住。','chapters',
       '订金处理办法和另一人的联系方式边界分属不同事件，作者明确分别保存。',
       [mf(4,['订金各退各的实付数额，循原支付路径']),mf(5,['樊予蔚不向陌生人递任澄蓁的私号'])])
    at(4,'宁下一回星期天要先赴自己朋友的约，也不再固定替黎许排见面；这份决定写进事实。','writing',
       '正文明确了宁新的个人日程优先顺序，资料没有这项决定。',[mf(6,['宁晏菱周日先见自己的朋友，不代排黎许约见'])],para=False)
    at(5,'相册交接以后，谁收原件别还挂在荻瓣名下，照后来那次交接纠正。','materials',
       '旧事实一仍写黎保管，正文第八章已将原件交许，扫描件不等于原件。',[cf(1,['莳页册原件由许泊垣收管，黎见棠仅留扫描'])])
    at(6,'榛屿那枚银坠后来已经送出，持有人的一栏替我跟到赠送结果。','overview',
       '第十章明确赠与表姐并转移所有权，不能将看过或试戴与真正赠送混淆。',[cf(2,['萼弧坠已赠宁晏菱，所有权随之转给她'])])
    at(7,'荻瓣住处别停在借客房那会儿，改到她另租一间、已经安顿好这一状态。','chapters',
       '作者只要更新同一条居住事实，周的借桌所有权和搬家居住是不同事项。',[cf(3,['黎见棠已自租入住，结束在周砚荞家借住'])])
    at(8,'请改姜参与方式的事实，填成他已回城、每星期会同大家当面走一回。','plan',
       '返城后的固定线下散步改变了仅线上联系的旧状态，不等于赴远方邀约。',[cf(4,['姜序弥已返城，一周一回当面散步'])],para=False)
    at(9,'没写完称呼那张纸已经知道是干什么的了，别再挂着待揭。','materials',
       '作者笼统要求结线，须查到第十三章代写道歉的明确解释。',[rs(1)],vague=True)
    at(10,'周包里那两张一直没送的票，误会讲开也约上了，替我把这一支结掉。','overview',
       '第十四章周任互相确认同行意愿，票的对象和迟疑已经得到回应。',[rs(2)])
    at(11,'宁认过那张不落款的便条，也解释了意思，这条不用再吊着读者。','chapters',
       '第十六章确认书写者和亲自说话的原意，既有伏笔可以记回收。',[rs(3)])
    at(12,'把银坠短划痕那条伏笔标成已回收，章号按宁真正说明童年缘由的地方填。','materials',
       '短痕直到第十九章才由在场经历解释，不能把第十章赠物当作解谜。',[rs(4)],para=False)
    at(13,'那张没图又不署名的明信片，来处还悬着，给它单独留根线。','plan',
       '正文已有未解的寄件者疑问而资料没有此条，笼统说法需要找最早埋线位置。',
       [a('add_thread',{'about':missing_threads[0][0],'planted_chapter':4},['无图卡片无落款，寄件者身份待明','埋在第4章'],4,missing_threads[0][2])],vague=True)
    at(14,'旧模型底下那张月份对不齐的小纸片，也开成一条新线，别并到相册那边。','chapters',
       '月份纸片与其他纸物是独立悬念，最早在第六章模型底部出现。',
       [a('add_thread',{'about':missing_threads[1][0],'planted_chapter':6},['模型底纸片的月份与正面不同，缘故待明','埋在第6章'],6,missing_threads[1][2])])
    at(15,'未打开那张画的说明补一句：任想等寄画的人当面讲过再展开；原来未拆和来意不明的内容留着。','materials',
       '作者直接给追加的话，只改说明并保留原核心，不能误作打开画或结束悬线。',
       [a('edit_thread',6,['朋友寄画仍未展开，寄来的用意未明','任澄蓁等寄画人当面解释后才拆'])],para=False,author=True)
    at(16,'贺去外地那条写偏了，别还写他要长住，按他后来亲口解释重写，没定的日子别替他定。','overview',
       '目标是错误说明五，正文只否定常驻并留下短访日期未知，不能将整条线回收。',
       [a('edit_thread',5,['贺以蘅已拒绝长期外住，只考虑短访','短访日程仍没落定'],11,notes[1][2])],para=True,author=False)
    at(17,'任那张蓝纸裹着的画后面我不追写了，这一支就停在这里。','plan',
       '作者明确不再追写正文尚未展开的画，凭作者话可放弃，不伪造正文回收依据。',[a('abandon_thread',6,['已放弃'])])
    at(18,'花店门口的陌生长伞我决定不写了，把那条伏笔标成放弃。','materials',
       '长伞主人到结尾仍未知，作者明确放弃这条支线，不能误删资料。',[a('abandon_thread',7,['已放弃'])],para=False)

    def no(n,request,kind,targets,why,selection=None):
        context={'page':'writing' if selection else 'materials'}
        if selection:context.update(chapter_number=21,selection=selection)
        tasks.append(dict(id=nid(n),work='w01',suite='no_action',request=request,context=context,why=why,no_action_type=kind,request_targets=targets))
    no(1,'卷云杯现在归柑芽这点，给我补进事实库。','already_recorded',{'facts':[17],'foreshadows':[]},'事实十七已经记明杯归周且不是借放，没有新变化需要卡片。')
    no(2,'卷云杯那道裂痕的来由，给我另建一条伏笔。','already_recorded',{'facts':[],'foreshadows':[9]},'同一疑问已在伏笔九登记并回收，不该重复创建。')
    no(3,'帮我把周砚荞的生日是二月十七记进事实。','no_evidence',{'facts':[],'foreshadows':[]},'正文提到周的童年称呼却没有交代出生日期，不能把指定日期当成已有证据。')
    no(4,'花店那把深色长伞的线标成已回收，红伞套的客人已经把它领走了。','no_evidence',{'facts':[],'foreshadows':[7]},'正文明确来取的是另一把红袋短折伞，长伞仍在，作者给出的收线前提与正文相反。')
    sel='黎见棠将新买的椅子推到窄桌旁，先放下早餐，才去拉开窗帘。'
    no(5,'把这句压短一点，动作先后别换。','prose_edit',{'facts':[],'foreshadows':[]},'作者要求的是共享草稿的句式压缩，不是修改资料条目。',sel)
    no(6,'把莳页册保管人的那条事实整个删掉。','unsupported_kind',{'facts':[1],'foreshadows':[]},'作者明确要求删除事实，这一动作未在六种支持动作中，不能擅改成更新。')

    def route(n,text,page,kind,why,selection=None,chapter=None):
        c={'page':page}
        if selection:c['selection']=selection
        if chapter is not None:c['chapter_number']=chapter
        tasks.append(dict(id=rid(n),work='w01',suite='route',input=text,context=c,why=why,expected_route=kind))
    route(1,'贺不接受被撮合那份态度，帮我留在人物资料里。','materials','change','口语命令要求保存人物选择，属于新增资料。')
    route(2,'相册后来换谁管了，保管那一条照后来的交接改好。','overview','change','尽管需要检索新值，作者已经明确要求更新保管条目。')
    route(3,'月份纸片还没收到线索里，替我另开一条。','plan','change','要求给遗漏线索建立记录，是新增伏笔意图。')
    route(4,'那把无人认的长伞以后不追写了，把这支线停掉。','materials','change','明确不再追写，要求将开放线标放弃。')
    route(5,'长伞这条是不是该放弃了，留着还有用吗？','plan','ask','疑问是在寻求有依据的取舍建议，没有作出放弃决定。')
    route(6,'资料里相册这一条，现在还该算荻瓣收着吗？','materials','ask','作者问旧记法是否成立，尚未发出修改指令。')
    same='这几句有没有把旧交代拧反了？'
    route(7,same,'chapters','ask','章节页没有选中草稿，指向当前章节的问询按问作品处理。',chapter=20)
    route(8,'准备继续落笔了，把人和东西到现在哪一步给我捋顺。','writing','recap','下笔前回顾当前状态与前情，不是在要求改库。',chapter=21)
    route(9,same,'writing','check_passage','写作页已选中完整草稿句，要求对照前文检查这段。',selection=sel,chapter=21)
    route(10,'给我的手机想一张横向壁纸的配色。','overview','out_of_scope','请求与本作品人物和已写情节无关。')
    wr['same_input_groups']=[[rid(7),rid(9)]]
    wr['route_semantics']={'colloquial_change_ids':[rid(1),rid(2),rid(3),rid(4)],'ask_like_change_ids':[rid(5),rid(6)],
                           'new_action_change_ids':[rid(3),rid(4)],'thread_like_ask_ids':[rid(5)],'paraphrased_route_ids':[rid(i) for i in range(1,11)]}
    wr['no_evidence_modes']={nid(3):'not_stated',nid(4):'contradicted'}
    task_notes={
      nid(1):f'依据：起始事实17；{ch[2]["title"]}第{position(ch,2,"卷云杯已经赠给周砚荞，归周砚荞所有，不是借放在这里的物件。")}个汉字。',
      nid(2):f'依据：起始伏笔9，收于{ch[5]["title"]}；第{position(ch,5,"卷云杯是周砚荞自己意外磕坏后找人修好的，并非许泊垣损坏。")}个汉字。',
      nid(3):f'相关但不构成答案的童年称呼：{ch[9]["title"]}第{position(ch,9,missing_threads[2][2])}个汉字；日期无正文依据。',
      nid(4):f'反证：{ch[7]["title"]}第{position(ch,7,"那把深色长伞仍靠在墙边")}个汉字，区别于客人领走的短折伞。',
      nid(5):'对象为选中的共享草稿句，位置见下；不以草稿作已有事实依据。',
      nid(6):'依据为动作登记的能力范围与事实1的对象，正文考点位置不适用。',
    }
    return work,facts,threads,tasks,wr,task_notes
