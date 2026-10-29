"""Count and locate source features, without creating or rewriting any prose."""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import re

REPO = Path(__file__).resolve().parents[3]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')

def main():
    roots = [REPO/'evaluation'/n for n in ('eval_set_a26_formal','eval_set_a2s6_formal')]
    result = {'works': {}, 'duplicate_paragraph_groups': [], 'duplicate_sentence_groups': [], 'narrative_meta': []}
    paragraphs, sentences = defaultdict(list), defaultdict(list)
    for root in roots:
        for p in sorted((root/'works').glob('*.md')):
            text = p.read_text(encoding='utf-8')
            starts = list(re.finditer(r'^# 第([1-9][0-9]*)章 ([^\r\n]+)$', text, re.M))
            counts = {}
            for i, m in enumerate(starts):
                n = int(m[1])
                body = text[m.end():starts[i+1].start() if i+1<len(starts) else len(text)]
                counts[n] = len(HAN.findall(body))
                label = f'{root.name}/{p.name}:{n}'
                for block in re.split(r'\n\s*\n', body):
                    clean = ''.join(HAN.findall(block))
                    if len(clean) >= 40:
                        paragraphs[clean].append(label)
                for sentence in re.split(r'[。！？\n]', body):
                    clean = ''.join(HAN.findall(sentence))
                    if len(clean) >= 35:
                        sentences[clean].append(label)
                for pattern in (r'第[0-9一二三四五六七八九十百]+章',r'题集|考点|金标|评测|标准答案|self.review'):
                    for hit in re.finditer(pattern, body):
                        result['narrative_meta'].append({'work':label,'han_position':len(HAN.findall(body[:hit.start()]))+1})
            result['works'][f'{root.name}/{p.name}'] = {'chapters':len(starts),'chapter_lengths':counts,
                'total_han':sum(counts.values()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    for values, key in ((paragraphs,'duplicate_paragraph_groups'),(sentences,'duplicate_sentence_groups')):
        result[key] = [{'occurrences':len(loc),'locations':loc,'han':len(s)} for s,loc in values.items() if len(loc)>1]
    out = roots[0]/'authoring/prose-audit.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    main()
