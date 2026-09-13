"""LLM 调用封装模块。

统一封装对 llama-index LLM 的调用，提供带重试的容错逻辑，以及
带 JSON 校验的调用能力。项目所有大模型调用都应经由本模块，以便
统一处理限流、超时、重试等异常情况。
"""
import time
import json
from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.prompts import BasePromptTemplate
from typing import Any, Dict, List, Optional, Sequence


def call_llm(prompt: BasePromptTemplate, llm: Optional[LLM] = None,
             max_try: int = 5, sleep: int = 10, **prompt_args) -> str:
    """调用 LLM 生成文本，失败时自动重试。

    Args:
        prompt: llama-index 的 PromptTemplate（内部含 {} 占位符）。
        llm: 大模型实例（如 DashScope）。
        max_try: 最大尝试次数。
        sleep: 两次尝试之间的等待秒数。
        **prompt_args: 用于填充 prompt 模板的参数（如 field_info_str 等）。

    Returns:
        模型返回的文本；若全部重试失败则返回空字符串。
    """
    for try_idx in range(max_try):
        try:
            # predict 会先用 prompt_args 填充模板再交给 LLM 生成
            res = llm.predict(prompt, **prompt_args)
            return res
        except Exception:
            time.sleep(sleep)
    return ''


def call_llm_message(messages: Sequence[ChatMessage], llm: Optional[LLM] = None,
                     max_try: int = 5, sleep: int = 10, **kwargs) -> str:
    """以消息列表形式调用 LLM（适用于多轮对话），失败时自动重试。

    Args:
        messages: ChatMessage 消息序列。
        llm: 大模型实例。
        max_try: 最大尝试次数。
        sleep: 重试间隔秒数。
        **kwargs: 其他传给 llm.chat 的参数。

    Returns:
        模型回复的文本内容；全部失败则返回空字符串。
    """
    for try_idx in range(max_try):
        try:
            res = llm.chat(messages, **kwargs)
            return res.message.content
        except Exception:
            time.sleep(sleep)
    return ''


def call_llm_with_json_validation(prompt: BasePromptTemplate, llm: Optional[LLM] = None,
                                  required_fields: Optional[List[str]] = None,
                                  expected_type: Optional[type] = None,
                                  max_retries: int = 3, sleep: int = 2, **prompt_args) -> Dict[str, Any]:
    """调用 LLM 并要求返回合法 JSON，对结果进行校验。

    该函数被并行处理器（ParallelLLMProcessor）使用，用于需要结构化
    输出的场景。它会把模型返回内容解析为 JSON，并校验必要字段与类型。

    Args:
        prompt: llama-index 的 PromptTemplate。
        llm: 大模型实例。
        required_fields: JSON 结果中必须包含的字段名列表。
        expected_type: 期望返回的 JSON 顶层类型（如 dict / list）。
        max_retries: 最大重试次数。
        sleep: 重试间隔秒数。
        **prompt_args: 填充 prompt 模板的参数。

    Returns:
        形如 {"success": bool, "data": Any, "error": str} 的结果字典。
        success 表示解析/校验是否通过。
    """
    for _ in range(max_retries):
        raw = call_llm(prompt, llm, max_try=1, sleep=sleep, **prompt_args)
        if not raw:
            continue
        try:
            data = _parse_json_from_text(raw)
            # 校验顶层类型
            if expected_type is not None and not isinstance(data, expected_type):
                continue
            # 校验必要字段
            if required_fields is not None:
                if isinstance(data, dict):
                    missing = [f for f in required_fields if f not in data]
                    if missing:
                        continue
            return {"success": True, "data": data, "error": ""}
        except Exception as e:
            continue
    return {"success": False, "data": {}, "error": "JSON validation failed"}


def _parse_json_from_text(raw: str):
    """从模型返回文本中尽力提取 JSON。

    依次尝试：直接 json.loads、提取 ```json 代码块、提取首尾花括号区间。
    """
    raw = raw.strip()
    # 1) 直接整体解析
    try:
        return json.loads(raw)
    except Exception:
        pass
    # 2) 提取 ```json ... ``` 代码块
    import re
    m = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    # 3) 提取第一个 { 到最后一个 } 之间的内容
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    raise ValueError(f"无法从文本中解析出 JSON: {raw[:200]}")
