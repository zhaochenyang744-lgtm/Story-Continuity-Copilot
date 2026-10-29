"""The assistant's crutches (v2.1): what the harness does only because the model cannot yet be trusted to do it alone.

Each was added after a failure the evaluation found, and each costs something (rounds, money, refusals of right items). As
models get better some stop paying for themselves, so each is listed with the weakness it makes up for, the failure that
brought it in, how to tell whether it is still needed, and the switch the development regression (`evaluation/regress.py
--ablate`) turns it off with. When a model changes (the procedure in Desktop/agent规划/03-换模型流程.md), every switchable one is
run off on the spent sets against a same-time run with all on; one that no longer moves a measure is taken out.

Not listed, because they hold whatever the model: a source must be a passage the task read; a record must exist and be one
the task saw; nothing changes before the author confirms; undo restores exactly. Those are the product, not crutches. New
crutches (long tasks: compaction, pausing to ask, checking a step after a resume) are listed here before they ship.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Crutch:
    name: str
    where: str
    weakness: str
    origin: str
    check: str
    switch: bool  # whether `evaluation/regress.py --ablate <name>` turns it off


SPENT_A2 = "the spent A2 pairs (one pass, with a same-time run of the shipped version)"

CRUTCHES = (
    Crutch("consensus", "assistant_consensus (Stage13Settings.assistant_change_runs)",
           "one run of a change task proposes an extra item or misses one on a few cards in every pass",
           "v2.1 p48–p52: unrequested items 3–4 a pass on the shipped prompt; three runs kept 1",
           f"{SPENT_A2}: unrequested items, no-action rate, card rate, cost and time", True),
    Crutch("request_list", "assistant_requests (the split before reading), assistant_actions._grounded",
           "the model proposes a change of another kind than the author asked for, or changes a record it was only asked to read",
           "A2 second pair, p41, injection-07 ('那条请读全' rewrote the record); A2 second formal run, w02-no-action-06 (a thread given "
           "up marked resolved); the word lists it replaced in v2.1 A",
           f"{SPENT_A2}: injection safety, no-action rate, unrequested items", True),
    Crutch("second_look", "assistant_actions._second_look (SECOND_LOOK_SAME, SECOND_LOOK_SAME_SUBJECT, SECOND_LOOK_KEPT)",
           "the model adds a fact the materials already state in other words, or restates a fact it was asked to change",
           "A2 second and third formal runs (w01-no-action-01, w02-no-action-02, w02-action-10): duplicates on no-action tasks",
           f"{SPENT_A2}: no-action rate, unrequested items, rounds used", True),
    Crutch("author_value", "assistant_actions._author_value_missing (a reason of the second look)",
           "the model writes the author's wording of a new state onto a card when the text says otherwise",
           "A2 second formal run, w02-no-action-04 (three passes of three)",
           f"{SPENT_A2}: no-action rate (no-evidence tasks)", True),
    Crutch("value_numbers", "assistant_actions.numbers_in in _grounded",
           "the model puts a number or date into a fact that its passage does not state",
           "A2 second formal run, w01-no-action-03 (a birthday on a passage that names no date)",
           f"{SPENT_A2}: evidence support, no-action rate", True),
    Crutch("request_words", "assistant_actions._request_words and change_request_words_taken",
           "the model proposes a change the author's sentence has no words for, or two changes on one piece of it",
           "A2 development round 2, no-action-05; A2 first formal run, w01/w02-action-12",
           f"{SPENT_A2}: unrequested items", False),
    Crutch("held_answer", "assistant.py: an answer is refused while an item is held back (change_held_back)",
           "the model closes the task in the round an item was held back, and the card comes out empty",
           "A2 second formal run: three empty cards whose answers said a change was proposed",
           f"{SPENT_A2}: card rate; goes with second_look", False),
    Crutch("answer_repair", "assistant.py: one repair round when an answer's citations or note do not hold",
           "the model cites a passage it did not read or describes what it looked at wrongly",
           "A1 and A1c formal runs (v1.8–v1.9)",
           "A1c development sets: citation support and failed tasks", False),
    Crutch("forced_close", "assistant.py: ASSISTANT_MAX_ROUNDS, ASSISTANT_FORCE_ANSWER_CNY, CHANGE_FORCE_NOTICE",
           "the model keeps searching and does not close within the budget",
           "A1c first formal run (budget), A2 third formal run (an item restated in round 7)",
           "A1c and A2 development sets: forced-finish rate, budget, card rate", False),
    # Long tasks (v2.1 B, design 14 section 11). No switch yet: the A3 runner that would turn them off is still to be written.
    Crutch("step_window", "long_tasks.WINDOW_CHAPTERS (a step reads about five chapters)",
           "a model asked about many chapters at once misses what is in them",
           "design 14 (v2.1 B), from the A1c real-length runs, where answers over many chapters lost points",
           "the A3 development set: trace recall and card rate with wider windows, and cost", False),
    Crutch("step_digest", "long_tasks._findings / the digest of earlier steps the program writes into a step",
           "a summary the model writes loses its sources and can be steered by words hidden in the text",
           "design 14 (v2.1 B): compaction is the program's, the rules, request and step list are never summarised",
           "the A3 safety set: compaction-directed injections; the development set: recall across steps", False),
    Crutch("step_repair", "long_tasks._run_step: one more call when a step's report does not validate, then the items that still do not are left out",
           "the model cites a passage outside its step or leaves a verdict without a passage",
           "design 14 (v2.1 B), as answer_repair for questions",
           "the A3 development set: failed tasks and evidence support with no repair", False),
    Crutch("tidy_majority", "long_task_kinds.Tidy.runs / majority: a tidy step is read three times, the facts list in another order each time, and keeps what most readings found",
           "one reading proposes facts the author did not ask for, and not the same ones from reading to reading",
           "A3 dev rounds 2 and 3 (v2.1 B); the user's decision of 2026-10-26, for tidy only",
           "the A3 development sets: unrequested items and card item rate with one reading, and cost", False),
    Crutch("prompt_rules", "assistant.py: SYSTEM_PROMPT and CHANGE_INSTRUCTION, rule by rule",
           "each rule was added after a failure (the commit that added it names the task)",
           "v1.8–v2.1 development rounds",
           "per-rule switch-off on the spent sets, as the word lists were in g1", False),
    Crutch("card_review", "assistant_review (assistant.py _review): one small call per fact or thread item after the runs agree",
           "the model that proposed an item, asked to look again, proposes it once more: a fact the materials state under the full name "
           "restated under a nickname, a thread marked resolved on the author's word when the passage settles another thing",
           "A2 sixth formal run, w01/w02-no-01 and w01/w02-no-04 (addendum 12)",
           f"{SPENT_A2}: no-action rate (already-recorded and no-evidence tasks), card rate, cost and time; whether second_look "
           "and the nickname check (_said_under_full_name) still move a measure with it on", False),
)

BY_NAME = {crutch.name: crutch for crutch in CRUTCHES}
SWITCHES = tuple(crutch.name for crutch in CRUTCHES if crutch.switch)
