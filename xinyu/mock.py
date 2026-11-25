"""离线模式:词表打分 + 关键词找压力源 + 分档建议。

情绪分析里最该老实的一句话:规则引擎看不出你没写出来的东西。
所以离线结果只基于你写下的字,不做心理推断。
"""

from __future__ import annotations

from . import tools


def analyze(entry: dict) -> dict:
    text = entry.get("text", "")
    score = tools.mood_score(text)
    sources = tools.stressors(text)
    labels = [s["label"] for s in sources]
    return {
        "mood": tools.mood_label(score),
        "score": score,
        "stressors": sources,
        "advice": tools.advice_for(score, labels),
        "offline": True,
        "checks": ["离线模式:只做了词表打分与关键词匹配,未做推断"],
    }


def trend_text(t: dict) -> str:
    if not t.get("analyzed"):
        return "还没有带分析的记录,先 analyze 几天再看趋势。"
    lines = [
        f"看了 {t['days']} 天,其中 {t['analyzed']} 天有分析。",
        f"平均分 {t['avg']},波动 {t['volatility']}(波动越小,说明这几天状态越稳)。",
    ]
    if t.get("best"):
        lines.append(f"最好的一天:{t['best']['date']}({t['best']['score']} 分)。")
    if t.get("worst"):
        lines.append(f"最难的一天:{t['worst']['date']}({t['worst']['score']} 分)。")
    if t["analyzed"] < 3:
        lines.append("样本还太少,连续低落要看至少 3 天有分析的记录才算得准。")
    elif t.get("low_runs", 0) >= 3:
        lines.append(f"注意:出现过连续 {t['low_runs']} 天不高于 0 分,这不是懒,是消耗累积。")
    else:
        lines.append("没有连续三天的低落段,节奏还算稳。")
    return "\n".join(lines)
