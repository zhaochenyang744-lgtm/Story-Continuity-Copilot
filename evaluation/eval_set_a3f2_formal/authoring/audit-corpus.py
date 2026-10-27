"""Offline lexical audits; excludes forbidden directories before recursive reads."""
from pathlib import Path
from difflib import SequenceMatcher
import hashlib
import json
import unicodedata

REPO = Path(__file__).resolve().parents[3]
EXCLUDED = ['eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring',
            'eval_set_a26_formal', 'eval_set_a2s6_formal']
NEW = ['eval_set_a3f2_formal', 'eval_set_a3s2_formal']
CANDIDATES = {
    'eval_set_a3f2_formal': ('莘砚棠 棠尺 郗望岑 夜衡 贲弥舟 弦客 栾素觿 褚闻荇 鄢靖纾 衡澹璆 逄澜荠 郦灼瑗 汲辞嵩 蔚衡京 廉昴台 砺玄殿 南缜圃 翼纹候筒 硃脊漏舟 缄朔玉筹 '
                          '郜缃遥 阔时客 班聿岐 炬耳人 竺芩曜 缄帆者 邬曼洄 阴俞旻 亓宸苓 祁梵棱 喻聆峭 冉栖遐 甄洛蘩 纭隙双星 岑弧返港 黛弦航庭 迟汐对钟 刈光指匣 返龄契盒').split(),
    'eval_set_a3s2_formal': '苗珣翳 翳羽 费蘅墟 蘅灯 蒯泠茉 茉背 佘珂窈 乐阙榛 卜遐樾 邬昭粼 鄄玟羽 程嵩芮 嵇汀柊 蚀穗天庭 镜蛹原 煦甲崖 霁蛾令壳 季蛾'.split(),
}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm(s):
    return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))


def inputs(o):
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in {'input', 'question', 'request'} and isinstance(v, str):
                out.append(norm(v))
            elif isinstance(v, (dict, list)):
                out.extend(inputs(v))
    elif isinstance(o, list):
        for x in o:
            out.extend(inputs(x))
    return out


def main():
    eval_root = REPO / 'evaluation'
    directories = [p for p in sorted(eval_root.iterdir()) if p.is_dir() and
                   p.name.startswith('eval_set') and p.name not in EXCLUDED + NEW]
    source_hashes, grouped, corpus_hashes, overlap = {}, {}, {}, {s: [] for s in NEW}
    for d in directories:
        task = d / 'tasks.json'
        if task.is_file():
            rel = task.relative_to(REPO).as_posix()
            source_hashes[rel] = sha(task)
            grouped[rel] = sorted(set(inputs(json.loads(task.read_text(encoding='utf-8-sig')))))
        for p in sorted(d.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in {'.md', '.json', '.py', '.sha256', '.jsonl', '.txt'} or set(EXCLUDED).intersection(p.parts):
                continue
            rel = p.relative_to(REPO).as_posix()
            text = p.read_text(encoding='utf-8-sig')
            corpus_hashes[rel] = sha(p)
            for sid, names in CANDIDATES.items():
                for n in names:
                    if n in text:
                        overlap[sid].append({'name': n, 'file': rel})
    old = sorted({v for vs in grouped.values() for v in vs})
    for sid in NEW:
        root = eval_root / sid
        payload = {
            'excluded_directories': EXCLUDED,
            'normalized_inputs': old,
            'normalized_inputs_by_source': grouped,
            'source_hashes': source_hashes,
            'names_corpus_sha256': corpus_hashes,
            'candidate_names_sha256': hashlib.sha256(json.dumps(sorted(CANDIDATES[sid]), ensure_ascii=False).encode()).hexdigest(),
            'names_overlap': len(overlap[sid]),
            'reference_counts': {'source_files': len(source_hashes), 'normalized_inputs': len(old), 'names_text_files': len(corpus_hashes)},
        }
        (root / 'authoring/novelty-reference.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps({'set_id': sid, **payload['reference_counts'], 'names': len(CANDIDATES[sid]), 'names_overlap': len(overlap[sid])}))
    if any(overlap.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
