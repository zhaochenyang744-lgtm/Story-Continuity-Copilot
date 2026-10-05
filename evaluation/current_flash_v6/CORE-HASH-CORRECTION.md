# Core handoff hash transcription correction

The first `CORE-OFFLINE-HANDOFF.md` transcribed the Provider digest incorrectly as a 63-character value. The tested file did not change. The current, 64-character SHA-256 of `backend/app/provider.py` is:

`ed33b19761acfec79cff0a14d171389eaa9659ba4774223a4d161c58d2d32643`

The other two recorded digests remain correct: `backend/app/engine.py` is `0f0d34335636bf05b551dbfe8ec88ffff07fabb0d7a6a577dd987ebd1ffcee59`; `backend/tests/test_v6_continuity_contract.py` is `c976efb224b00b4f039dc77bf2f558c724eeb60d9e7aec429016fe9049bda357`. These are the same files used by the reported 41-test passing command. The first rejected core freeze attempt and old handoff remain intact for the audit chain; no product edit or Provider call followed that mismatch.
