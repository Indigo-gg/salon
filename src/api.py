"""Salon Web API — 提供会话状态的 HTTP 查询接口。

启动方式：
  - CLI 模式下自动在后台线程启动（端口 8765）
  - 独立启动：uvicorn src.api:app --port 8765

端点：
  GET /api/memory              → 所有 agent 的记忆（JSON）
  GET /api/memory/{agent_id}   → 单个 agent 的记忆（JSON）
  GET /api/export?format=md    → 导出 Markdown
  GET /api/export?format=html  → 导出 HTML
  GET /api/export?format=pdf   → 导出 PDF
  GET /memory                  → 记忆卡片页面（HTML）
  GET /export                  → 导出页面（HTML）
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, Response

if TYPE_CHECKING:
    from src.memory import MemorySystem

app = FastAPI(title="Salon API", version="0.1")

# 全局引用，由 start_server() 注入
_memory: MemorySystem | None = None
_agents_info: dict[str, dict] = {}  # agent_id -> {name, role, soul_path}
_session_dir: str | None = None     # 当前 session 目录路径


def bind(memory: MemorySystem, agents_info: dict[str, dict], session_dir: str | None = None) -> None:
    """将运行时的 MemorySystem 和 agent 信息绑定到 API。"""
    global _memory, _agents_info, _session_dir
    _memory = memory
    _agents_info = agents_info
    _session_dir = session_dir


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@app.get("/api/memory")
def get_all_memories():
    if not _memory:
        return {"error": "No active session"}
    result = {}
    for agent_id, mem in _memory.agent_memories.items():
        info = _agents_info.get(agent_id, {})
        result[agent_id] = {
            "name": info.get("name", agent_id),
            "role": info.get("role", "participant"),
            "expressed_stances": mem.expressed_stances,
            "unique_contributions": mem.unique_contributions,
            "active_disagreements": mem.active_disagreements,
            "pending_points": mem.pending_points,
        }
    return result


@app.get("/api/memory/{agent_id}")
def get_agent_memory(agent_id: str):
    if not _memory:
        return {"error": "No active session"}
    mem = _memory.agent_memories.get(agent_id)
    if not mem:
        return {"error": f"Agent '{agent_id}' not found"}
    info = _agents_info.get(agent_id, {})
    return {
        "agent_id": agent_id,
        "name": info.get("name", agent_id),
        "role": info.get("role", "participant"),
        "expressed_stances": mem.expressed_stances,
        "unique_contributions": mem.unique_contributions,
        "active_disagreements": mem.active_disagreements,
        "pending_points": mem.pending_points,
    }


# ---------------------------------------------------------------------------
# HTML 页面
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Salon — Agent Memories</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; color: #333; }
  .header { background: #1a1a2e; color: #eee; padding: 16px 24px; display: flex; align-items: center; gap: 16px; }
  .header h1 { font-size: 18px; font-weight: 600; }
  .header .nav-btns { margin-left: auto; display: flex; gap: 8px; }
  .header .nav-btns a, .header .nav-btns button { background: #333; color: #ccc; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 13px; text-decoration: none; }
  .header .nav-btns a:hover, .header .nav-btns button:hover { background: #555; }
  .tabs { display: flex; background: #fff; border-bottom: 1px solid #ddd; overflow-x: auto; }
  .tab { padding: 10px 20px; cursor: pointer; font-size: 14px; border-bottom: 2px solid transparent; white-space: nowrap; transition: all 0.15s; }
  .tab:hover { background: #f0f0f0; }
  .tab.active { border-bottom-color: #4a6fa5; color: #4a6fa5; font-weight: 600; }
  .content { max-width: 800px; margin: 24px auto; padding: 0 16px; }
  .card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 20px; margin-bottom: 16px; }
  .card h3 { font-size: 14px; color: #666; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card ul { list-style: none; padding: 0; }
  .card li { padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 14px; line-height: 1.5; }
  .card li:last-child { border-bottom: none; }
  .empty { color: #999; font-style: italic; font-size: 13px; }
  .badge { display: inline-block; background: #e8eef4; color: #4a6fa5; padding: 2px 8px; border-radius: 10px; font-size: 12px; margin-left: 6px; }
  .agent-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
  .agent-header .name { font-size: 20px; font-weight: 700; }
  .agent-header .role { font-size: 13px; color: #888; background: #f0f0f0; padding: 2px 10px; border-radius: 10px; }
  .warning { background: #fff3cd; border-left: 3px solid #ffc107; padding: 8px 12px; font-size: 13px; color: #856404; border-radius: 0 4px 4px 0; margin-top: 12px; }
</style>
</head>
<body>
  <div class="header">
    <h1>🧠 Salon — Agent Memories</h1>
    <div class="nav-btns">
      <a href="/replay">回放</a>
      <a href="/export">导出</a>
      <button onclick="load()">Refresh</button>
    </div>
  </div>
  <div class="tabs" id="tabs"></div>
  <div class="content" id="content"></div>

<script>
let data = {};
let activeTab = null;

async function load() {
  const resp = await fetch('/api/memory');
  data = await resp.json();
  if (data.error) {
    document.getElementById('content').innerHTML = '<p style="padding:24px;color:#999">' + data.error + '</p>';
    return;
  }
  const ids = Object.keys(data);
  if (!ids.length) {
    document.getElementById('content').innerHTML = '<p style="padding:24px;color:#999">No agent memories yet.</p>';
    return;
  }
  renderTabs(ids);
  if (!activeTab || !data[activeTab]) activeTab = ids[0];
  renderCard(activeTab);
}

function renderTabs(ids) {
  const el = document.getElementById('tabs');
  el.innerHTML = ids.map(id => {
    const d = data[id];
    const label = d.name || id;
    return '<div class="tab ' + (id === activeTab ? 'active' : '') + '" onclick="switchTab(\\'' + id + '\\')">' + label + '</div>';
  }).join('');
}

function switchTab(id) {
  activeTab = id;
  renderCard(id);
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
}

function renderCard(id) {
  const d = data[id];
  let html = '<div class="agent-header"><span class="name">' + (d.name || id) + '</span><span class="role">' + (d.role || '') + '</span></div>';

  html += section('已表达立场', d.expressed_stances);
  html += section('独特贡献', d.unique_contributions);
  html += section('活跃分歧', d.active_disagreements);
  html += section('待表达', d.pending_points);

  document.getElementById('content').innerHTML = '<div class="card">' + html + '</div>';
}

function section(title, items) {
  if (!items || !items.length) return '<h3>' + title + '</h3><p class="empty">暂无</p>';
  let html = '<h3>' + title + ' <span class="badge">' + items.length + '</span></h3><ul>';
  items.forEach(item => { html += '<li>' + escapeHtml(item) + '</li>'; });
  html += '</ul>';
  return html;
}

function escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

load();
setInterval(load, 10000);
</script>
</body>
</html>"""


@app.get("/memory", response_class=HTMLResponse)
def memory_page():
    return HTMLResponse(_HTML_TEMPLATE)


# ---------------------------------------------------------------------------
# 导出 API
# ---------------------------------------------------------------------------

@app.get("/api/export")
def api_export(
    format: str = Query("html", pattern="^(md|html|pdf)$"),
    include_reasoning: bool = Query(True),
):
    if not _session_dir:
        return {"error": "No active session"}
    from src.output.export import export_session
    try:
        content, filename, media_type = export_session(
            _session_dir, fmt=format, include_reasoning=include_reasoning,
        )
        if isinstance(content, str):
            content = content.encode("utf-8")
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return {"error": str(e)}


_EXPORT_PAGE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Salon — 档案导出</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif; background: #f8f9fa; color: #2d3436; }
  .container { max-width: 520px; margin: 80px auto; padding: 0 20px; }
  .card { background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 32px; }
  h1 { font-size: 20px; margin-bottom: 8px; }
  .subtitle { font-size: 14px; color: #636e72; margin-bottom: 24px; }
  .options { display: flex; flex-direction: column; gap: 12px; }
  .opt {
    display: flex; align-items: center; gap: 14px; padding: 14px 16px;
    border: 2px solid #dfe6e9; border-radius: 10px; cursor: pointer;
    transition: all 0.15s; text-decoration: none; color: inherit;
  }
  .opt:hover { border-color: #0984e3; background: #f0f7ff; }
  .opt .icon { font-size: 28px; }
  .opt .label { font-weight: 600; font-size: 15px; }
  .opt .desc { font-size: 13px; color: #636e72; margin-top: 2px; }
  .checkbox-row { display: flex; align-items: center; gap: 8px; margin-top: 16px; font-size: 14px; color: #636e72; }
  .nav { margin-top: 20px; text-align: center; }
  .nav a { color: #0984e3; text-decoration: none; font-size: 14px; }
  .nav a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <h1>📦 档案导出</h1>
    <p class="subtitle">选择导出格式，下载对话记录</p>
    <div class="options">
      <a class="opt" onclick="download('md')">
        <span class="icon">📝</span>
        <div><div class="label">Markdown</div><div class="desc">纯文本格式，适合分享和二次编辑</div></div>
      </a>
      <a class="opt" onclick="download('html')">
        <span class="icon">🌐</span>
        <div><div class="label">HTML</div><div class="desc">自包含网页，支持暗色模式，可浏览器打印为 PDF</div></div>
      </a>
      <a class="opt" onclick="download('pdf')">
        <span class="icon">📄</span>
        <div><div class="label">PDF</div><div class="desc">需要安装 weasyprint，否则回退为 HTML</div></div>
      </a>
    </div>
    <label class="checkbox-row">
      <input type="checkbox" id="reasoning" checked> 包含推理过程（review / thought）
    </label>
  </div>
  <div class="nav"><a href="/replay">← 回放页</a> · <a href="/memory">记忆卡片</a></div>
</div>
<script>
function download(fmt) {
  const include = document.getElementById('reasoning').checked;
  let url = '/api/export?format=' + fmt;
  if (!include) url += '&include_reasoning=false';
  window.location.href = url;
}
</script>
</body>
</html>
"""


@app.get("/export", response_class=HTMLResponse)
def export_page():
    return HTMLResponse(_EXPORT_PAGE)


# ---------------------------------------------------------------------------
# 回放页（对话流 + 记忆卡片侧栏）
# ---------------------------------------------------------------------------

@app.get("/api/replay")
def api_replay():
    """返回对话消息列表（排除 intent）。"""
    if not _session_dir:
        return {"error": "No active session"}
    from src.output.export import _load_messages, _filter_speech
    messages = _load_messages(_session_dir)
    messages = _filter_speech(messages)
    return {"messages": messages}


_REPLAY_PAGE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Salon — 回放室</title>
<style>
  :root { --bg:#f8f9fa; --card:#fff; --text:#2d3436; --sub:#636e72; --border:#dfe6e9; --accent:#0984e3; }
  @media(prefers-color-scheme:dark){ :root{--bg:#1a1a2e;--card:#16213e;--text:#eee;--sub:#b2bec3;--border:#2d3436;--accent:#74b9ff;} }
  *{margin:0;padding:0;box-sizing:border-box;}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif;background:var(--bg);color:var(--text);line-height:1.7;}
  .top-bar{background:#1a1a2e;color:#eee;padding:12px 20px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:100;}
  .top-bar h1{font-size:16px;font-weight:600;}
  .top-bar .nav-btns{margin-left:auto;display:flex;gap:8px;}
  .top-bar .nav-btns a{background:#333;color:#ccc;border:none;padding:5px 12px;border-radius:4px;font-size:12px;text-decoration:none;}
  .top-bar .nav-btns a:hover{background:#555;}
  .layout{display:flex;max-width:1200px;margin:0 auto;min-height:calc(100vh - 48px);}
  .conversation{flex:1;padding:20px;overflow-y:auto;}
  .sidebar{width:320px;border-left:1px solid var(--border);background:var(--card);padding:16px;overflow-y:auto;position:sticky;top:48px;height:calc(100vh - 48px);}
  .round-divider{text-align:center;margin:24px 0 12px;position:relative;}
  .round-divider::before{content:"";position:absolute;left:0;right:0;top:50%;border-top:1px solid var(--border);}
  .round-divider span{background:var(--bg);padding:0 14px;position:relative;font-size:12px;color:var(--sub);font-weight:600;letter-spacing:1px;}
  .msg{background:var(--card);border-radius:8px;padding:14px 16px;margin-bottom:10px;border-left:3px solid var(--accent);box-shadow:0 1px 2px rgba(0,0,0,0.05);}
  .msg.system{background:#fff3cd;border-left-color:#ffc107;font-size:13px;font-style:italic;color:#856404;}
  @media(prefers-color-scheme:dark){.msg.system{background:#2d2006;color:#ffc107;}}
  .msg-head{display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap;}
  .msg-name{font-weight:700;font-size:14px;}
  .msg-type{font-size:10px;padding:1px 6px;border-radius:8px;background:var(--border);color:var(--sub);}
  .msg-mention{font-size:11px;color:var(--sub);}
  .msg-body{font-size:14px;white-space:pre-wrap;word-break:break-word;}
  details{margin-top:8px;font-size:12px;color:var(--sub);}
  details summary{cursor:pointer;font-weight:500;}
  details .reasoning{margin-top:4px;padding:8px;background:var(--bg);border-radius:4px;white-space:pre-wrap;font-size:12px;line-height:1.5;}
  .sidebar h2{font-size:14px;color:var(--sub);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px;}
  .agent-tabs{display:flex;gap:4px;margin-bottom:12px;flex-wrap:wrap;}
  .agent-tab{padding:4px 10px;font-size:12px;border-radius:12px;cursor:pointer;border:1px solid var(--border);background:transparent;color:var(--text);transition:all 0.15s;}
  .agent-tab:hover{background:var(--border);}
  .agent-tab.active{background:var(--accent);color:#fff;border-color:var(--accent);}
  .mem-section{margin-bottom:14px;}
  .mem-section h3{font-size:12px;color:var(--sub);margin-bottom:4px;text-transform:uppercase;}
  .mem-section ul{list-style:none;padding:0;}
  .mem-section li{font-size:13px;padding:3px 0;border-bottom:1px solid var(--border);line-height:1.4;}
  .mem-section li:last-child{border:none;}
  .mem-empty{font-size:12px;color:var(--sub);font-style:italic;}
  .empty-state{text-align:center;padding:60px 20px;color:var(--sub);}
  @media(max-width:800px){.layout{flex-direction:column;}.sidebar{width:100%;position:static;height:auto;border-left:none;border-top:1px solid var(--border);}}
</style>
</head>
<body>
<div class="top-bar">
  <h1>🎬 回放室</h1>
  <div class="nav-btns">
    <a href="/memory">记忆卡片</a>
    <a href="/export">导出</a>
  </div>
</div>
<div class="layout">
  <div class="conversation" id="conv"></div>
  <div class="sidebar" id="sidebar">
    <h2>🧠 记忆卡片</h2>
    <div class="agent-tabs" id="agent-tabs"></div>
    <div id="mem-content"></div>
  </div>
</div>
<script>
const COLORS={moderator:'#6c5ce7',participant:'#0984e3',scribe:'#00b894',system:'#636e72',human:'#d63031'};
const LABELS={Extend:'延伸',Dissent:'反驳',New_Angle:'新角度',Clarify:'澄清',Ask:'提问',Pass:'跳过',system_notice:'通知',question:'提问'};
let memData={};
let activeAgent=null;
let messages=[];

async function load(){
  const[repResp,memResp]=await Promise.all([fetch('/api/replay'),fetch('/api/memory')]);
  const rep=await repResp.json();
  memData=await memResp.json();
  if(rep.error){document.getElementById('conv').innerHTML='<div class="empty-state">'+rep.error+'</div>';return;}
  messages=rep.messages;
  renderConversation();
  renderAgentTabs();
  if(activeAgent&&memData[activeAgent])renderMemory(activeAgent);
  else{const ids=Object.keys(memData);if(ids.length){activeAgent=ids[0];renderMemory(activeAgent);}}
}

function renderConversation(){
  const el=document.getElementById('conv');
  let html='';
  let curRound=null;
  messages.forEach(m=>{
    const r=m.round;
    if(r!==curRound){curRound=r;html+='<div class="round-divider"><span>第 '+r+' 轮</span></div>';}
    const color=COLORS[m.agent_role]||COLORS.participant;
    const content=escapeHtml(m.content);
    if(m.agent_role==='system'){
      html+='<div class="msg system"><div class="msg-head"><span class="msg-name">📢 '+escapeHtml(m.agent_name)+'</span></div><div class="msg-body">'+content+'</div></div>';
    }else{
      const typeLabel=LABELS[m.speech_type]||m.speech_type||'';
      const mention=m.mentions&&m.mentions.length?'<span class="msg-mention">→ '+escapeHtml(m.mentions.join(', '))+'</span>':'';
      let reasoning='';
      if(m.review||m.thought){
        let parts='';
        if(m.review)parts+='<b>review:</b><br>'+escapeHtml(m.review);
        if(m.thought)parts+=(parts?'<br><br>':'')+'<b>thought:</b><br>'+escapeHtml(m.thought);
        reasoning='<details><summary>💭 推理</summary><div class="reasoning">'+parts+'</div></details>';
      }
      html+='<div class="msg" style="border-left-color:'+color+'">'
        +'<div class="msg-head"><span class="msg-name" style="color:'+color+'">'+escapeHtml(m.agent_name)+'</span>'
        +(typeLabel?'<span class="msg-type">'+escapeHtml(typeLabel)+'</span>':'')
        +mention+'</div>'
        +'<div class="msg-body">'+content+'</div>'
        +reasoning+'</div>';
    }
  });
  el.innerHTML=html||'<div class="empty-state">暂无对话记录</div>';
}

function renderAgentTabs(){
  const el=document.getElementById('agent-tabs');
  const ids=Object.keys(memData);
  el.innerHTML=ids.map(id=>{
    const d=memData[id];
    return '<div class="agent-tab '+(id===activeAgent?'active':'')+'" onclick="switchAgent(\\''+id+'\\')">'+escapeHtml(d.name||id)+'</div>';
  }).join('');
}

function switchAgent(id){
  activeAgent=id;
  renderAgentTabs();
  renderMemory(id);
}

function renderMemory(id){
  const d=memData[id];
  if(!d){document.getElementById('mem-content').innerHTML='<p class="mem-empty">暂无记忆</p>';return;}
  let html='';
  html+=memSection('已表达立场',d.expressed_stances);
  html+=memSection('独特贡献',d.unique_contributions);
  html+=memSection('活跃分歧',d.active_disagreements);
  html+=memSection('待表达',d.pending_points);
  document.getElementById('mem-content').innerHTML=html;
}

function memSection(title,items){
  if(!items||!items.length)return '<div class="mem-section"><h3>'+title+'</h3><p class="mem-empty">暂无</p></div>';
  let html='<div class="mem-section"><h3>'+title+' ('+items.length+')</h3><ul>';
  items.forEach(i=>{html+='<li>'+escapeHtml(i)+'</li>';});
  html+='</ul></div>';
  return html;
}

function escapeHtml(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML;}

load();
setInterval(async()=>{
  const r=await fetch('/api/memory');
  memData=await r.json();
  if(activeAgent)renderMemory(activeAgent);
},15000);
</script>
</body>
</html>
"""


@app.get("/replay", response_class=HTMLResponse)
def replay_page():
    return HTMLResponse(_REPLAY_PAGE)


# ---------------------------------------------------------------------------
# 服务器启动
# ---------------------------------------------------------------------------

def start_server(memory: MemorySystem, agents_info: dict[str, dict], session_dir: str | None = None, port: int = 8765) -> threading.Thread:
    """在后台线程启动 API 服务器。返回线程对象。"""
    bind(memory, agents_info, session_dir=session_dir)

    def _run():
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    t = threading.Thread(target=_run, daemon=True, name="salon-api")
    t.start()
    return t
