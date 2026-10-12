"""本地导出文件导入：把 CSV / JSON / TXT 解析为统一记录结构。

统一记录结构（与 Workbuddy 输出的 chat_<date>.json 中的 records 一致）::

    {
        "contact": "张三",            # 联系人姓名
        "company": "云启科技",        # 公司（缺失则为空串）
        "msgs": [                     # 会话消息（按文件出现顺序）
            {"role": "user"|"contact", "text": "内容", "time": 1700000000.0},
            ...
        ],
        "time": 1700000000.0,         # 会话时间（取首条消息时间，缺失为 0.0）
    }

设计原则：字段缺失时使用安全默认值，不因个别字段缺失而整体报错；
只有当文件完全无法识别（如空文件、编码错误、无任何会话）时才抛 ValueError。
"""
import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 统一记录中的角色取值
ROLE_USER = "user"
ROLE_CONTACT = "contact"

# 视为「我/本人」的角色取值（其余一律归为 contact）
_USER_ROLES = {"user", "self", "我", "me", "本人", "自己", "from_me"}

# 会话分节行：如「联系人: 张三」「Contact: 张三」
_SECTION_RE = re.compile(r"^\s*(联系人|客户|姓名|contact|name)\s*[:：]\s*(.+?)\s*$", re.I)

# 时间字符串常见格式
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                 "%Y-%m-%d", "%Y/%m/%d")

# CSV/JSON 表头同义词 -> 统一字段名
_HEADER_SYNONYMS = {
    "contact": {"contact", "联系人", "客户", "name", "姓名", "who"},
    "company": {"company", "公司", "企业", "组织", "org"},
    "role": {"role", "角色", "方向", "direction", "speaker", "from"},
    "text": {"text", "内容", "消息", "message", "content", "msg", "正文"},
    "time": {"time", "时间", "timestamp", "日期", "date", "datetime"},
}


# ---------------- 通用工具 ----------------
def _decode(data: bytes) -> str:
    """按常见编码解码字节内容。

    功能：依次尝试 utf-8-sig / utf-8 / gb18030 解码，兼容 BOM 与中文导出。
    参数：data —— 文件原始字节。
    返回值：解码后的字符串；全部失败抛 ValueError。
    """
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别的文件编码（请使用 UTF-8 或 GBK）")


def _norm_role(raw: object) -> str:
    """把任意角色取值归一化为 user / contact。

    功能：把「我/self/本人」等归为 user，其余（含缺失）归为 contact。
    参数：raw —— 原始角色值。
    返回值：统一角色字符串（user 或 contact）。
    """
    val = str(raw or "").strip().lower()
    return ROLE_USER if val in _USER_ROLES else ROLE_CONTACT


def _parse_time(raw: object) -> float:
    """把时间字段解析为秒级浮点时间戳。

    功能：支持秒级数字时间戳与常见日期字符串，解析失败返回 0.0。
    参数：raw —— 原始时间值（数字或字符串）。
    返回值：秒级时间戳，无法解析时为 0.0。
    """
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return 0.0
    # 纯数字（含小数）按时间戳处理
    try:
        return float(text)
    except ValueError:
        pass
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def _norm_msg(raw: dict) -> dict:
    """把单条消息归一化为 {role, text, time}。

    功能：容错角色与时间字段，文本缺失用空串。
    参数：raw —— 原始消息字典。
    返回值：统一消息字典。
    """
    return {
        "role": _norm_role(raw.get("role")),
        "text": str(raw.get("text") or raw.get("content") or ""),
        "time": _parse_time(raw.get("time")),
    }


def _session(contact: str, company: str) -> dict:
    """新建一个空的会话记录。

    功能：构造统一记录结构，避免各处重复书写默认值。
    参数：contact —— 联系人；company —— 公司。
    返回值：统一记录字典。
    """
    return {"contact": contact, "company": company, "msgs": [], "time": 0.0}


def _finalize(rec: dict) -> dict:
    """收尾会话记录：用首条消息时间补全会话时间。

    功能：若会话 time 仍为 0.0，则取第一条消息的时间。
    参数：rec —— 会话记录。
    返回值：补全后的会话记录。
    """
    if not rec["time"] and rec["msgs"]:
        rec["time"] = rec["msgs"][0]["time"]
    return rec


def _merge_flat(rows: List[dict]) -> List[dict]:
    """把扁平行（每行一条消息）按 contact 合并为会话。

    功能：同一联系人的多行消息合并为一个会话，保持出现顺序。
    参数：rows —— 归一化后的扁平行（含 contact/company/role/text/time）。
    返回值：会话记录列表。
    """
    sessions: dict = {}
    order: List[str] = []
    for row in rows:
        contact = row.get("contact") or "未知联系人"
        rec = sessions.get(contact)
        if rec is None:
            rec = _session(contact, row.get("company") or "")
            sessions[contact] = rec
            order.append(contact)
        if not rec["company"] and row.get("company"):
            rec["company"] = row["company"]
        msg = {"role": _norm_role(row.get("role")), "text": str(row.get("text") or ""),
               "time": _parse_time(row.get("time"))}
        if msg["text"]:
            rec["msgs"].append(msg)
    return [_finalize(sessions[c]) for c in order if sessions[c]["msgs"]]


# ---------------- CSV ----------------
def _header_map(fieldnames: List[str]) -> dict:
    """建立「实际表头 -> 统一字段名」的映射。

    功能：兼容中英文表头与大小写差异，仅保留可识别的列。
    参数：fieldnames —— csv 读取到的表头列表。
    返回值：映射字典 {实际表头: 统一字段名}。
    """
    mapping = {}
    for name in fieldnames or []:
        key = str(name).strip().lower()
        for canon, syns in _HEADER_SYNONYMS.items():
            if key in syns:
                mapping[name] = canon
                break
    return mapping


def _parse_csv(text: str) -> List[dict]:
    """解析 CSV 内容为会话记录。

    功能：按表头映射读取各行并按 contact 合并为会话。
    参数：text —— CSV 文本。
    返回值：会话记录列表；无有效数据时抛 ValueError。
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头")
    hmap = _header_map(reader.fieldnames)
    rows = []
    for raw in reader:
        row = {}
        for col, val in raw.items():
            canon = hmap.get(col)
            if canon:
                row[canon] = val
        if not any(str(v or "").strip() for v in (raw.get(k) for k in raw)):
            continue  # 跳过全空行
        if row.get("text") or row.get("contact"):
            rows.append(row)
    records = _merge_flat(rows)
    if not records:
        raise ValueError("CSV 未解析到任何会话（请检查表头与内容）")
    return records


# ---------------- JSON ----------------
def _parse_json(text: str) -> List[dict]:
    """解析 JSON 内容为会话记录。

    功能：兼容 {"records":[...]}、顶层数组（会话式）与扁平数组三种形式。
    参数：text —— JSON 文本。
    返回值：会话记录列表；解析失败或无有效数据时抛 ValueError。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}")

    # 形式一：{"records": [...]}
    if isinstance(data, dict) and isinstance(data.get("records"), list):
        return _normalize_record_list(data["records"])

    # 形式二/三：顶层数组
    if isinstance(data, list):
        # 判定是否扁平形式：元素含 text 而无 msgs
        flat = [it for it in data if isinstance(it, dict)]
        if flat and all("msgs" not in it for it in flat):
            return _merge_flat(flat)
        return _normalize_record_list(flat)

    # 形式四：单个记录字典（含 msgs）
    if isinstance(data, dict) and isinstance(data.get("msgs"), list):
        return _normalize_record_list([data])

    raise ValueError("JSON 结构无法识别（需为 records 列表或记录数组）")


def _normalize_record_list(items: List[dict]) -> List[dict]:
    """归一化「会话式」记录列表。

    功能：每项含 contact/company/msgs，字段缺失时用安全默认值；缺 msgs 时按扁平处理。
    参数：items —— 原始记录列表。
    返回值：会话记录列表；无有效数据时抛 ValueError。
    """
    records = []
    for it in items:
        if not isinstance(it, dict):
            continue
        msgs = it.get("msgs")
        if not isinstance(msgs, list):
            # 退化为扁平行
            if it.get("text"):
                merged = _merge_flat([it])
                records.extend(merged)
            continue
        rec = _session(it.get("contact") or "未知联系人", it.get("company") or "")
        rec["msgs"] = [_norm_msg(m) for m in msgs if isinstance(m, dict)]
        rec["time"] = _parse_time(it.get("time"))
        if rec["msgs"]:
            records.append(_finalize(rec))
    if not records:
        raise ValueError("JSON 未解析到任何会话")
    return records


# ---------------- TXT ----------------
def _parse_txt(text: str) -> List[dict]:
    """解析 TXT 内容为会话记录。

    功能：识别「联系人: 姓名」行作为会话分节起点，其余非空行作为消息（默认 contact）。
    参数：text —— 纯文本内容。
    返回值：会话记录列表；完全无法识别时抛 ValueError。
    """
    records: List[dict] = []
    current: Optional[dict] = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _SECTION_RE.match(stripped)
        if m:
            current = _session(m.group(2).strip() or "未知联系人", "")
            records.append(current)
            continue
        if current is None:
            continue  # 首个分节前的说明文字忽略
        current["msgs"].append({"role": ROLE_CONTACT, "text": stripped, "time": 0.0})
    records = [_finalize(r) for r in records if r["msgs"]]
    if not records:
        raise ValueError("TXT 未识别到会话分节（需包含形如「联系人: 张三」的行）")
    return records


# ---------------- 统一入口 ----------------
def parse_bytes(filename: str, data: bytes) -> List[dict]:
    """按文件扩展名分派解析，返回统一记录结构。

    功能：支持 .csv / .json / .txt 三种本地导出格式；解析失败抛 ValueError。
    参数：filename —— 文件名（用于判断类型）；data —— 文件原始字节。
    返回值：统一记录结构列表（每个元素为一个会话）。
    """
    ext = Path(filename or "").suffix.lower()
    text = _decode(data)
    if ext == ".csv":
        return _parse_csv(text)
    if ext == ".json":
        return _parse_json(text)
    if ext == ".txt":
        return _parse_txt(text)
    raise ValueError(f"不支持的文件类型：{ext or '（无扩展名）'}（仅支持 CSV/JSON/TXT）")