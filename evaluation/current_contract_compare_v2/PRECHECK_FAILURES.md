# V2 precheck and correction log

- Independent V1 round-two review found three rule-only temporal shortcuts; two later-transition controls rejected even when product `state_change` was supported; loose scoring of extra, wrong-relation, and tampered Evidence; five insufficiency rows requiring background as if it were minimum; and an eight-of-eight `establish` wording cue. V2 revises each of these while leaving V1 frozen.
- The first V2 API probe completed 24/24 scripted runs, but only 8/24 scored structurally. The scorer compared the Issue's per-run claim ID with a **different preflight run's** ID. The scorer now receives the exact business request captured during the scored run and checks its source content against V2 case hashes. The frozen preflight capture is checked for equal business content, excluding ephemeral run IDs.
- After the correction, the 24 base runs and two additional supported `state_change` runs completed and structurally passed. This does not resolve semantic review.
- No product, V1 input/result/manifest, real Provider, author data, SMTP, or environment file was changed by V2 work.
