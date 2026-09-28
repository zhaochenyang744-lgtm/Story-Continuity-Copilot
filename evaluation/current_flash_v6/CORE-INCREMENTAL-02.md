# V6 core incremental fix after independent malformed-enum probe

The independent `ROOT-NEW-ENUM-PROBE-02.json` found that an array-valued `claim_verdicts[].verdict` escaped as a Python `TypeError` before bounded contract repair. The V6-only verdict checker now requires a string before enum membership. The new control uses captured comparison case 02 and checks list, object, null and number, both direct validation and `execute`: each gets the controlled `claim_verdicts_invalid` result after at most the existing one repair. The first independent probe and previous core review remain historical evidence; this edit supersedes the prior engine/test hashes for acceptance.

Current hashes: `backend/app/provider.py` = `ed33b19761acfec79cff0a14d171389eaa9659ba4774223a4d161c58d2d32643` (unchanged); `backend/app/engine.py` = `26de881938315b01b5208e8d9f35a6826ddd9615dd1d8bcff8f670a48836e949`; `backend/tests/test_v6_continuity_contract.py` = `7f1a9325e01e0ce2f31177566313acf0905b7a72cb3a02cec034780bc4fbc57f`.

The same offline command from `CORE-OFFLINE-HANDOFF.md` now reports **42 tests, 0 failures/errors**. No Provider HTTP or real database access occurred.
