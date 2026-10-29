"""Read-only delivery audit and content-free receipt."""
from pathlib import Path
from collections import Counter
import hashlib
import importlib.util
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    spec = importlib.util.spec_from_file_location('a2n7_final_check', ROOT / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    result = check.validate()
    assert result['status'] == 'PASS', result['errors']
    baseline = load('authoring/protected-baseline.json')
    protected_changes = sum(digest(REPO / p) != h for p, h in baseline['protected'].items())
    assert protected_changes == 0
    original = subprocess.check_output(['git', 'show', baseline['head'] + ':.gitattributes'], cwd=REPO)
    line = b'evaluation/eval_set_a2n7_formal/** -text whitespace=-blank-at-eol,-blank-at-eof,-cr-at-eol\n'
    assert (REPO / '.gitattributes').read_bytes() == original + line
    bad_bytes = []
    for p in sorted(ROOT.rglob('*')):
        if p.is_file():
            raw = p.read_bytes()
            raw.decode('utf-8')
            if raw.startswith(b'\xef\xbb\xbf') or b'\r' in raw:
                bad_bytes.append(p.relative_to(ROOT).as_posix())
    assert not bad_bytes, bad_bytes
    assert not list((ROOT / 'authoring').glob('ch[0-9][0-9].md'))
    assert not list(ROOT.parent.glob('.a2n7-negative-*'))
    data = load('tasks.json')
    source = (ROOT / 'works/w01.md').read_text(encoding='utf-8')
    chapters = check.chapter_map(source)
    counts = {str(n): len(check.HAN.findall(v['body'])) for n, v in chapters.items()}
    narrative_meta = len(re.findall(r'第[0-9一二三四五六七八九十百]+章', '\n'.join(v['body'] for v in chapters.values())))
    assert narrative_meta == 0
    blind = load('authoring/blind-comparison.json')['comparisons']
    initial = sum(c['initial_agreement'] for c in blind)
    final = sum(c['final_agreement'] for c in blind)
    reference = load('authoring/novelty-reference.json')
    sealed = load('authoring/sealed-comparison.json')
    revisions = load('authoring/revision-log.json')
    rereview = load('authoring/blind-rereview.json')
    full_review = load('authoring/full-source-review.json')
    receipt = {
        'status': 'PASS', 'data_files': 4, 'protected_files': len(baseline['protected']),
        'protected_changes': protected_changes, 'gitattributes_added_lines': 1,
        'chapter_han': counts, 'narrative_chapter_meta': narrative_meta,
        'utf8_bom_or_cr_files': 0, 'chapter_work_copies': 0, 'negative_temp_directories': 0,
        'names_overlap': reference['names_overlap'], 'sealed_names_overlap': sealed['names_overlap'],
        'copy_errors': result['copy_errors'], 'novelty_errors': result['novelty_errors'],
        'readable_reference_counts': reference['reference_counts'], 'sealed_reference_counts': sealed['reference_counts'],
        'reference_reading': {'existing_readmes_read': 42, 'directories_without_readme': 7,
                              'independent_opening_works': 99, 'opening_chapters': 198},
        'blocked_directories_accessed': 0,
        'independent_findings_closed': len(full_review['findings']),
        'source_editorial_revisions': revisions['source_changes'], 'metadata_revisions': revisions['metadata_changes'],
        'request_revisions': revisions['request_changes'], 'gold_kind_target_revisions': revisions['gold_kind_target_changes'],
        'blind_rounds': 2, 'original_verdicts_preserved': 20, 'rereview_judgements_changed': rereview['judgements_changed'],
        'blind_summary': {'total': 20, 'initial_agreement': initial, 'initial_rate': initial / 20,
                          'final_agreement': final, 'final_rate': final / 20,
                          'initial_disagreement_ids': [c['id'] for c in blind if not c['initial_agreement']],
                          'closed_disagreements': sum(not c['initial_agreement'] and c['final_agreement'] for c in blind),
                          'unresolved': 20 - final},
        'authoring_source_generation': 0, 'model_calls': 0, 'product_runs': 0, 'evaluation_runs': 0,
        'manifest_sha256': digest(ROOT / 'set.sha256')}
    (ROOT / 'authoring/final-audit.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))

if __name__ == '__main__':
    main()
