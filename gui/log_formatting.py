"""演奏日志展示格式化纯函数:无 Qt 依赖,可被 unittest 无 QApplication 直接覆盖。

消费 core 解析所得的事件 dict / 会话信息 dict,产出时间线行文本与摘要键值对;
字段缺失输出占位而非报错,内部异常降级为"时间 + [未知事件]"行,全部函数不抛出。
"""

from datetime import datetime

from gui.log_texts import (
    ANOMALY_MARK,
    EVENT_ROW_TEMPLATES,
    EVENT_TYPE_LABELS,
    FOCUS_LOST_TEXT,
    FOCUS_REGAINED_TEXT,
    NOTE_FAIL_TEXT,
    NOTE_SUCCESS_TEXT,
    PLACEHOLDER_UNKNOWN,
    SESSION_END_LABEL,
    SESSION_START_LABEL,
    SOURCE_LABELS,
    SUMMARY_LABELS,
    TEXT_NO,
    TEXT_YES,
)

# 会话头尾行的专用标签(不属于六类事件,单独映射)
_SESSION_LINE_LABELS = {
    "session_start": SESSION_START_LABEL,
    "session_end": SESSION_END_LABEL,
}


def format_row_time(timestamp) -> str:
    """Unix 秒 -> "HH:MM:SS";无效输入输出占位。"""
    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%H:%M:%S")
    except Exception:
        return PLACEHOLDER_UNKNOWN


def format_file_size(size_bytes) -> str:
    """字节 -> "12.3 KB" 可读格式;无效输入输出占位。"""
    try:
        n = float(size_bytes)
    except Exception:
        return PLACEHOLDER_UNKNOWN
    if n < 0:
        return PLACEHOLDER_UNKNOWN
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def format_completion(completed, total) -> str:
    """"18/20";两值均 0(含缺失) -> 占位。"""
    try:
        c, t = int(completed), int(total)
    except Exception:
        return PLACEHOLDER_UNKNOWN
    if c == 0 and t == 0:
        return PLACEHOLDER_UNKNOWN
    return f"{c}/{t}"


def format_anomaly_flag(count) -> str:
    """0 -> "";>0 -> "⚠ n";无效输入按 0 处理。"""
    try:
        n = int(count)
    except Exception:
        return ""
    return ANOMALY_MARK.format(n=n) if n > 0 else ""


def _join_or_unknown(values) -> str:
    """列表字段拼接;空列表输出占位。"""
    try:
        joined = ", ".join(str(v) for v in values)
    except Exception:
        return PLACEHOLDER_UNKNOWN
    return joined if joined else PLACEHOLDER_UNKNOWN


def _event_info(event: dict, etype: str) -> str:
    """按类型模板拼装事件关键信息(不含时间与标签前缀)。"""
    if etype == "note":
        try:
            dev = float(event.get("deviation_ms", 0.0))
            deviation = f"{dev:.1f}"
        except Exception:
            deviation = PLACEHOLDER_UNKNOWN
        success = event.get("success")
        if success is None:
            result = PLACEHOLDER_UNKNOWN
        else:
            result = NOTE_SUCCESS_TEXT if success else NOTE_FAIL_TEXT
        text = EVENT_ROW_TEMPLATES[etype].format(
            notes=_join_or_unknown(event.get("notes") or []),
            keys=_join_or_unknown(event.get("keys") or []),
            deviation=deviation,
            result=result,
        )
    elif etype == "focus":
        lost = event.get("event", "lost") == "lost"
        if lost:
            title = str(event.get("window_title") or PLACEHOLDER_UNKNOWN)
            text = f"{FOCUS_LOST_TEXT}{title}"
        else:
            text = FOCUS_REGAINED_TEXT
        return text
    elif etype == "control":
        params = event.get("params")
        text = EVENT_ROW_TEMPLATES[etype].format(
            action=str(event.get("action") or PLACEHOLDER_UNKNOWN),
            params=str(params) if params else "",
        ).rstrip()
        return text
    elif etype == "external_input":
        source = str(event.get("source") or PLACEHOLDER_UNKNOWN)
        text = EVENT_ROW_TEMPLATES[etype].format(
            vk_code=event.get("vk_code", PLACEHOLDER_UNKNOWN),
            source=SOURCE_LABELS.get(source, source),
        )
    elif etype == "modifier_anomaly":
        text = EVENT_ROW_TEMPLATES[etype].format(
            modifier=str(event.get("modifier") or PLACEHOLDER_UNKNOWN),
            expected=event.get("expected", PLACEHOLDER_UNKNOWN),
            actual=event.get("actual", PLACEHOLDER_UNKNOWN),
        )
    elif etype == "env":
        details = event.get("details")
        text = EVENT_ROW_TEMPLATES[etype].format(
            env_event=str(event.get("event") or PLACEHOLDER_UNKNOWN),
            details=str(details) if details else "",
        ).rstrip()
        return text
    elif etype == "session_start":
        text = EVENT_ROW_TEMPLATES[etype].format(
            score_name=str(event.get("score_name") or PLACEHOLDER_UNKNOWN),
            bpm=event.get("bpm", PLACEHOLDER_UNKNOWN),
            note_count=event.get("note_count", PLACEHOLDER_UNKNOWN),
        )
    elif etype == "session_end":
        text = EVENT_ROW_TEMPLATES[etype].format(
            completed=event.get("completed", PLACEHOLDER_UNKNOWN),
            total=event.get("total", PLACEHOLDER_UNKNOWN),
            events_count=event.get("events_count", PLACEHOLDER_UNKNOWN),
        )
    else:
        return PLACEHOLDER_UNKNOWN
    return text


def format_event_row(event: dict) -> str:
    """单个事件 dict -> 时间线行文本 "HH:MM:SS [类型标签] 关键信息"。

    非法 type 或字段缺失一律走占位分支;内部异常降级为"时间 + [未知事件]"行,永不抛出。
    会话头尾行使用专用标签([会话开始]/[会话结束])。
    """
    ts = format_row_time(event.get("timestamp") if isinstance(event, dict) else None)
    try:
        etype = event.get("type", "") if isinstance(event, dict) else ""
        label = EVENT_TYPE_LABELS.get(etype) or _SESSION_LINE_LABELS.get(etype)
        if label is None:
            return f"{ts} [未知事件]"
        info = _event_info(event, etype)
        return f"{ts} [{label}] {info}".rstrip()
    except Exception:
        return f"{ts} [未知事件]"


def format_summary_pairs(info: dict) -> list[tuple[str, str]]:
    """get_session_info 结果 -> 摘要键值对列表(供详情视图摘要卡渲染)。

    键顺序即渲染顺序;缺失字段输出占位,函数不抛出。
    """
    pairs: list[tuple[str, str]] = []
    if not isinstance(info, dict):
        return pairs
    get = info.get
    for key, label in SUMMARY_LABELS.items():
        try:
            if key == "score_name":
                value = str(get("score_name") or PLACEHOLDER_UNKNOWN)
            elif key == "session_id":
                value = str(get("session_id") or PLACEHOLDER_UNKNOWN)
            elif key == "bpm":
                bpm = get("bpm", 0)
                value = PLACEHOLDER_UNKNOWN if not bpm else str(bpm)
            elif key in ("started_at", "ended_at"):
                value = str(get(key) or PLACEHOLDER_UNKNOWN)
            elif key == "completion":
                value = format_completion(get("completed", 0), get("total", 0))
            elif key == "stopped_early":
                value = TEXT_YES if get("stopped_early") else TEXT_NO
            else:  # events_count
                count = get("events_count", 0)
                value = PLACEHOLDER_UNKNOWN if not count else str(count)
        except Exception:
            value = PLACEHOLDER_UNKNOWN
        pairs.append((label, value))
    return pairs