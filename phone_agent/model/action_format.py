"""Parse one literal action from AutoGLM or an OpenAI-compatible VLM."""

import ast
import json
import math
import re


ACTION_NAMES = {
    "Launch", "Tap", "Type", "Type_Name", "Interact", "Swipe", "Note",
    "Call_API", "Long Press", "Double Tap", "Take_over", "Back", "Home", "Wait",
}


def split_response(content):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型返回了空响应，未执行任何操作")
    text = content.strip()
    outer_fence = re.fullmatch(r"```(?:python|json)?\s*\n?(.*?)\n?```", text, re.S)
    if outer_fence:
        text = outer_fence.group(1).strip()
    thinking = ""
    think = re.search(r"<think>(.*?)</think>", text, re.S)
    if think:
        thinking = think.group(1).strip()
    answers = re.findall(r"<answer>(.*?)</answer>", text, re.S)
    if answers:
        text = answers[-1].strip()
    elif "<answer>" in text:
        text = text.rsplit("<answer>", 1)[1].strip()
    else:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        # AutoGLM sometimes emits a short explanation without XML tags.
        match = re.search(r"\b(?:do|finish)\s*\(", text)
        if match and not text.startswith("{"):
            thinking = thinking or text[:match.start()].strip()
            text = text[match.start():]
    fence = re.fullmatch(r"```(?:python|json)?\s*\n?(.*?)\n?```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    return thinking, text


def parse_literal_action(text):
    """Accept JSON or keyword-only do()/finish(); never execute model code."""
    _, text = split_response(text)
    try:
        if text.startswith("{"):
            action = json.loads(text)
            if not isinstance(action, dict):
                raise ValueError("动作必须是对象")
            if action.get("action") == "finish":
                action = {"_metadata": "finish", "message": action.get("message", "")}
            elif "_metadata" not in action:
                action["_metadata"] = "do"
        else:
            node = ast.parse(text, mode="eval").body
            if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name)
                    or node.func.id not in {"do", "finish"} or node.args):
                raise ValueError("需要单条 do(...) 或 finish(...) 指令")
            action = {}
            for keyword in node.keywords:
                if keyword.arg is None or keyword.arg in action or keyword.arg == "_metadata":
                    raise ValueError("动作参数重复或格式无效")
                action[keyword.arg] = ast.literal_eval(keyword.value)
            action["_metadata"] = node.func.id
        if action.get("_metadata") == "finish":
            if not isinstance(action.get("message"), str):
                raise ValueError("finish 需要字符串 message")
            return action
        if action.get("_metadata") != "do" or action.get("action") not in ACTION_NAMES:
            raise ValueError("未知动作")
        name = action["action"]
        coordinate_keys = ("start", "end") if name == "Swipe" else (
            ("element",) if name in {"Tap", "Long Press", "Double Tap"} else ()
        )
        for key in coordinate_keys:
            point = action.get(key)
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError(f"{key} 需要两个 0～999 坐标")
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or not 0 <= v <= 999 for v in point):
                raise ValueError("坐标必须在 0～999 范围内")
        for key in ({"Launch": ("app",), "Type": ("text",), "Type_Name": ("text",)}.get(name, ())):
            if not isinstance(action.get(key), str):
                raise ValueError(f"{name} 需要字符串 {key}")
        return action
    except (SyntaxError, TypeError, KeyError, ValueError) as exc:
        raise ValueError(f"无法解析模型动作: {exc}") from exc
