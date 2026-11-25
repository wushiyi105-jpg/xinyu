"""命令行入口:python -m xinyu <命令> [选项]。"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, agent, llm
from . import db as dbmod
from .llm import LLMError

MOCK_BANNER = (
    "⚠️  当前为离线模式(未配置 LLM_API_KEY),分析由词表与关键词规则完成。\n"
    "   在 .env 填入 LLM_API_KEY 后,情绪命名与建议交给大模型。\n"
)

_OPEN: list = []


def _db(args) -> dbmod.Database:
    db = dbmod.Database(getattr(args, "db", None))
    _OPEN.append(db)
    return db


def _close_all() -> None:
    for d in _OPEN:
        d.close()
    _OPEN.clear()


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def render_entry(e: dict) -> str:
    mood = e.get("mood") or "未分析"
    return f"[{e['id']}] {e['date']}  {mood}({e.get('score', 0)})  {len(e['text'])} 字"


def render_analysis(r: dict) -> str:
    head = f"🌤  {r['mood']}  分数 {r['score']}"
    if r.get("offline"):
        head += "  ·  离线模式"
    lines = [head]
    for s in r.get("stressors", []):
        lines.append(f"  · 压力源 {s['label']}:{s['evidence'][:40]}")
    for a in r.get("advice", []):
        lines.append(f"  → {a}")
    for c in r.get("checks", []):
        lines.append(f"  ! {c}")
    return "\n".join(lines)


def cmd_add(args):
    db = _db(args)
    text = _read_input(args.file)
    if not text.strip():
        print("❌ 记录为空", file=sys.stderr)
        sys.exit(1)
    date = args.date or __import__("datetime").date.today().isoformat()
    eid = db.save_entry(date, text)
    print(f"✅ 已记录 [{eid}] {date}  {len(text)} 字")


def cmd_list(args):
    db = _db(args)
    es = db.list_entries(args.limit)
    if args.json:
        print(json.dumps(es, ensure_ascii=False, indent=2))
        return
    if not es:
        print("(空)用 xinyu add 记一条")
        return
    for e in es:
        print(render_entry(e))


def cmd_show(args):
    db = _db(args)
    e = db.get_entry(args.key)
    if not e:
        print(f"❌ 找不到记录:{args.key}", file=sys.stderr)
        sys.exit(1)
    print(render_entry(e))
    print("\n" + e["text"])
    if e["mood"]:
        print(f"\n分析:{e['mood']}({e['score']})")
        for s in e["stressors"]:
            print(f"  · {s['label']}:{s['evidence']}")
        print("建议:")
        for a in e["advice"]:
            print(f"  → {a}")


def cmd_analyze(args):
    db = _db(args)
    e = db.get_entry(args.key)
    if not e:
        print(f"❌ 找不到记录:{args.key}", file=sys.stderr)
        sys.exit(1)
    recent = [x for x in db.recent(10) if x["date"] < e["date"]]
    r = agent.analyze(e, config=llm.config_from_args(args), force_mock=args.mock, recent=recent)
    labels = [s["label"] for s in r.get("stressors", [])]
    db.set_analysis(e["id"], r["mood"], r["score"], labels, "\n".join(r.get("advice", [])))
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(render_analysis(r))
        print("\n✅ 已存进这一天")


def cmd_trend(args):
    db = _db(args)
    es = db.recent(args.days)
    r = agent.trend(es, config=llm.config_from_args(args), force_mock=args.mock)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    print(f"📈 最近 {r['days']} 天趋势" + ("  ·  离线模式" if r.get("offline") else ""))
    print(f"均分 {r['avg']} / 波动 {r['volatility']} / 有分析 {r['analyzed']} 天")
    print()
    print(r.get("summary", ""))
    if r.get("suggestion"):
        print(f"\n→ {r['suggestion']}")
    if r.get("warning"):
        print(f"! {r['warning']}")


def cmd_rm(args):
    db = _db(args)
    e = db.get_entry(args.key)
    if not e:
        print(f"❌ 找不到记录:{args.key}", file=sys.stderr)
        sys.exit(1)
    db.delete_entry(e["id"])
    print(f"🗑  已删除 [{e['id']}] {e['date']}")


def cmd_stats(args):
    print(json.dumps(_db(args).stats(), ensure_ascii=False))


def cmd_web(args):
    from . import web

    web.serve(host=args.host, port=args.port, db_path=args.db, force_mock=args.mock)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xinyu", description="心语 · 情绪日记:记录、分析、看趋势。")
    p.add_argument("--version", action="version", version=f"xinyu {__version__}")
    p.add_argument("--mock", action="store_true", help="强制离线模式(不调用模型)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--api-key")
    p.add_argument("--db")

    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="记一条(文件或 - 读 stdin)")
    a.add_argument("file")
    a.add_argument("--date", help="YYYY-MM-DD,默认今天")
    a.set_defaults(func=cmd_add)

    ls = sub.add_parser("list", help="最近的记录")
    ls.add_argument("--limit", type=int, default=30)
    ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show", help="看某一天的记录")
    sh.add_argument("key", help="id 或日期")
    sh.set_defaults(func=cmd_show)

    an = sub.add_parser("analyze", help="分析这一天")
    an.add_argument("key")
    an.set_defaults(func=cmd_analyze)

    tr = sub.add_parser("trend", help="趋势")
    tr.add_argument("--days", type=int, default=7)
    tr.set_defaults(func=cmd_trend)

    rm = sub.add_parser("rm", help="删一条")
    rm.add_argument("key")
    rm.set_defaults(func=cmd_rm)

    st = sub.add_parser("stats", help="统计")
    st.set_defaults(func=cmd_stats)

    wb = sub.add_parser("web", help="启动 Web 界面")
    wb.add_argument("--host", default="127.0.0.1")
    wb.add_argument("--port", type=int, default=8000)
    wb.set_defaults(func=cmd_web)
    return p


GLOBAL_FLAGS = ("--mock", "--json")
GLOBAL_OPTS = ("--model", "--base-url", "--api-key", "--db")


def hoist_globals(argv: list[str]) -> list[str]:
    """把全局开关挪到子命令前。"""
    g, rest = [], []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in GLOBAL_FLAGS:
            g.append(a)
            i += 1
        elif a in GLOBAL_OPTS:
            g += [a, argv[i + 1]] if i + 1 < len(argv) else [a]
            i += 2
        elif any(a.startswith(o + "=") for o in GLOBAL_OPTS):
            g.append(a)
            i += 1
        else:
            rest.append(a)
            i += 1
    return g + rest


def main(argv=None):
    args = build_parser().parse_args(hoist_globals(list(sys.argv[1:] if argv is None else argv)))
    if not args.mock and args.command in ("analyze", "trend"):
        if not llm.config_from_args(args).get("api_key"):
            print(MOCK_BANNER, file=sys.stderr)
    try:
        args.func(args)
    except LLMError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    finally:
        _close_all()


if __name__ == "__main__":
    main()
