"""Serialize the manually designed starting-material draft; contains no prose generator."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent

FACTS = [
    ('static_canon', '蒋珞岑', '别名', '矩鸢', 1),
    ('static_canon', '褚霁禾', '别名', '霜芥', 1),
    ('static_canon', '厉闻绡', '别名', '砂鹭', 1),
    ('static_canon', '范筠策', '别名', '斜栅', 1),
    ('dynamic_state', '蒋珞岑', '组内职责', '制样员，负责制作试样', 1),
    ('dynamic_state', '褚霁禾', '工作房间', '迟测间', 1),
    ('dynamic_state', '灰芽膜', '保管人', '厉闻绡', 2),
    ('dynamic_state', '范筠策', '试次次序', '先看双瓣样', 2),
    ('dynamic_state', '卫砚翎', '组内身份', '报告统筹', 3),
    ('static_canon', '蒋珞岑', '书写习惯', '用左手写标签', 1),
    ('static_canon', '褚霁禾', '随身本', '青布封面', 1),
    ('static_canon', '厉闻绡', '午后习惯', '午饭后走楼梯', 2),
    ('static_canon', '范筠策', '饮品偏好', '只喝温水', 2),
    ('dynamic_state', '黎映珂', '职责', '安排研究日程', 1),
    ('dynamic_state', '郝宥弦', '座位', '靠北窗', 2),
    ('static_canon', '翁素缦', '研究方向', '比较颜色的时间差', 3),
    ('static_canon', '昼纹片', '形状', '方形', 3),
    ('static_canon', '暮纹片', '形状', '圆形', 3),
    ('dynamic_state', '岔脊盒', '封装', '盒盖缠着白线', 3),
    ('static_canon', '双瓣样', '结构', '两片可以分离', 2),
    ('static_canon', '灰芽膜', '外观', '边缘呈灰绿', 2),
    ('static_canon', '弧脉条', '外观', '有一道弯曲暗纹', 3),
    ('static_canon', '澄络材料实验中心', '例会时间', '午后举行', 1),
    ('static_canon', '本轮研究', '结果认定原则', '不把一次颜色变化当作可重复结果', 4),
    ('static_canon', '黎映珂', '告示写法', '不用红字催人', 4),
]

THREADS = [
    ('双瓣样三点痕', '双瓣样上出现三个紫色小点，颜色为何在那几个位置留下、是否自行移动，还没有找到可信的解释。', 'developing', 2),
    ('空架低鸣', '空着的架子附近仍传来低鸣，几个人都听见过，声音究竟来自哪里尚未查明。', 'planted', 3),
    ('灰芽膜空白角', '灰芽膜的一角迟迟不显色，和其他区域的表现不同，还不清楚是材料本身还是别的原因。', 'planted', 2),
    ('暮纹片慢退色', '暮纹片的颜色退得比昼纹片慢，差异的来源尚不明确，需要保留这条疑问。', 'developing', 3),
    ('夜蓝反光', '桌边夜里出现的蓝影来自窗帘的反射，移开窗帘后蓝影消失，原先不明的来源已经查清。', 'resolved', 1, 4),
    ('昼纹片离室', '昼纹片已经离开迟测间，带走者尚不清楚，外面看到的颜色和室内是否相同仍待核实。', 'planted', 3),
    ('岔脊盒夹层', '白线封着的岔脊盒是否有夹层还未查明，盒内可能藏着旧样页，但尚无人看见里面的情形。', 'developing', 3),
    ('弧脉条斜纹', '条体在暗处也自行发光，斜纹可能随内光移动，准备比较斜纹的来源及变化方式。', 'planned', 3),
    ('缺角目录', '目录纸被去掉一角，缺失的位置原来写着什么还不知道，这部分是否与旧样有关也未证实。', 'planted', 6),
    ('旧色谱重建', '上一轮曾计划重新拼出旧色谱，后来已经明确不再追索，这条研究旁枝决定放弃。', 'abandoned', 2),
]

def save(rel, value):
    (ROOT / rel).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

def main():
    facts = [dict(zip(('memory_type', 'subject', 'predicate', 'value', 'chapter'), row)) for row in FACTS]
    threads = []
    for row in THREADS:
        item = dict(zip(('title', 'description', 'status', 'planted_chapter'), row[:4]))
        if len(row) == 5:
            item['resolved_chapter'] = row[4]
        threads.append(item)
    save('materials/w01-facts.json', facts)
    save('materials/w01-foreshadows.json', threads)
    print(json.dumps({'facts': len(facts), 'foreshadows': len(threads)}, sort_keys=True))

if __name__ == '__main__':
    main()
