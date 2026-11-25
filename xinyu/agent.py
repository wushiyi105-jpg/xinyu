"""编排:模型分析 + 本地算术 + 离线回退。

分工很明确:
  - 分数、均值、波动、连续低落 —— 本地算,模型不许改。
  - 情绪命名、压力源归因、建议 —— 模型说人话,但压力源必须能在原文里查到。
"""

from __future__ import annotations

from . import llm, mock, tools

MAX_STEPS = 12

ANALYZE_SYSTEM = """你在读一个人的当日情绪记录。只用他写下的内容,不做心理诊断,不猜他没写的事。

输出 JSON:
{"mood":"一个词概括今天的状态","score":-5到5的整数,"stressors":[{"label":"压力源类别","evidence":"原文里的一句话"}],"advice":["具体可做的建议,一句话一条"]}

规则:
- score 为负表示消耗,为正表示状态好,0 表示说不上。
- stressors 最多 3 条;evidence 必须从原文逐字摘,不许改写。
- 原文没写到的压力源就不要写,别用「可能」凑。
- advice 最多 4 条,每条不超过 40 字,要具体到动作,不要「多关心自己」这种话。
- 不做诊断,不提药物,不说「你应该去看医生」以外的医疗建议。"""

TREND_SYSTEM = """你在给一段情绪趋势写解读。数字是算好的,你只负责说人话。

输出 JSON:
{"summary":"120 字以内的观察","suggestion":"一句具体建议"}

规则:
- 不许改动数字,不许新增数字。
- 只根据给出的统计说话,不要脑补生活事件。
- 语气平实,不要安慰腔。"""


def _use_model(config: dict | None, force_mock: bool) -> bool:
    if force_mock:
        return False
    return bool({**llm.default_config(), **(config or {})}.get("api_key"))


def _cfg(config: dict | None) -> dict:
    return {**llm.default_config(), **(config or {})}


def _chat(messages, config, max_tokens=1200) -> str:
    return llm.chat(messages, config=_cfg(config), temperature=0.4, max_tokens=max_tokens)


def verify(entry: dict, data: dict) -> tuple[dict, list[str]]:
    """模型结果的硬校验:分数范围、证据可回查、建议长度。"""
    problems = []
    text = entry.get("text", "")
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
        problems.append("score 不是整数,已归零")
    if not -5 <= score <= 5:
        problems.append(f"score {score} 越界,已截断")
        score = max(-5, min(5, score))

    kept = []
    for s in data.get("stressors", [])[:3]:
        ev = str(s.get("evidence", ""))
        if tools.contains_quote(text, ev):
            kept.append({"label": str(s.get("label", "")).strip(), "evidence": ev})
        else:
            problems.append(f"压力源证据在原文里查不到:{ev[:20]}")

    advice = [str(a).strip() for a in data.get("advice", []) if str(a).strip()]
    advice = [a for a in advice if len(a) <= 40][:4]
    return {
        "mood": str(data.get("mood", "")).strip() or tools.mood_label(score),
        "score": score,
        "stressors": kept,
        "advice": advice,
        "problems": problems,
        "offline": False,
    }, problems


def analyze(entry: dict, config: dict | None = None, force_mock: bool = False,
            recent: list[dict] | None = None) -> dict:
    if not _use_model(config, force_mock):
        return mock.analyze(entry)
    ctx = ""
    if recent:
        ctx = "\n最近几天:" + ";".join(
            f"{e['date']} {e.get('mood') or '未分析'}({e.get('score', 0)})" for e in recent[-5:]
        )
    raw = _chat([
        {"role": "system", "content": ANALYZE_SYSTEM},
        {"role": "user", "content": f"日期:{entry['date']}\n今日记录:\n{entry.get('text', '')}{ctx}"},
    ], config)
    data = llm.extract_json(raw)
    result, _ = verify(entry, data)
    result["checks"] = result.pop("problems") or ["硬校验通过:分数在范围内、证据可回查"]
    return result


def trend(entries: list[dict], config: dict | None = None, force_mock: bool = False) -> dict:
    """趋势数字永远本地算;模型只在一段总结里说人话。"""
    t = tools.trend(entries)
    if not _use_model(config, force_mock) or not t.get("analyzed"):
        t["summary"] = mock.trend_text(t)
        t["offline"] = True
        return t
    raw = _chat([
        {"role": "system", "content": TREND_SYSTEM},
        {"role": "user", "content": "统计:" + tools.dump(t)},
    ], config, max_tokens=600)
    data = llm.extract_json(raw)
    summary = str(data.get("summary", "")).strip()
    fresh = tools_new_numbers(summary, t)
    if fresh:
        summary = mock.trend_text(t)
        t["warning"] = "模型新增了统计里没有的数字,已改用本地解读"
    t["summary"] = summary or mock.trend_text(t)
    t["suggestion"] = str(data.get("suggestion", "")).strip()
    t["offline"] = False
    return t


def tools_new_numbers(summary: str, t: dict) -> list[str]:
    """总结里出现、但统计里没有的数字(允许出现统计里的数字)。"""
    import re

    known = {str(x) for x in [t.get("days"), t.get("analyzed"), t.get("avg"), t.get("volatility")]}
    nums = re.findall(r"\d{2,}(?:\.\d+)?", summary)
    return [n for n in nums if n not in known]
