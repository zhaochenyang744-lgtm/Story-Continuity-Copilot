"""Write the authorized content-free delivery after the one local commit."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent
REPORT = Path('C:/Users/赵晨阳/Desktop/v2.1任务/34-交付报告.md')

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO).decode('utf-8').strip()

def main():
    check = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'evaluation.eval_set_a2n7_formal.check'],
                           cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    assert check.returncode == 0, check.stdout
    result = json.loads(check.stdout)
    negative = load('authoring/negative-tests.json')
    audit = load('authoring/final-audit.json')
    assert negative['status'] == 'PASS' and audit['status'] == 'PASS'
    assert git('branch', '--show-current') == 'eval/a2-7-authoring'
    assert git('log', '-1', '--format=%B') == 'eval: author and freeze the A2 supplementary set'
    assert not git('status', '--porcelain')
    work = result['works']['w01']
    text = '\n'.join([
        '# 34 交付报告', '',
        '- 分支：`eval/a2-7-authoring`。',
        '- 提交：`' + git('rev-parse', 'HEAD') + '`。',
        '- 本地提交 1；推送 0；合并 0；切分支 0；其他 worktree 访问 0。',
        '- 作品 1；题目 20；改资料动作 8；不该改 12；分流 0；注入 0。',
        '- 模型接口调用 0；产品运行 0；评测运行 0。以下 PASS 均为静态、离线检查结果。', '',
        '## 封存清单', '', '```text', (ROOT / 'set.sha256').read_text(encoding='utf-8').rstrip(), '```', '',
        '`set.sha256` SHA-256：`' + sha(ROOT / 'set.sha256') + '`。', '',
        '## 数量与分布', '',
        '```json', json.dumps(work, ensure_ascii=False, sort_keys=True, indent=2), '```', '',
        '## 独立复判', '',
        '```json', json.dumps(result['independent_review'], ensure_ascii=False, sort_keys=True, indent=2), '```', '',
        '全部20题的初判和最终一致率按下列记录计算；仅列编号和计数。', '',
        '```json', json.dumps(audit['blind_summary'], ensure_ascii=False, sort_keys=True, indent=2), '```', '',
        '## 排重与最终审计', '',
        '```json', json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2), '```', '',
        '## 检查器完整输出', '', '```json', check.stdout.strip(), '```', '',
        '## 负向测试', '',
        '```json', json.dumps(negative, ensure_ascii=False, sort_keys=True, indent=2), '```', '',
        '## 规则解释', '',
        '1. 补充十二与任务34替换任务32的规模和题型：1部12章、12道不该改、8道动作；每题只要求一处改动。多动作题0，分流0，注入0。',
        '2. 第六套动作题的口语比例9/18折算到8题，最低4；模糊比例2/18向上取整为1，且至少1道属于新动作。',
        '3. 补充十二允许最后两道从edit_thread或abandon_thread中选；任务34进一步规定各1道，采用较具体约束。唯一edit_thread采用按正文纠正说明；任务32要求两种模式各1道的数量不适用。',
        '4. 外号最少4人；资料与正文均记录对应。already_recorded外号题和change_fact外号题分别验证。',
        '5. 前提相反题的why包含反驳原句，另用premise_evidence绑定章节和引用；上述字段均为检查和复核元数据。',
        '6. 盲判使用不透明随机编号。先保留全部原判，再做金标比较；初判分歧逐项保存和关闭。',
        '7. 依据位置继承A1c第2节：至少一半在1500字后，同时至少三分之一唯一依据在2500字后。',
        '8. 三个封存目录仅由程序比较专名与输入新颖性，保存计数和哈希；三个禁止访问的A3目录在遍历前排除。',
        '9. SPEC与任务34的核心数量及补测范围无冲突。任务32的旧规模、复合动作和分流分布按任务34覆盖。',
        '10. 本交付只完成出题与封存；正式补测和发布版本回归尚未运行。', ''
    ])
    data = load('tasks.json')
    forbidden = list(data['works'][0]['names']) + [data['works'][0]['title']]
    for t in data['tasks']:
        forbidden += [t['request'], t['why']]
        for a in t.get('expected_actions', []):
            forbidden += a['evidence_quotes']
            # Program points are rule strings and intentionally appear in structural fields.
            forbidden += [p for p in a['after_points'] if p != '已放弃' and p != '已回收' and not re.fullmatch(r'收在第[0-9]+章', p)]
    forbidden += [p for p in data['works'][0]['shared_draft']['body'].split('\n') if len(p.strip()) >= 20]
    assert not any(s and s in text for s in forbidden), 'report_content_leak'
    REPORT.write_text(text, encoding='utf-8', newline='\n')
    print(json.dumps({'report_written': True, 'report_bytes': REPORT.stat().st_size,
                      'report_sha256': sha(REPORT), 'leak_matches': 0}, sort_keys=True))

if __name__ == '__main__':
    main()
