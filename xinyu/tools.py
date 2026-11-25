"""纯函数层:情绪词打分、压力源关键词、趋势算术。

情绪这件事有大量主观成分,但有两点是能算的:词频倾向、以及一段时间的
均值与波动。能算的交给我,不能算的交给模型——顺序不能反。
"""

from __future__ import annotations

import re
from statistics import mean, pstdev

# 情绪词表:正向 +1/+2,负向 -1/-2。刻意保持短小,靠人自己补。
MOOD_WORDS = {
    "开心": 2, "高兴": 2, "满足": 2, "轻松": 2, "感激": 2, "踏实": 2, "有劲": 2, "顺利": 1,
    "还行": 1, "平静": 1, "普通": 1, "一般": 1,
    "烦": -1, "累": -1, "疲惫": -2, "焦虑": -2, "紧张": -1, "压抑": -2, "低落": -2, "难受": -2,
    "崩溃": -2, "委屈": -2, "孤独": -2, "生气": -2, "失望": -2, "失眠": -2, "麻木": -2,
}

STRESS_WORDS = {
    "加班": "工作负荷", "赶工": "工作负荷", "deadline": "截止时间", "DDL": "截止时间",
    "考试": "考试压力", "面试": "求职压力", "投简历": "求职压力", "开题": "学业压力", "论文": "学业压力",
    "吵架": "人际冲突", "冷战": "人际冲突", "误会": "人际冲突",
    "钱": "经济压力", "房租": "经济压力", "还款": "经济压力", "贷款": "经济压力",
    "体检": "健康担忧", "疼": "身体不适", "头疼": "身体不适", "失眠": "睡眠问题", "睡不着": "睡眠问题",
    "家里人": "家庭牵挂", "父母": "家庭牵挂", "异地": "关系距离",
}

ONLINE = (1, 2, 3, 4, 5)
LIGHT = -1
LOW = (-2, -3)


def mood_score(text: str) -> int:
    """按词表打分,截到 -5..5。没有情绪词就是 0。"""
    s = 0
    for w, v in MOOD_WORDS.items():
        s += v * (text or "").count(w)
    return max(-5, min(5, s))


def mood_label(score: int) -> str:
    if score >= 3:
        return "不错"
    if score >= 1:
        return "还行"
    if score == 0:
        return "说不上好坏"
    if score >= -1:
        return "有点沉"
    return "低落"


def stressors(text: str) -> list[dict]:
    """压力源:关键词命中 + 命中的那一句作为证据。"""
    out, seen = [], set()
    sents = sentences(text)
    for kw, label in STRESS_WORDS.items():
        if kw not in (text or ""):
            continue
        if label in seen:
            continue
        seen.add(label)
        evidence = next((s for s in sents if kw in s), "")
        out.append({"label": label, "keyword": kw, "evidence": evidence})
    return out


def normalize(text: str) -> str:
    """比对用:去空白与常见标点。"""
    return re.sub(r"[\s\u3000，。、；：！？,.;:!?\"“”‘’（）()【】\[\]—…·]", "", text or "")


def contains_quote(source: str, quote: str) -> bool:
    """证据是否真在原文里(归一化后 ≥6 字才算)。"""
    q = normalize(quote)
    if len(q) < 6:
        return False
    return q in normalize(source)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？!?；;\n])", text or "") if s.strip()]


def trend(entries: list[dict]) -> dict:
    """趋势:算术部分。entries 需按日期升序。"""
    scored = [e for e in entries if e.get("mood")]
    if not scored:
        return {"days": len(entries), "analyzed": 0, "avg": 0.0, "volatility": 0.0,
                "best": None, "worst": None, "low_runs": 0}
    scores = [int(e["score"]) for e in scored]
    best = max(scored, key=lambda e: int(e["score"]))
    worst = min(scored, key=lambda e: int(e["score"]))
    runs = 0
    cur = 0
    for s in scores:
        if s <= 0:
            cur += 1
            runs = max(runs, cur)
        else:
            cur = 0
    return {
        "days": len(entries),
        "analyzed": len(scored),
        "avg": round(mean(scores), 2),
        "volatility": round(pstdev(scores), 2) if len(scores) > 1 else 0.0,
        "best": {"date": best["date"], "score": int(best["score"])},
        "worst": {"date": worst["date"], "score": int(worst["score"])},
        "low_runs": runs,
    }


def advice_for(score: int, sources: list[str]) -> list[str]:
    """离线建议:按分数档位给固定动作,不装心理医生。"""
    out = []
    if score >= 3:
        out.append("状态不错,记一下今天做了什么,以后低落时照着做。")
    elif score >= 1:
        out.append("保持现在的节奏,别额外加码。")
    else:
        out.append("今天先减负:把非必须的事推到明天。")
        out.append("出门走 15 分钟,不带手机。")
        if "睡眠问题" in sources:
            out.append("睡前两小时不碰屏幕,比早睡更管用。")
        if "工作负荷" in sources:
            out.append("把任务拆成 20 分钟一段,只做第一段。")
        if "人际冲突" in sources:
            out.append("先把想说的话写下来,明天再决定要不要发。")
    return out[:4]


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------
TOOLS = [
    {"name": "recent_entries", "desc": "取最近几天的记录,看连续性。", "args": {"days": "天数,整数"}},
    {"name": "entry_stats", "desc": "打分均值与波动。", "args": {}},
]


def tool_list_text() -> str:
    return "\n".join(f"- {t['name']}({', '.join(t['args']) or '无'}):{t['desc']}" for t in TOOLS)


def execute(name: str, args: dict, entries: list[dict]) -> dict:
    if name == "recent_entries":
        try:
            n = max(1, min(60, int(args.get("days", 7))))
        except (TypeError, ValueError):
            return {"error": "days 必须是整数"}
        return {"days": n, "entries": entries[-n:]}
    if name == "entry_stats":
        return trend(entries)
    return {"error": f"未知工具: {name}"}


def dump(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
