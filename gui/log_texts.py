"""演奏日志前端展示文案常量组:全部界面文案的唯一存放处(spec 4.4)。

对齐 gui/disclaimer.py 顶部常量组模式:布局代码只引用常量,禁止内联硬编码文案。
模板占位符统一采用 str.format 具名参数({n} / {m} / {path});模块仅标准库、零 Qt 依赖。
"""

# ---------- 导航与页面标题 ----------

NAV_LOG_TEXT = "演奏记录"
LOG_PAGE_TITLE = "演奏记录"
LOG_PAGE_SUBTITLE = "每次演奏的过程、结果与异常回溯"

# ---------- 记录列表 ----------

LOG_TABLE_HEADERS = ["曲名", "开始时间", "时长", "完成度", "异常", "大小"]
LOG_EMPTY_TEXT = "暂无演奏记录"
LOG_LOADING_TEXT = "正在加载演奏记录…"

# ---------- 按钮文字 ----------

BTN_VIEW_DETAIL_TEXT = "查看详情"
BTN_EXPORT_TEXT = "导出选中"
BTN_DELETE_TEXT = "删除选中"
BTN_BACK_TEXT = "返回列表"
BTN_LOAD_MORE_TEXT = "加载更多"

# ---------- 导出 ----------

EXPORT_FORMAT_TITLE = "导出演奏记录"
EXPORT_FORMAT_LABEL = "导出格式"
EXPORT_FORMAT_ITEMS = [
    ("jsonl", "JSONL(原始事件流)"),
    ("csv", "CSV(音符数据表)"),
    ("markdown", "Markdown(摘要报告)"),
]
EXPORT_ALL_FILTER_TEXT = "全部"
EXPORT_SUCCESS_TITLE = "导出成功"
EXPORT_SUCCESS_TEXT = "导出成功：{path}"
EXPORT_FAIL_TITLE = "导出失败"
EXPORT_FAIL_TEXT = "导出失败，请检查磁盘空间与权限"
EXPORT_SELECT_ONE_TITLE = "无法导出"
EXPORT_SELECT_ONE_TEXT = "导出仅支持单条记录，请只勾选一条"

# ---------- 删除 ----------

DELETE_CONFIRM_TITLE = "删除演奏记录"
DELETE_CONFIRM_BODY = "确认删除选中的 {n} 条演奏记录？删除后不可恢复"
DELETE_DONE_TITLE = "删除完成"
DELETE_DONE_TEXT = "已删除 {n} 条演奏记录"
DELETE_PARTIAL_TEXT = "已删除 {n} 条，{m} 条删除失败(可能被占用)"

# ---------- 自动清理与加载 ----------

CLEANUP_DONE_TITLE = "自动清理"
CLEANUP_DONE_TEXT = "自动清理完成：删除 {n} 个文件，释放 {m} MB"
LOAD_ERROR_TITLE = "加载失败"
LOAD_ERROR_TEXT = "演奏记录加载失败，请重试"

# ---------- 占位与通用词 ----------

PLACEHOLDER_UNKNOWN = "未知"
TEXT_YES = "是"
TEXT_NO = "否"
ANOMALY_MARK = "⚠ {n}"
ANOMALY_NONE_MARK = "-"

# ---------- 事件类型中文标签(六类映射,集中定义供记录页与详情视图共用) ----------

EVENT_TYPE_LABELS = {
    "note": "音符演奏",
    "focus": "焦点变化",
    "control": "控制操作",
    "external_input": "外部输入",
    "modifier_anomaly": "修饰键异常",
    "env": "环境事件",
}

SOURCE_LABELS = {
    "self": "自身",
    "user": "用户",
    "injected": "注入",
}

NOTE_SUCCESS_TEXT = "成功"
NOTE_FAIL_TEXT = "失败"
FOCUS_LOST_TEXT = "失焦："
FOCUS_REGAINED_TEXT = "回焦"
SESSION_START_LABEL = "会话开始"
SESSION_END_LABEL = "会话结束"

# ---------- 事件行模板(六类事件 + 会话头尾;头尾模板为标签后的纯信息部分) ----------

EVENT_ROW_TEMPLATES = {
    "note": "{notes} / 键{keys} 偏差{deviation}ms {result}",
    "focus": "{event_desc}{window_title}",
    "control": "{action} {params}",
    "external_input": "VK {vk_code}（来源：{source}）",
    "modifier_anomaly": "{modifier} 预期={expected} 实际={actual}",
    "env": "{env_event} {details}",
    "session_start": "{score_name}（BPM {bpm}，音符 {note_count}）",
    "session_end": "完成 {completed}/{total}，事件 {events_count}",
}

# ---------- 详情摘要卡(键顺序即渲染顺序,取值来自 get_session_info) ----------

SUMMARY_LABELS = {
    "score_name": "曲名",
    "session_id": "会话 ID",
    "bpm": "BPM",
    "started_at": "开始时间",
    "ended_at": "结束时间",
    "completion": "完成度",
    "stopped_early": "提前停止",
    "events_count": "总事件数",
}