"""通用异常栈解析工具（错误类型 / 可能原因 / 排查方向）。

纯文本处理，无外部依赖；识别 Python 与 JavaScript 两种常见栈形。
输出结构化结果：错误类型、消息、帧列表、可能原因与排查建议。
"""

from __future__ import annotations

import re

MAX_TRACE_CHARS = 20000

_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+)(?:, in (.+))?')
_JS_FRAME = re.compile(r"at\s+(?:(\S+)\s+\()([^()]+?):(\d+):(\d+)\)?")
_PY_ERROR = re.compile(r"^((?:[\w.])*(?:Error|Exception|Exit|Interrupt|Warning|Failure|Timeout))\s*:\s*(.*)$")
_JS_ERROR = re.compile(r"^(\w*(?:Error|Exception))\s*:\s*(.*)$")

# 常见异常类型 → 可能原因与排查方向；键为异常短名（不含模块前缀）。
_CAUSES: dict[str, list[str]] = {
    "KeyError": ["访问了映射中不存在的键；核对键名拼写与数据来源是否产生该键"],
    "AttributeError": ["对象没有该属性；检查变量是否为 None、类型是否符合预期、属性名拼写"],
    "TypeError": ["类型不匹配或参数个数不对；打印相关变量的 type() 定位错位参数"],
    "IndexError": ["序列下标越界；检查循环边界与容器是否为空"],
    "ValueError": ["值不合法（如转换失败）；在转换前校验原始输入内容"],
    "ImportError": ["模块不可导入；核对依赖是否安装、虚拟环境是否正确、包名拼写"],
    "ModuleNotFoundError": ["模块不存在；确认依赖清单与运行环境一致"],
    "FileNotFoundError": ["路径不存在；确认工作目录与相对路径基准"],
    "PermissionError": ["权限不足；确认进程身份与目标路径权限"],
    "ConnectionError": ["网络连接失败；确认目标地址可达、服务在运行、代理设置"],
    "TimeoutError": ["等待超时；区分服务慢与不可达，检查超时阈值设置"],
    "StopIteration": ["迭代器耗尽后被取值；next() 应带默认值或先判空"],
    "RecursionError": ["递归过深；检查终止条件是否可达"],
    "RuntimeError": ["运行期通用错误；结合消息与栈顶帧定位具体调用"],
}


def parse_stacktrace(trace: str) -> dict:
    """解析一段异常栈文本；无法识别错误行时返回 language=unknown 的骨架。"""
    if not isinstance(trace, str) or not trace.strip():
        raise ValueError("trace 必须是非空字符串")
    if len(trace) > MAX_TRACE_CHARS:
        raise ValueError(f"trace 过长（上限 {MAX_TRACE_CHARS} 字符）")
    lines = [line.rstrip() for line in trace.strip().splitlines()]

    error_type, message = "", ""
    for line in reversed(lines):
        m = _PY_ERROR.match(line.strip())
        if m:
            error_type = m.group(1).split(".")[-1]
            message = m.group(2).strip()
            break
        m = _JS_ERROR.match(line.strip())
        if m:
            error_type = m.group(1)
            message = m.group(2).strip()
            break

    # 语言按帧特征判定，避免 Python 正则抢先吞掉 JS 错误行
    has_py_frames = bool(_PY_FRAME.search(trace))
    has_js_frames = bool(_JS_FRAME.search(trace))
    if has_py_frames:
        language = "python"
    elif has_js_frames:
        language = "javascript"
    else:
        language = "python" if error_type else "unknown"

    frames: list[dict] = []
    if language == "python":
        for m in _PY_FRAME.finditer(trace):
            frames.append({"file": m.group(1), "line": int(m.group(2)), "in": m.group(3) or ""})
    elif language == "javascript":
        for m in _JS_FRAME.finditer(trace):
            frames.append(
                {"file": m.group(2), "line": int(m.group(3)), "in": m.group(1) or ""}
            )

    short = error_type.split(".")[-1]
    causes = _CAUSES.get(short, [f"未收录的异常类型 {short}；从错误消息与最近一帧入手定位"])
    suggestions = list(causes)
    if frames:
        top = frames[-1]
        suggestions.append(f"最近一帧：{top['file']}:{top['line']}（{top['in'] or '-'}）先核对这里")
    else:
        suggestions.append("未识别到帧行；请贴出完整栈（含 File/…/at 行）")
    return {
        "language": language,
        "error_type": error_type,
        "message": message,
        "frames": frames,
        "frame_count": len(frames),
        "possible_causes": causes,
        "suggestions": suggestions,
    }
