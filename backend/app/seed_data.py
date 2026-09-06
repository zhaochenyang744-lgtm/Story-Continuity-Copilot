"""Synthetic, public seed content for the Story Continuity application."""

from __future__ import annotations

SEED_ORIGIN = {
    "origin": "original_demo_specific_web_demo_stage1",
    "created_on": "2026-08-25",
    "restriction": "Synthetic public sample; no private author content or runtime account data is used.",
}

PROJECT = {
    "id": "project-grey-harbor-echo",
    "title": "灰港回声",
    "summary": "一名潮图修复师在雾港追查被改写的航线记录。",
    "data_origin": "demo-specific-original",
}

CHAPTERS = [
    ("ghe-ch-01", 1, "雾钟", "苏岑抵达灰港，听见北潮闸关闭时才会响一次的雾钟。", [("ghe-ch01-s01", "雾钟守则", "灰港的雾钟只在北潮闸完全关闭后敲响一次，别的潮声不会让它响。")]),
    ("ghe-ch-02", 2, "裂纹罗盘", "苏岑从测绘塔取回父亲留下的罗盘。", [("ghe-ch02-s01", "罗盘状态", "黄铜罗盘的镜面有一道月牙裂纹，此刻由苏岑放在外套内袋。")]),
    ("ghe-ch-03", 3, "迟到的渡船", "黎舟带苏岑穿过风栈码头，记录潮汐反常的时刻。", [("ghe-ch03-s01", "时间线", "十九点二十，西航道先退潮，最后一班渡船在十九点四十才离开风栈码头。")]),
    ("ghe-ch-04", 4, "无字潮表", "档案员温岚找到一张加密潮表。", [("ghe-ch04-s01", "知识边界", "温岚看得懂潮表上的坐标，却还不知道‘廊桥钥匙’这个代号指向什么。")]),
    ("ghe-ch-05", 5, "盐雾信箱", "一张无人署名的纸条把三人引向旧灯塔。", [("ghe-ch05-s01", "开放线索", "纸条只写着‘白色渡船没有靠岸’，署名和日期都被盐雾抹去了。")]),
    ("ghe-ch-06", 6, "低室电台", "黎舟修好低室电台，三人听到短促的求救码。", [("ghe-ch06-s01", "事件记录", "电台在二十一点零五分收到三次短促求救码，信号来自雾线水门以外。")]),
    ("ghe-ch-07", 7, "潮线之外", "苏岑和温岚在雾线水门外找到被撕开的航图。", [("ghe-ch07-s01", "地点状态", "航图被固定在雾线水门外的锚柱上，右下角缺失了一块。")]),
    ("ghe-ch-08", 8, "北堤灯火", "温岚用旧档案证明父亲曾守过北堤。", [("ghe-ch08-s01", "关系变化", "温岚把北堤值守簿交给苏岑，两人约定不再各自隐瞒新线索。")]),
    ("ghe-ch-09", 9, "换手", "苏岑将罗盘交给温岚，自己进入封闭仓道。", [("ghe-ch09-s01", "动态状态", "进入仓道前，苏岑把带月牙裂纹的黄铜罗盘交到温岚手里保管。")]),
    ("ghe-ch-10", 10, "回声坐标", "雾钟再响，白色渡船的回声从港外传来。", [("ghe-ch10-s01", "未解问题", "北潮闸并未关闭，雾钟却响了一次；温岚仍握着罗盘，港外传来白色渡船的汽笛。")]),
]
DRAFT = {
    "id": "draft-ghe-ch11",
    "chapter_number": 11,
    "title": "第十一章：未归的航标",
    "body": "温岚仍握着黄铜罗盘；与此同时，黄铜罗盘也在苏岑的外套内袋。随后，温岚把罗盘放在潮汐档案室的桌上。苏岑沿着雾线水门的石阶回望灰港，决定先核对那声不该响起的雾钟。黎舟已经告诉苏岑‘廊桥钥匙’的含义。",
    "revision": 1,
    "status": "saved",
}

MEMORY_RECORDS = [
    ("mem-ghe-v4-001", "static_canon", "灰港雾钟", "ring_condition", "只在北潮闸完全关闭后敲响一次", "ghe-ch01-s01"),
    ("mem-ghe-v4-002", "dynamic_state", "黄铜罗盘", "holder", "温岚", "ghe-ch09-s01"),
    ("mem-ghe-v4-003", "event_timeline", "西航道退潮", "time", "第3章 19:20", "ghe-ch03-s01"),
    ("mem-ghe-v4-004", "character_knowledge", "温岚", "does_not_know", "廊桥钥匙的含义", "ghe-ch04-s01"),
    ("mem-ghe-v4-005", "open_thread", "白色渡船", "status", "没有靠岸，来源未明", "ghe-ch05-s01"),
    ("mem-ghe-v4-006", "dynamic_state", "航图", "location", "雾线水门外锚柱", "ghe-ch07-s01"),
    ("mem-ghe-v4-007", "event_timeline", "低室电台", "received", "第6章 21:05 收到三次求救码", "ghe-ch06-s01"),
    ("mem-ghe-v4-008", "open_thread", "异常雾钟", "status", "北潮闸未关闭时响起，原因未解", "ghe-ch10-s01"),
]

# Deterministic, Web-Demo-only review material. This is authored fixture data,
# not stored or simulated Provider output. Identifiers are rebound to each new
# account's project-local chapters, spans, Memory records, draft, and Run.
DEMO_REVIEW_ISSUES = [
    {
        "claim_text": "温岚仍握着黄铜罗盘；与此同时，黄铜罗盘也在苏岑的外套内袋。",
        "classification": "conflict",
        "nature": "confirmed_conflict",
        "category": "object_state",
        "severity": "high",
        "explanation": "同一时刻、同一枚黄铜罗盘被写成由两人分别持有，形成已确认冲突。",
        "reasoning": "第 10 章在紧邻当前草稿的时间点明确写着温岚仍握着这枚罗盘；当前句又用“与此同时”把同一枚罗盘放进苏岑内袋，时间与对象范围一致，两个位置不能同时成立。",
        "evidence_span_id": "ghe-ch10-s01",
        "evidence_relation": "contradicts",
        "evidence_sufficiency": "sufficient",
        "evidence_role": "prior_state",
        "suggested_revision": {"before": "温岚仍握着黄铜罗盘；与此同时，黄铜罗盘也在苏岑的外套内袋。", "after": "温岚仍握着黄铜罗盘。"},
        "available_actions": ["edit", "apply_suggestion", "keep_intentional", "false_positive"],
        "related_memory_id": "mem-ghe-v4-002",
        "proposed_memory_change": {
            "operation": "add", "memory_type": "open_thread", "subject": "黄铜罗盘临时离手",
            "predicate": "status", "value": "持有人表述冲突，待作者澄清",
        },
    },
    {
        "claim_text": "随后，温岚把罗盘放在潮汐档案室的桌上。",
        "classification": "conflict",
        "nature": "state_change",
        "category": "location_action",
        "severity": "medium",
        "explanation": "这是从“温岚手中”到“档案室桌上”的有先后关系的状态变化。",
        "reasoning": "第 9 章先建立温岚接手保管罗盘的旧状态，当前草稿用“随后”写出她将罗盘放到桌上的后续动作；这是可追溯的前后变化，不应误报为同一时刻冲突。",
        "evidence_span_id": "ghe-ch09-s01",
        "evidence_relation": "context",
        "evidence_sufficiency": "sufficient",
        "evidence_role": "prior_state",
        "suggested_revision": None,
        "available_actions": ["edit", "keep_intentional", "false_positive"],
        "related_memory_id": "mem-ghe-v4-002",
        "proposed_memory_change": {
            "operation": "replace", "memory_type": "dynamic_state", "subject": "黄铜罗盘",
            "predicate": "holder", "value": "由温岚放在潮汐档案室桌上", "affected_memory_id": "mem-ghe-v4-002",
        },
    },
    {
        "claim_text": "苏岑决定先核对那声不该响起的雾钟。",
        "classification": "conflict",
        "nature": "possible_conflict",
        "category": "event_status",
        "severity": "medium",
        "explanation": "雾钟规则与异常响钟之间存在疑点，但既有正文已把它标为未解线索。",
        "reasoning": "第 1 章给出正常响钟规则，第 10 章则明确保留一次异常响钟；当前草稿只是继续调查这个开放线索，尚不足以确认世界规则已被无意违反。",
        "evidence_span_id": "ghe-ch10-s01",
        "evidence_relation": "context",
        "evidence_sufficiency": "sufficient",
        "evidence_role": "current_context",
        "suggested_revision": None,
        "available_actions": ["edit", "keep_intentional", "false_positive"],
        "related_memory_id": "mem-ghe-v4-008",
        "proposed_memory_change": {
            "operation": "add",
            "memory_type": "event_timeline",
            "subject": "苏岑",
            "predicate": "next_action",
            "value": "优先核对异常雾钟",
        },
    },
    {
        "claim_text": "黎舟已经告诉苏岑‘廊桥钥匙’的含义。",
        "classification": "insufficient_evidence",
        "nature": "insufficient_evidence",
        "category": "character_knowledge",
        "severity": "low",
        "explanation": "已写来源没有出现黎舟完成告知或苏岑获知该含义的事件。",
        "reasoning": "第 4 章只证明温岚当时不知道代号含义；现有来源中缺少黎舟获知、转告以及苏岑接收信息的中间事件，因此在证据链缺口补齐前停止判断。",
        "evidence_span_id": "ghe-ch04-s01",
        "evidence_relation": "context",
        "evidence_sufficiency": "insufficient",
        "evidence_role": "missing_link",
        "suggested_revision": None,
        "available_actions": [],
        "related_memory_id": "mem-ghe-v4-004",
        "proposed_memory_change": None,
    },
]
