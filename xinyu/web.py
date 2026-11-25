"""Web UI:http.server 单文件,零依赖。"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import agent, llm
from .db import Database

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>心语 · 情绪日记</title>
<style>
:root{--bg:#f7f6fb;--card:#fff;--ink:#22222b;--dim:#70707d;--accent:#5b5bd6;--line:#e4e3f2}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 "Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:30px 18px 60px}
h1{font-size:25px;margin:0 0 4px}.sub{color:var(--dim);margin:0 0 18px}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;margin-left:6px}
.tabs{display:flex;gap:8px;margin:16px 0}
.tab{padding:8px 16px;border:1px solid var(--line);background:var(--card);border-radius:8px;cursor:pointer}
.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:14px}
label{display:block;font-size:14px;color:var(--dim);margin:10px 0 4px}
input,textarea{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;font:inherit}
textarea{min-height:140px;resize:vertical}
button{padding:9px 18px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:inherit;cursor:pointer}
button.ghost{background:#ecebfb;color:var(--accent)}
button:disabled{opacity:.55;cursor:wait}
.out{white-space:pre-wrap;font:14px/1.8 Consolas,"Microsoft YaHei",monospace;background:#fbfbfe;border:1px solid var(--line);border-radius:8px;padding:14px;margin-top:12px;min-height:40px}
.list div{padding:8px 0;border-bottom:1px dashed var(--line);display:flex;justify-content:space-between;font-size:14px}
</style></head><body><div class="wrap">
<h1>心语 <span id="st" class="badge"></span></h1>
<p class="sub">记录只存在本机。分析能说清的交给规则,说不清的交给模型,但不会替你诊断。</p>
<div class="tabs"><div class="tab on" data-t="day">今天</div><div class="tab" data-t="trend">趋势</div></div>

<div class="card" id="p-day">
  <label>日期</label><input id="dDate" type="date">
  <label>今天怎么样(想到什么写什么)</label><textarea id="dText"></textarea>
  <div style="margin-top:12px"><button id="btnSave">记录并分析</button></div>
  <div class="out" id="dayOut"></div>
  <div class="list" id="recent" style="margin-top:14px"></div>
</div>

<div class="card" id="p-trend" style="display:none">
  <label>看最近多少天</label><input id="tDays" type="number" value="7" min="3" max="60">
  <div style="margin-top:12px"><button id="btnTrend">算趋势</button></div>
  <div class="out" id="trendOut"></div>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function loading(btn,on){if(on){btn.dataset.label=btn.dataset.label||btn.textContent.trim();btn.disabled=true;btn.textContent='处理中…';}else{btn.disabled=false;btn.textContent=btn.dataset.label||btn.textContent;}}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));['day','trend'].forEach(k=>$('p-'+k).style.display=k===t.dataset.t?'block':'none');});
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;}
async function loadRecent(){const es=await api('/api/entries?limit=10');
 $('recent').innerHTML=es.map(e=>`<div><span>${esc(e.date)}</span><span>${esc(e.mood||'未分析')} · ${e.score}</span></div>`).join('')||'<div>还没有记录</div>';}
$('btnSave').onclick=async()=>{const btn=$('btnSave');loading(btn,true);
 try{const r=await api('/api/day',{date:$('dDate').value,text:$('dText').value});
  let t=(r.offline?'【离线模式】':'')+r.mood+'  分数 '+r.score+'\\n';
  (r.stressors||[]).forEach(s=>t+='· '+s.label+':'+s.evidence.slice(0,40)+'\\n');
  (r.advice||[]).forEach(a=>t+='→ '+a+'\\n');
  (r.checks||[]).forEach(c=>t+='! '+c+'\\n');
  $('dayOut').textContent=t;await loadRecent();}
 catch(e){$('dayOut').textContent='❌ '+e.message;}finally{loading(btn,false);}};
$('btnTrend').onclick=async()=>{const btn=$('btnTrend');loading(btn,true);
 try{const r=await api('/api/trend?days='+$('tDays').value);
  $('trendOut').textContent=`均分 ${r.avg} / 波动 ${r.volatility} / 有分析 ${r.analyzed} 天\\n\\n`+r.summary+(r.suggestion?'\\n→ '+r.suggestion:'');}
 catch(e){$('trendOut').textContent='❌ '+e.message;}finally{loading(btn,false);}};
(async()=>{try{const s=await api('/api/status');const b=$('st');b.textContent=s.mock?'离线模式':'模型模式';b.style.background=s.mock?'#fdecd6':'#dcefe3';b.style.color=s.mock?'#8a4a12':'#245c31';}catch(e){}
 $('dDate').value=new Date().toISOString().slice(0,10);await loadRecent();})();
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    db: Database
    cfg: dict
    force_mock: bool

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        for enc in ("utf-8", "gbk"):
            try:
                return json.loads(raw.decode(enc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        return {}

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            cfg = {**llm.default_config(), **self.cfg}
            self._json({"mock": self.force_mock or not cfg.get("api_key"), "model": cfg.get("model")})
        elif path == "/api/entries":
            limit = 20
            if "limit=" in u.query:
                try:
                    limit = max(1, min(60, int(u.query.split("limit=")[1].split("&")[0])))
                except ValueError:
                    limit = 20
            self._json(self.db.list_entries(limit))
        elif path == "/api/trend":
            days = 7
            if "days=" in u.query:
                try:
                    days = max(1, min(60, int(u.query.split("days=")[1].split("&")[0])))
                except ValueError:
                    days = 7
            es = self.db.recent(days)
            try:
                self._json(agent.trend(es, config=self.cfg, force_mock=self.force_mock))
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 502)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/day":
            self._json({"error": "not found"}, 404)
            return
        data = self._read_json()
        text = str(data.get("text", "")).strip()
        date = str(data.get("date", "")).strip()
        if not text:
            self._json({"error": "记录不能为空"}, 400)
            return
        if not date:
            from datetime import date as _d

            date = _d.today().isoformat()
        eid = self.db.save_entry(date, text)
        e = self.db.get_entry(eid)
        try:
            r = agent.analyze(e, config=self.cfg, force_mock=self.force_mock, recent=self.db.recent(10))
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 502)
            return
        labels = [s["label"] for s in r.get("stressors", [])]
        self.db.set_analysis(eid, r["mood"], r["score"], labels, "\n".join(r.get("advice", [])))
        r["id"], r["date"] = eid, date
        self._json(r)


def _make_handler(db: Database, cfg: dict, force_mock: bool):
    class Handler(_Handler):
        pass

    Handler.db, Handler.cfg, Handler.force_mock = db, cfg, force_mock
    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, db_path: str | None = None, force_mock: bool = False):
    db = Database(db_path or os.environ.get("XINYU_DB"))
    httpd = ThreadingHTTPServer((host, port), _make_handler(db, llm.default_config(), force_mock))
    print(f"🌤  心语已启动  http://{host}:{httpd.server_address[1]}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        db.close()


if __name__ == "__main__":
    serve()
