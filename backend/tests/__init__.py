"""Backend verification package for Story Continuity Copilot."""

import os
import pathlib

# Behaviour tests run against the frozen legacy sample work, independent of the published sample text
# (app/seed/sample_work.json, which test_v170_sample_work validates separately).
os.environ.setdefault("STORY_SAMPLE_WORK_FILE", str(pathlib.Path(__file__).with_name("fixtures") / "sample_work_legacy.json"))
