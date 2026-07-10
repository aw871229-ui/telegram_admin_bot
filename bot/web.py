from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from .db import Database
from .utils import now_ts

logger = logging.getLogger(__name__)

_JS = """
async function loadChat(cid){
  document.getElementById('stats-panel').style.display='';
  document.getElementById('logs-panel').style.display='';
  document.getElementById('ledger-panel').style.display='';
  document.getElementById('members-panel').style.display='';
  document.getElementById('export-logs').href='/export/logs/'+cid+'.csv';
  document.getElementById('export-ledger').href='/export/ledger/'+cid+'.csv';
  const [s,l,d,m]=await Promise.all([
    fetch('/api/stats/'+cid).then(r=>r.json()),
    fetch('/api/logs/'+cid).then(r=>r.json()),
    fetch('/api/ledger/'+cid).then(r=>r.json()),
    fetch('/api/members/'+cid).then(r=>r.json()),
  ]);
  renderStats(s);renderLogs(l);renderLedger(d);renderMembers(m);
}
function renderStats(d){
  const g=document.getElementById('stats-grid');
  g.innerHTML=Object.entries(d).map(([k,v])=>'<div class="stat"><div class="num">'+v+'</div><div>'+k+'</div></div>').join('');
}
function makeTable(cols,rows){
  if(!rows.length) return '<p>暂无数据</p>';
  let h='<table><thead><tr>'+cols.map(c=>'<th>'+c+'</th>').join('')+'</tr></thead><tbody>';
  rows.forEach(r=>{h+='<tr>'+cols.map(c=>'<td>'+(r[c]||'')+'</td>').join('')+'</tr>';});
  return h+'</tbody></table>';
}
function renderLogs(d){
  document.getElementById('logs-table').innerHTML=makeTable(
    ['时间','动作','操作者','目标','详情'],
    d.map(r=>({时间:r.created_at,动作:r.action,操作者:r.actor_id,目标:r.target_id,详情:r.detail}))
  );
}
function renderLedger(d){
  document.getElementById('ledger-table').innerHTML=makeTable(
    ['时间','类型','金额','汇率','费率','折算','操作人'],
    d.map(r=>({时间:r.created_at,类型:r.kind,金额:r.amount,汇率:r.rate,费率:r.fee_rate,折算:r.final_amount,操作人:r.user_id}))
  );
}
function renderMembers(d){
  document.getElementById('members-table').innerHTML=makeTable(
    ['用户ID','发言数','警告数','入群时间','待审核'],
    d.map(r=>({
      用户ID:r.user_id,发言数:r.message_count,警告数:r.warns,
      入群时间:r.joined_at?new Date(r.joined_at*1000).toLocaleString():'未知',
      待审核:r.silent_left
    }))
  );
}
"""


def create_web_app(db: Database, super_admins: set[int]) -> web.Application:
    app = web.Application()
    app.router.add_get("/", dashboard_page)
    app.router.add_get("/api/stats/{chat_id:\\d+}", stats_api)
    app.router.add_get("/api/logs/{chat_id:\\d+}", logs_api)
    app.router.add_get("/api/ledger/{chat_id:\\d+}", ledger_api)
    app.router.add_get("/api/members/{chat_id:\\d+}", members_api)
    app.router.add_post("/api/settings/{chat_id:\\d+}", settings_api)
    app.router.add_get("/export/logs/{chat_id:\\d+}.csv", export_logs_csv)
    app.router.add_get("/export/ledger/{chat_id:\\d+}.csv", export_ledger_csv)
    app["db"] = db
    app["super_admins"] = super_admins
    return app


def _json_response(data: Any) -> web.Response:
    return web.json_response(data)


def _build_page(chat_rows: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>管理员面板</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:20px;background:#f5f5f5;color:#333}}
.container{{max-width:1200px;margin:0 auto}}
h1,h2,h3{{color:#1a73e8}}
.card{{background:#fff;border-radius:8px;padding:20px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:12px 0}}
.stat{{background:#e8f0fe;border-radius:8px;padding:16px;text-align:center}}
.stat .num{{font-size:28px;font-weight:bold;color:#1a73e8}}
table{{width:100%;border-collapse:collapse;margin:8px 0}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #e0e0e0}}
th{{background:#f0f0f0;font-weight:600}}
.btn{{display:inline-block;padding:8px 16px;border:none;border-radius:4px;cursor:pointer;font-size:14px;margin:4px;text-decoration:none;color:#fff}}
.btn-primary{{background:#1a73e8}}
.btn-primary:hover{{background:#1557b0}}
.btn-danger{{background:#d93025}}
.btn-danger:hover{{background:#b3261e}}
.chat-list{{list-style:none;padding:0}}
.chat-list li{{padding:10px;border-bottom:1px solid #eee}}
.chat-list li:hover{{background:#e8f0fe}}
#chat-selector{{margin-bottom:20px}}
</style></head><body>
<div class="container">
<h1>Telegram 管理员面板</h1>
<div class="card" id="chat-selector">
<h3>选择群组/频道</h3>
<ul class="chat-list">{chat_rows}</ul>
</div>
<div class="card" id="stats-panel" style="display:none">
<h2>数据统计</h2>
<div class="stats" id="stats-grid"></div>
</div>
<div class="card" id="logs-panel" style="display:none">
<h2>操作日志 <a class="btn btn-primary" id="export-logs">导出 CSV</a></h2>
<div id="logs-table"></div>
</div>
<div class="card" id="ledger-panel" style="display:none">
<h2>记账明细 <a class="btn btn-primary" id="export-ledger">导出 CSV</a></h2>
<div id="ledger-table"></div>
</div>
<div class="card" id="members-panel" style="display:none">
<h2>成员数据</h2>
<div id="members-table"></div>
</div>
</div>
<script>
const params=new URLSearchParams(location.search);
const chatId=params.get('chat');
if(chatId) loadChat(chatId);
{_JS}
</script></body></html>"""


async def dashboard_page(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    chats = await db.fetchall("SELECT chat_id, title FROM chats ORDER BY chat_id")
    chat_rows = ""
    for c in chats:
        chat_rows += f'<li><a href="/?chat={c["chat_id"]}">{html.escape(c["title"] or str(c["chat_id"]))}</a></li>\n'
    page = _build_page(chat_rows)
    resp = web.Response(text=page, content_type="text/html; charset=utf-8")
    return resp


async def stats_api(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    chat_id = int(request.match_info["chat_id"])
    logs = await db.fetchone("SELECT COUNT(*) AS c FROM moderation_logs WHERE chat_id=?", (chat_id,))
    users = await db.fetchone("SELECT COUNT(*) AS c FROM memberships WHERE chat_id=? AND left_at IS NULL", (chat_id,))
    msgs = await db.fetchone("SELECT SUM(message_count) AS c FROM memberships WHERE chat_id=?", (chat_id,))
    today_logs = await db.fetchone(
        "SELECT COUNT(*) AS c FROM moderation_logs WHERE chat_id=? AND created_at>=?",
        (chat_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")),
    )
    return _json_response({
        "当前成员": users["c"] or 0,
        "累计消息": msgs["c"] or 0,
        "管理操作": logs["c"] or 0,
        "今日操作": today_logs["c"] or 0,
    })


async def logs_api(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    chat_id = int(request.match_info["chat_id"])
    rows = await db.fetchall(
        "SELECT actor_id,target_id,action,detail,created_at FROM moderation_logs WHERE chat_id=? ORDER BY id DESC LIMIT 100",
        (chat_id,),
    )
    return _json_response([dict(r) for r in rows])


async def ledger_api(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    chat_id = int(request.match_info["chat_id"])
    rows = await db.fetchall(
        "SELECT kind,amount,rate,fee_rate,final_amount,user_id,created_at FROM ledger_entries WHERE chat_id=? ORDER BY id DESC LIMIT 100",
        (chat_id,),
    )
    return _json_response([dict(r) for r in rows])


async def members_api(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    chat_id = int(request.match_info["chat_id"])
    rows = await db.fetchall(
        "SELECT user_id,message_count,warns,joined_at,silent_left FROM memberships WHERE chat_id=? AND left_at IS NULL ORDER BY message_count DESC LIMIT 100",
        (chat_id,),
    )
    return _json_response([dict(r) for r in rows])


async def settings_api(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    chat_id = int(request.match_info["chat_id"])
    try:
        data = await request.json()
        for key, value in data.items():
            await db.set_setting(chat_id, key, value)
        return _json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def export_logs_csv(request: web.Request) -> web.Response:
    from .export import export_logs_to_csv

    db: Database = request.app["db"]
    chat_id = int(request.match_info["chat_id"])
    rows = await db.fetchall(
        "SELECT * FROM moderation_logs WHERE chat_id=? ORDER BY id DESC LIMIT 5000", (chat_id,)
    )
    csv_str = export_logs_to_csv([dict(r) for r in rows])
    return web.Response(
        text=csv_str,
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=logs_{chat_id}.csv"},
    )


async def export_ledger_csv(request: web.Request) -> web.Response:
    from .export import export_ledger_to_csv

    db: Database = request.app["db"]
    chat_id = int(request.match_info["chat_id"])
    rows = await db.fetchall(
        "SELECT * FROM ledger_entries WHERE chat_id=? ORDER BY id DESC LIMIT 5000", (chat_id,)
    )
    csv_str = export_ledger_to_csv([dict(r) for r in rows])
    return web.Response(
        text=csv_str,
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=ledger_{chat_id}.csv"},
    )