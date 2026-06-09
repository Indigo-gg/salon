"""档案导出模块 — 将对话转录导出为 Markdown / HTML / PDF。

样式风格：回放室对话流，轮次分隔 + 角色卡片 + 可折叠推理过程。
"""

from __future__ import annotations

import html
import json
from pathlib import Path

# 角色配色（用于 HTML 导出，匹配系统像素风格）
_ROLE_COLORS = {
    "moderator": "#e5a937",   # gold
    "participant": "#4eb8ba", # cyan
    "scribe": "#7bb56c",      # green
    "system": "#a2a2b5",      # muted
    "human": "#c95a66",       # red
}

_SPEECH_TYPE_LABELS = {
    "Extend": "延伸",
    "Dissent": "反驳",
    "New_Angle": "新角度",
    "Clarify": "澄清",
    "Ask": "提问",
    "Pass": "跳过",
    "system_notice": "通知",
    "question": "提问",
}


def _load_messages(session_dir: str | Path) -> list[dict]:
    """从 session 目录加载 transcript JSONL。"""
    p = Path(session_dir) / "transcript.jsonl"
    if not p.exists():
        return []
    messages = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages


def _filter_speech(messages: list[dict]) -> list[dict]:
    """过滤出正式发言（排除 intent）。"""
    return [m for m in messages if m.get("speech_type") != "intent"]


# ---------------------------------------------------------------------------
# Markdown 导出
# ---------------------------------------------------------------------------

def export_markdown(
    messages: list[dict],
    topic: str = "",
    session_id: str = "",
    include_reasoning: bool = True,
) -> str:
    """生成 Markdown 格式的对话导出。"""
    lines = []

    # 标题
    if topic:
        lines.append(f"# {topic}\n")
    if session_id:
        lines.append(f"**会话 ID**: `{session_id}`\n")
    lines.append("---\n")

    current_round = None
    for msg in messages:
        r = msg.get("round", 0)
        name = msg.get("agent_name", "?")
        role = msg.get("agent_role", "participant")
        content = msg.get("content", "")
        speech_type = msg.get("speech_type", "")
        review = msg.get("review")
        thought = msg.get("thought")
        mentions = msg.get("mentions", [])

        # 轮次分隔
        if r != current_round:
            current_round = r
            lines.append(f"\n## 第 {r} 轮\n")

        # 角色标签
        type_label = _SPEECH_TYPE_LABELS.get(speech_type, speech_type)
        role_tag = f"[{type_label}]" if type_label else ""
        mention_tag = f" → {', '.join(mentions)}" if mentions else ""

        if role == "system":
            lines.append(f"> **📢 {name}**: {content}\n")
        else:
            lines.append(f"### {name} {role_tag}{mention_tag}\n")
            lines.append(f"{content}\n")

            # 工具调用记录（可折叠）
            tool_calls = msg.get("metadata", {}).get("tool_calls", [])
            if tool_calls:
                lines.append(f"\n<details><summary>📎 引用来源（{len(tool_calls)} 次工具调用）</summary>\n")
                for tc in tool_calls:
                    tool_name = tc.get("tool", "?")
                    tool_input = tc.get("input", {})
                    tool_output = tc.get("output", "")
                    input_str = ", ".join(tool_input.get("queries", [])) if "queries" in tool_input else str(tool_input)
                    lines.append(f"🔍 **{tool_name}**：`{input_str}`\n")
                    if tool_output:
                        lines.append(f"> {tool_output}\n")
                    lines.append("")
                lines.append("\n</details>\n")

            # 推理过程（可折叠）
            if include_reasoning and (review or thought):
                lines.append("\n<details><summary>💭 推理过程</summary>\n")
                if review:
                    lines.append(f"**review**: {review}\n")
                if thought:
                    lines.append(f"**thought**: {thought}\n")
                lines.append("\n</details>\n")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML 导出
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #2b2b36; --panel-bg: #363644; --border: #1e1e26;
    --text: #e8e8e2; --text-muted: #a2a2b5;
    --gold: #e5a937; --cyan: #4eb8ba; --red: #c95a66; --green: #7bb56c;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.7;
    padding: 24px;
  }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  .header {{
    text-align: center; padding: 28px 20px; margin-bottom: 24px;
    background: var(--panel-bg);
    border: 4px solid var(--border); border-radius: 2px;
    box-shadow: 4px 4px 0px rgba(0,0,0,0.4);
  }}
  .header h1 {{ font-size: 24px; color: var(--gold); margin-bottom: 8px; text-shadow: 2px 2px 0 var(--border); }}
  .header .meta {{ font-size: 12px; color: var(--text-muted); }}
  .round-divider {{
    text-align: center; margin: 28px 0 16px; position: relative;
  }}
  .round-divider::before {{
    content: ""; position: absolute; left: 0; right: 0; top: 50%;
    border-top: 2px dashed var(--border);
  }}
  .round-divider span {{
    background: var(--bg); padding: 0 16px; position: relative;
    font-size: 12px; color: var(--gold); font-weight: 600;
    letter-spacing: 2px;
  }}
  .msg {{
    background: var(--panel-bg); border-radius: 2px; padding: 14px 16px;
    margin-bottom: 10px; border-left: 4px solid var(--cyan);
    border: 4px solid var(--border); border-left: 4px solid var(--cyan);
    box-shadow: 4px 4px 0px rgba(0,0,0,0.3);
  }}
  .msg.system {{
    border-left-color: var(--gold); font-style: italic;
    font-size: 13px; color: var(--gold);
  }}
  .msg-header {{
    display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap;
  }}
  .agent-name {{ font-weight: bold; font-size: 14px; }}
  .type-tag {{
    font-size: 10px; padding: 1px 6px;
    background: var(--border); color: var(--text-muted);
    border: 1px solid var(--text-muted);
  }}
  .mention-tag {{ font-size: 11px; color: var(--text-muted); }}
  .msg-content {{ font-size: 14px; white-space: pre-wrap; word-break: break-word; }}
  details {{ margin-top: 8px; font-size: 12px; color: var(--text-muted); }}
  details summary {{ cursor: pointer; user-select: none; }}
  details .reasoning {{
    margin-top: 4px; padding: 8px; background: var(--border);
    white-space: pre-wrap; font-size: 12px; line-height: 1.5;
  }}
  .footer {{
    text-align: center; padding: 24px; font-size: 11px; color: var(--text-muted);
    border-top: 2px dashed var(--border); margin-top: 24px;
  }}
  @media print {{
    body {{ padding: 0; background: #fff; color: #000; }}
    .header {{ background: #f0f0f0; color: #000; border-color: #ccc; box-shadow: none; }}
    .msg {{ box-shadow: none; border: 1px solid #ddd; }}
    details[open] .reasoning {{ background: #f9f9f9; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{title}</h1>
    <div class="meta">{meta}</div>
  </div>
  {body}
  <div class="footer">Salon — 多角色对话系统 · 导出于 {export_time}</div>
</div>
</body>
</html>
"""


def export_html(
    messages: list[dict],
    topic: str = "",
    session_id: str = "",
    include_reasoning: bool = True,
) -> str:
    """生成自包含 HTML 格式的对话导出。"""
    title = html.escape(topic) if topic else "对话记录"
    meta_parts = []
    if session_id:
        meta_parts.append(f"会话 {html.escape(session_id)}")
    total_rounds = max((m.get("round", 0) for m in messages), default=0)
    if total_rounds:
        meta_parts.append(f"{total_rounds} 轮")
    meta_parts.append(f"{len(messages)} 条发言")
    meta = " · ".join(meta_parts)

    from datetime import datetime
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    body_parts = []
    current_round = None
    for msg in messages:
        r = msg.get("round", 0)
        name = msg.get("agent_name", "?")
        role = msg.get("agent_role", "participant")
        content = msg.get("content", "")
        speech_type = msg.get("speech_type", "")
        review = msg.get("review")
        thought = msg.get("thought")
        mentions = msg.get("mentions", [])

        # 轮次分隔
        if r != current_round:
            current_round = r
            body_parts.append(
                f'<div class="round-divider"><span>第 {r} 轮</span></div>'
            )

        color = _ROLE_COLORS.get(role, _ROLE_COLORS["participant"])
        type_label = _SPEECH_TYPE_LABELS.get(speech_type, speech_type)
        escaped_content = html.escape(content)

        if role == "system":
            body_parts.append(
                f'<div class="msg system">'
                f'<div class="msg-header"><span class="agent-name">📢 {html.escape(name)}</span></div>'
                f'<div class="msg-content">{escaped_content}</div>'
                f'</div>'
            )
        else:
            mention_html = ""
            if mentions:
                mention_html = f'<span class="mention-tag">→ {html.escape(", ".join(mentions))}</span>'

            reasoning_html = ""
            if include_reasoning and (review or thought):
                parts = []
                if review:
                    parts.append(f"<b>review:</b><br>{html.escape(review)}")
                if thought:
                    parts.append(f"<b>thought:</b><br>{html.escape(thought)}")
                reasoning_content = "<br><br>".join(parts)
                reasoning_html = (
                    f'<details><summary>💭 推理过程</summary>'
                    f'<div class="reasoning">{reasoning_content}</div>'
                    f'</details>'
                )

            # 工具调用记录
            tool_calls_html = ""
            tool_calls = msg.get("metadata", {}).get("tool_calls", [])
            if tool_calls:
                tc_parts = []
                for tc in tool_calls:
                    tool_name = tc.get("tool", "?")
                    tool_input = tc.get("input", {})
                    tool_output = tc.get("output", "")
                    input_str = ", ".join(tool_input.get("queries", [])) if "queries" in tool_input else str(tool_input)
                    tc_parts.append(
                        f'<div style="margin:4px 0;padding:6px 8px;background:rgba(255,255,255,0.03);border-left:2px solid var(--text-muted);border-radius:4px;">'
                        f'<div style="color:var(--text-muted);font-size:11px;margin-bottom:3px;">🔍 {html.escape(tool_name)}：'
                        f'<code style="font-size:10px;background:rgba(255,255,255,0.05);padding:1px 4px;border-radius:2px;">{html.escape(input_str)}</code></div>'
                        f'<div style="color:var(--text-muted);font-size:11px;line-height:1.4;white-space:pre-wrap;">{html.escape(tool_output)}</div>'
                        f'</div>'
                    )
                tc_content = "".join(tc_parts)
                tool_calls_html = (
                    f'<details style="margin-top:6px;font-size:12px;">'
                    f'<summary style="color:var(--text-muted);cursor:pointer;font-size:11px;">📎 引用来源（{len(tool_calls)} 次工具调用）</summary>'
                    f'{tc_content}'
                    f'</details>'
                )

            body_parts.append(
                f'<div class="msg" style="border-left-color: {color}">'
                f'<div class="msg-header">'
                f'<span class="agent-name" style="color: {color}">{html.escape(name)}</span>'
                f'<span class="type-tag">{html.escape(type_label)}</span>'
                f'{mention_html}'
                f'</div>'
                f'<div class="msg-content">{escaped_content}</div>'
                f'{tool_calls_html}'
                f'{reasoning_html}'
                f'</div>'
            )

    body = "\n".join(body_parts)
    return _HTML_TEMPLATE.format(
        title=title,
        meta=meta,
        body=body,
        export_time=export_time,
    )


# ---------------------------------------------------------------------------
# PDF 导出
# ---------------------------------------------------------------------------

def export_pdf(html_content: str) -> bytes | None:
    """将 HTML 转换为 PDF。需要 weasyprint，未安装则返回 None。"""
    try:
        import weasyprint
        return weasyprint.HTML(string=html_content).write_pdf()
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# 便捷函数：从 session 目录直接导出
# ---------------------------------------------------------------------------

def export_session(
    session_dir: str | Path,
    fmt: str = "html",
    include_reasoning: bool = True,
) -> tuple[str | bytes, str, str]:
    """从 session 目录导出对话。

    返回 (content, filename, media_type)。
    """
    session_dir = Path(session_dir)
    messages = _load_messages(session_dir)
    messages = _filter_speech(messages)

    # 读取 session 元数据
    meta_path = session_dir / "metadata.json"
    topic = ""
    session_id = session_dir.name
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        topic = meta.get("topic", "")

    if fmt == "md":
        content = export_markdown(messages, topic, session_id, include_reasoning)
        return content, f"salon_{session_id}.md", "text/markdown"

    elif fmt == "html":
        content = export_html(messages, topic, session_id, include_reasoning)
        return content, f"salon_{session_id}.html", "text/html"

    elif fmt == "pdf":
        html_content = export_html(messages, topic, session_id, include_reasoning)
        pdf_bytes = export_pdf(html_content)
        if pdf_bytes:
            return pdf_bytes, f"salon_{session_id}.pdf", "application/pdf"
        # fallback: 返回 HTML
        return html_content, f"salon_{session_id}.html", "text/html"

    else:
        raise ValueError(f"Unsupported format: {fmt}. Use 'md', 'html', or 'pdf'.")
