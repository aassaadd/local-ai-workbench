"""协调员上下文 · 分层记忆与压缩。

三层记忆（对标长上下文产品的工程化处理方式）：
  1. 长期项目档案 Profile：结构化的事实/结论/待办/偏好，跨会话持久化，让协调员能「跟进项目」；
  2. 中期滚动摘要 Summary：超出阈值时把较早轮次压成一段摘要；
  3. 近期原文窗口 Recent：始终保留最近 CONTEXT_KEEP_TURNS 轮原文。

上下文装配时把「system + 项目档案 + 摘要」作为稳定前缀（顺序与内容稳定），
便于 oMLX / vLLM 等推理服务命中前缀 KV 缓存（对标上下文硬盘缓存的思路），
减少重复计算；最近原文追加在后，保证近端上下文精确。

未配置本地模型时，档案抽取与摘要均回退为规则式实现，功能不受影响。
"""
import hashlib
import json
import re
from typing import List

from . import config, db, llm

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ACK_TEXTS = {"收到需求，正在拆解任务…"}
_TODO_KW = ("待办", "记得", "需要", "下一步", "帮我", "别忘了")
_PREF_KW = ("我喜欢", "我习惯", "以后", "每次", "偏好", "叫我", "不要在")

EMPTY_PROFILE = {"goal": "", "facts": [], "todos": [], "prefs": []}
_MAX_FACTS = 8
_MAX_TODOS = 8
_MAX_PREFS = 6
_last_stats: dict = {}


def estimate_tokens(text: str) -> int:
    """粗略估算 token：中日韩按 1 字 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = max(len(text) - cjk, 0)
    return int(cjk + other / 4) + 1


def _messages_tokens(messages: List[dict]) -> int:
    return sum(estimate_tokens(m.get("content", "")) for m in messages)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + "…" + text[-limit // 3:]


def _dedup(items: List[str], limit: int, width: int = 60) -> List[str]:
    out: List[str] = []
    for it in items:
        it = _truncate(it.strip(), width)
        if it and it not in out:
            out.append(it)
    return out[-limit:]


# ---------------- 对话轮次 ----------------
def _load_turns(project: str) -> List[dict]:
    turns: List[dict] = []
    for m in db.get_chat_turns(project):
        agent = m.get("from_agent")
        content = (m.get("content") or "").strip()
        if agent not in ("user", "coordinator") or not content:
            continue
        if content in _ACK_TEXTS:
            continue
        role = "user" if agent == "user" else "assistant"
        turn = {"role": role, "content": content, "ts": m.get("timestamp", 0.0)}
        if role == "assistant" and turns and turns[-1]["role"] == "assistant":
            turns[-1] = turn
        else:
            turns.append(turn)
    return turns


# ---------------- 项目档案（长期事实） ----------------
def _rule_profile(prev: dict, turns: List[dict]) -> dict:
    prof = {k: (list(prev.get(k, [])) if isinstance(prev.get(k), list) else prev.get(k) or "")
            for k in EMPTY_PROFILE}
    goal = prev.get("goal", "") or ""
    facts = list(prev.get("facts", []))
    todos = list(prev.get("todos", []))
    prefs = list(prev.get("prefs", []))

    for t in turns:
        text = t["content"].replace("\n", " ")
        if not goal and t["role"] == "user":
            goal = _truncate(text, 60)
        if t["role"] == "assistant":
            # 规则引擎/占位回复不沉淀为结论
            if len(text) >= 4 and "规则引擎回复" not in text and "可以试试对我说" not in text:
                facts.append(text)
        for seg in re.split(r"[。；;\n]", text):
            seg = seg.strip()
            if t["role"] == "user" and any(k in seg for k in _TODO_KW):
                todos.append(seg)
            if t["role"] == "user" and any(k in seg for k in _PREF_KW):
                prefs.append(seg)

    prof["goal"] = goal
    prof["facts"] = _dedup(facts, _MAX_FACTS, 70)
    prof["todos"] = _dedup(todos, _MAX_TODOS, 60)
    prof["prefs"] = _dedup(prefs, _MAX_PREFS, 60)
    return prof


async def _llm_profile(prev: dict, turns: List[dict]) -> dict:
    dialogue = "\n".join(
        f"{'用户' if t['role'] == 'user' else '协调员'}：{_truncate(t['content'], 150)}"
        for t in turns
    )
    sys = ("你是项目记忆抽取器。从对话中抽取结构化记忆，只输出 JSON，字段："
           '{"goal": "项目目标一句话", "facts": ["关键结论/事实"], '
           '"todos": ["待办"], "prefs": ["用户偏好"]}。没有的字段留空数组，每条不超过 40 字。')
    usr = f"【已有档案】{json.dumps(prev, ensure_ascii=False)}\n【新增对话】\n{dialogue}"
    reply = await llm.chat([{"role": "system", "content": sys},
                            {"role": "user", "content": usr}], temperature=0.1)
    if not reply:
        return {}
    try:
        obj = json.loads(reply[reply.find("{"):reply.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {}
    merged = _rule_profile(prev, [])  # 以既有档案打底
    if isinstance(obj.get("goal"), str) and obj["goal"].strip():
        merged["goal"] = _truncate(obj["goal"].strip(), 60)
    for key, limit, width in (("facts", _MAX_FACTS, 70), ("todos", _MAX_TODOS, 60),
                              ("prefs", _MAX_PREFS, 60)):
        val = obj.get(key)
        if isinstance(val, list):
            merged[key] = _dedup(merged[key] + [str(v) for v in val], limit, width)
    return merged


async def _extract_profile(prev: dict, turns: List[dict]) -> dict:
    if not turns:
        return _rule_profile(prev, [])
    if llm.available():
        prof = await _llm_profile(prev, turns)
        if prof:
            return prof
    return _rule_profile(prev, turns)


def render_profile(prof: dict) -> str:
    if not prof:
        return ""
    lines = []
    if prof.get("goal"):
        lines.append(f"项目目标：{prof['goal']}")
    if prof.get("facts"):
        lines.append("关键结论：" + "；".join(prof["facts"]))
    if prof.get("todos"):
        lines.append("待办事项：" + "；".join(prof["todos"]))
    if prof.get("prefs"):
        lines.append("用户偏好：" + "；".join(prof["prefs"]))
    if not lines:
        return ""
    return _truncate("【项目档案·长期记忆】\n" + "\n".join(lines),
                     config.CONTEXT_PROFILE_MAX_CHARS + 40)


# ---------------- 摘要 ----------------
def _summary_messages(prev: str, older: List[dict]) -> List[dict]:
    dialogue = "\n".join(
        f"{'用户' if t['role'] == 'user' else '协调员'}：{_truncate(t['content'], 200)}"
        for t in older
    )
    sys = ("你是对话压缩器。把多轮对话压缩成简洁的事实性摘要，"
           "保留用户偏好与身份、任务结论、关键数据、待办事项；"
           f"不要超过 {config.CONTEXT_SUMMARY_MAX_CHARS} 字。")
    usr = (f"【已有摘要】\n{prev}\n\n" if prev else "") + \
          f"【新增对话】\n{dialogue}\n\n请输出合并后的摘要。"
    return [{"role": "system", "content": sys}, {"role": "user", "content": usr}]


def _fallback_summary(prev: str, older: List[dict]) -> str:
    parts = [prev] if prev else []
    parts.append("；".join(_truncate(t["content"], 80) for t in older))
    return _truncate(" | ".join(p for p in parts if p), config.CONTEXT_SUMMARY_MAX_CHARS)


async def _summarize(prev: str, older: List[dict]) -> str:
    reply = await llm.chat(_summary_messages(prev, older), temperature=0.2)
    if reply and reply.strip():
        return _truncate(reply.strip(), config.CONTEXT_SUMMARY_MAX_CHARS * 2)
    return _fallback_summary(prev, older)


# ---------------- 上下文装配 ----------------
def _prefix(messages: List[dict]) -> List[dict]:
    return [m for m in messages if m["role"] == "system"]


def _prefix_hash(messages: List[dict]) -> str:
    blob = "\n".join(m["content"] for m in _prefix(messages))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _context_plan(messages: List[dict], profile: str, summary: str) -> List[dict]:
    sys_t = estimate_tokens(messages[0]["content"]) if messages else 0
    prof_t = estimate_tokens(profile)
    summ_t = estimate_tokens(summary)
    recent = [m for m in messages if m["role"] != "system"]
    return [
        {"tier": "system", "tokens": sys_t, "desc": "协调员系统提示词"},
        {"tier": "profile", "tokens": prof_t, "desc": "长期项目档案"},
        {"tier": "summary", "tokens": summ_t, "desc": "中期滚动摘要"},
        {"tier": "recent", "tokens": _messages_tokens(recent),
         "desc": f"近期原文 {len(recent)} 轮"},
    ]


async def build_context(project: str, system_prompt: str) -> dict:
    """装配本次请求的 messages，并在需要时更新摘要/项目档案。"""
    mem = db.get_memory(project)
    summary = mem["summary"]
    prof_rec = db.get_profile(project)
    prof = prof_rec["data"] or dict(EMPTY_PROFILE)
    prof_updated_at = prof_rec["updated_at"]
    all_turns = _load_turns(project)
    turns = list(all_turns)
    max_tokens = config.CONTEXT_MAX_TOKENS
    keep = max(config.CONTEXT_KEEP_TURNS, 1)
    profile_updated = False

    def prefix_msgs():
        msgs = [{"role": "system", "content": system_prompt}]
        block = render_profile(prof)
        if block:
            msgs.append({"role": "system", "content": block})
        if summary:
            msgs.append({"role": "system", "content": f"【历史记忆摘要】\n{summary}"})
        return msgs

    tokens_before = _messages_tokens(prefix_msgs() + turns)
    compressed = False
    older: List[dict] = []

    if tokens_before > max_tokens and len(turns) > keep:
        recent = turns[-keep:]
        older = turns[:-keep]
        while older and _messages_tokens(prefix_msgs() + recent) > max_tokens and len(recent) > 1:
            older.insert(0, recent.pop(0))
        summary = await _summarize(summary, older)
        db.save_memory(project, summary, older[-1]["ts"])
        turns = recent
        compressed = True

    # 长期档案：首次有对话时建立；压缩时沉淀；此后每积累若干轮新对话刷新一次
    new_turns = [t for t in all_turns if t["ts"] > prof_updated_at]
    if older:
        src = older
    elif not prof.get("goal") and len(all_turns) >= 2:
        src = new_turns or all_turns
    elif len(new_turns) >= config.CONTEXT_PROFILE_REFRESH_TURNS:
        src = new_turns
    else:
        src = []
    if src:
        new_prof = await _extract_profile(prof, src)
        if new_prof != prof:
            db.save_profile(project, new_prof)
            prof = new_prof
            profile_updated = True

    messages = prefix_msgs() + turns
    plan = _context_plan(messages, render_profile(prof), summary)
    stats = {
        "turns": len(turns),
        "tokens_before": tokens_before,
        "tokens_after": _messages_tokens(messages),
        "max_tokens": max_tokens,
        "keep_turns": keep,
        "compressed": compressed,
        "profile_updated": profile_updated,
        "summary_chars": len(summary),
        "prefix_hash": _prefix_hash(messages),
        "cache_stable": config.CONTEXT_STABLE_PREFIX,
        "plan": plan,
    }
    _last_stats[project] = stats
    return {"messages": messages, "summary": summary, "profile": prof,
            "stats": stats, "plan": plan}


# ---------------- 对外状态 ----------------
def get_state(project: str) -> dict:
    mem = db.get_memory(project)
    prof = db.get_profile(project)
    return {
        "summary": mem["summary"],
        "compressed_upto": mem["compressed_upto"],
        "updated_at": mem["updated_at"],
        "profile": prof["data"] or dict(EMPTY_PROFILE),
        "profile_rendered": render_profile(prof["data"] or {}),
        "profile_updated_at": prof["updated_at"],
        "context_max_tokens": config.CONTEXT_MAX_TOKENS,
        "keep_turns": config.CONTEXT_KEEP_TURNS,
        "cache_stable": config.CONTEXT_STABLE_PREFIX,
        "last": _last_stats.get(project),
    }


def update_profile_manual(project: str, data: dict) -> dict:
    """人工编辑长期档案（记忆可编辑面板）。"""
    clean = dict(EMPTY_PROFILE)
    clean["goal"] = _truncate(str(data.get("goal", "") or ""), 60)
    for key, limit, width in (("facts", _MAX_FACTS, 70), ("todos", _MAX_TODOS, 60),
                              ("prefs", _MAX_PREFS, 60)):
        val = data.get(key)
        if isinstance(val, str):
            val = [x.strip() for x in re.split(r"[\n；;]", val) if x.strip()]
        clean[key] = _dedup([str(v) for v in (val or [])], limit, width)
    db.save_profile(project, clean)
    return clean


def clear(project: str) -> None:
    db.clear_memory(project)
    _last_stats.pop(project, None)
