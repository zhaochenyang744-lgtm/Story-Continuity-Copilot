"""Serialize the lead-authored per-work literals; never composes source prose."""
from pathlib import Path
import sys
from authoring_common import merge_proof,save,write_self_review
from build_w01 import build as build_w01

ROOT=Path(__file__).resolve().parent.parent

def main():
    builders=[build_w01]
    partial=sys.argv[1:]==['--partial-w01']
    if not partial:
        from build_w02 import build as build_w02
        builders.append(build_w02)
    works,tasks,review,notes=[],[],{},{}
    for builder in builders:
        w,f,t,ts,wr,ns=builder(ROOT)
        works.append(w);tasks.extend(ts);review[w['key']]=wr;notes.update(ns)
        save(ROOT/w['materials']['facts'],f)
        save(ROOT/w['materials']['foreshadows'],t)
    data={'version':'a2-2','set_id':'a26-formal','author':'evaluation authoring','works':works,'tasks':tasks}
    save(ROOT/'tasks.json',data)
    write_self_review(ROOT,data,{'works':review,'task_notes':notes})
    merge_proof(ROOT,data)
    print(f'saved: {len(works)} works, {len(tasks)} tasks; partial_authoring={partial}')

if __name__=='__main__':
    main()
