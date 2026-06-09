from __future__ import annotations

import json
import logging
import re
import time
from typing import Generator, Type

from openai import OpenAI
from pydantic import BaseModel

from src.config import LLMConfig

logger = logging.getLogger(__name__)

# 不可重试的错误关键词
_NON_RETRYABLE_PATTERNS = [
    "high risk",
    "rejected",
    "sensitive",
    "content policy",
    "invalid_api_key",
    "insufficient_quota",
    "account_deactivated",
]


def _is_retryable(error: Exception) -> bool:
    """判断错误是否值得重试。"""
    err_str = str(error).lower()
    for pattern in _NON_RETRYABLE_PATTERNS:
        if pattern in err_str:
            return False
    return True


def _repair_truncated_json(text: str) -> dict | None:
    """尝试修复被截断的JSON。"""
    text = text.strip()
    # 找到第一个 {
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    # 计算未闭合的括号
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False
    last_valid_pos = brace_start

    for i, ch in enumerate(text[brace_start:], brace_start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
            if open_braces == 0:
                # 完整的JSON
                try:
                    return json.loads(text[brace_start:i + 1], strict=False)
                except json.JSONDecodeError:
                    return None
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets -= 1

        # 记录最后一个有效的字符位置（非字符串内的）
        if not in_string and ch in (",", ":", "}", "]"):
            last_valid_pos = i

    # JSON被截断了，尝试修复
    # 截到最后一个有效位置，然后闭合所有未闭合的括号
    truncated = text[brace_start:last_valid_pos + 1]
    # 移除末尾的逗号
    truncated = truncated.rstrip().rstrip(",")

    # 闭合未闭合的括号
    # 为每个未闭合的 } 添加 "..."
    closers = "}" * max(0, open_braces) + "]" * max(0, open_brackets)
    # 如果最后一个有效字符是逗号或冒号，添加一个占位值
    if truncated.endswith(":"):
        truncated += '""'
    elif truncated.endswith(","):
        truncated = truncated[:-1]

    repaired = truncated + closers
    try:
        result = json.loads(repaired, strict=False)
        if isinstance(result, dict):
            logger.info(f"Successfully repaired truncated JSON ({len(text)} -> {len(repaired)} chars)")
            return result
    except json.JSONDecodeError:
        pass

    return None


# 必填字段的默认值映射（字段名 → 默认值）
_FIELD_DEFAULTS: dict[str, object] = {
    "speech": "[发言生成遇到问题]",
    "speech_type": "Extend",
    "content": "",
    "summary": "",
    "intent_type": "Pass",
    "want_to_speak": False,
    "energy": "low",
    "direction": "pass",
    "review": None,
    "thought": None,
    "mentions": [],
    "target": None,
    "next_direction": "",
    "speaker_focus": {},
    "operations": [],
    "action": "add",
    "section": "current_focus",
    # AgendaDecision fields
    "notice": "",
    "reject_intents": [],
    "speakers": [],
    "agenda_note": "",
}


def _is_type_compatible(field_info, value) -> bool:
    """检查值是否与字段的期望类型兼容（宽松检查，只拦截明显的类型错误）。"""
    if value is None:
        return True  # None 由 Pydantic 的 Optional 处理
    annotation = field_info.annotation
    # str 字段拿到 dict/list/bool/int → 不兼容
    if annotation is str and not isinstance(value, str):
        return False
    # list 字段拿到 dict/str/bool/int → 不兼容
    if annotation is list and not isinstance(value, list):
        return False
    return True


def _field_is_required(field_info) -> bool:
    """判断字段是否为必填（无 default 且无 default_factory）。"""
    from pydantic.fields import PydanticUndefined
    return (
        field_info.default is PydanticUndefined
        and field_info.default_factory is None
    )


def _fill_missing_fields(schema: type[BaseModel], data: dict) -> dict:
    """为缺失或类型错误的必填字段填充默认值，避免 Pydantic 验证失败。
    同时递归处理嵌套的 BaseModel 列表元素（如 WhiteboardSync.operations）。"""
    for field_name, field_info in schema.model_fields.items():
        value = data.get(field_name)
        required = _field_is_required(field_info)

        if field_name not in data:
            # 字段缺失
            if not required:
                continue
            if field_name in _FIELD_DEFAULTS:
                data[field_name] = _FIELD_DEFAULTS[field_name]
                logger.info(f"Filled missing required field '{field_name}' with default value")
        elif required and not _is_type_compatible(field_info, value):
            # 字段存在但类型明显错误（如截断修复后 speech 变成 {}）
            if field_name in _FIELD_DEFAULTS:
                data[field_name] = _FIELD_DEFAULTS[field_name]
                logger.info(f"Fixed malformed field '{field_name}' (was {type(value).__name__}), replaced with default")

    # 递归处理嵌套模型列表（如 operations: list[WhiteboardOperation]）
    for field_name, field_info in schema.model_fields.items():
        if field_name not in data:
            continue
        annotation = field_info.annotation
        if annotation is list:
            args = getattr(annotation, '__args__', None)
            if args and len(args) == 1 and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                inner_model = args[0]
                items = data[field_name]
                if isinstance(items, list):
                    for i, item in enumerate(items):
                        if isinstance(item, dict):
                            _fill_missing_fields(inner_model, item)

    return data


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.model = config.model
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        self.retry_count = config.retry_count
        self.retry_delay = config.retry_delay
        self.use_native_thinking = config.use_native_thinking
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.api_base,
            timeout=config.timeout,
        )

    def close(self) -> None:
        pass  # OpenAI client handles cleanup

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retry_count):
            try:
                effective_max = max_tokens or self.max_tokens
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature if temperature is not None else self.temperature,
                    "max_tokens": effective_max,
                }
                if self.use_native_thinking:
                    kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

                completion = self._client.chat.completions.create(**kwargs)
                msg = completion.choices[0].message
                content = msg.content or ""
                # 部分推理模型（如 o1/o3）把推理内容放在 reasoning_content 字段
                # 如果 content 为空但有 reasoning_content，用它兜底
                if not content and hasattr(msg, 'reasoning_content') and msg.reasoning_content:
                    content = msg.reasoning_content
                reason = completion.choices[0].finish_reason
                if not content:
                    logger.warning(f"LLM returned empty content (attempt {attempt + 1}), finish_reason={reason}")
                elif reason == "length":
                    logger.warning(f"LLM output truncated at {effective_max} tokens, content_len={len(content)}")
                return content
            except Exception as e:
                last_error = e
                if not _is_retryable(e):
                    logger.error(f"LLM request failed (non-retryable): {e}")
                    raise
                wait = self.retry_delay * (2 ** attempt)
                logger.warning(f"LLM request attempt {attempt + 1} failed: {e}, retrying in {wait}s")
                time.sleep(wait)

        raise RuntimeError(f"LLM request failed after {self.retry_count} attempts: {last_error}")

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        """流式调用 LLM，逐块 yield 文本片段。

        参数与 chat() 相同，但返回一个生成器而非完整字符串。
        重试逻辑仅在流创建阶段生效；一旦开始接收数据则不再重试。
        """
        last_error: Exception | None = None
        for attempt in range(self.retry_count):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature if temperature is not None else self.temperature,
                    "max_tokens": max_tokens or self.max_tokens,
                    "stream": True,
                }
                if self.use_native_thinking:
                    kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

                stream = self._client.chat.completions.create(**kwargs)
                # 流创建成功，开始 yield 内容
                chunk_count = 0
                total_chunks = 0
                first_chunk_info = None
                last_chunk_info = None
                for chunk in stream:
                    total_chunks += 1
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    # 记录第一个有 choices 的 chunk
                    if first_chunk_info is None:
                        first_chunk_info = {
                            "finish_reason": choice.finish_reason,
                            "role": choice.delta.role,
                            "content_len": len(choice.delta.content or ""),
                        }
                    # 始终更新 last_chunk_info
                    last_chunk_info = {
                        "finish_reason": choice.finish_reason,
                        "content_len": len(choice.delta.content or ""),
                        "has_content": bool(choice.delta.content),
                    }
                    if choice.delta.content:
                        chunk_count += 1
                        yield choice.delta.content
                # 流结束后检查
                if chunk_count == 0:
                    logger.warning(
                        f"LLM stream returned 0 content chunks (attempt {attempt + 1}). "
                        f"total_chunks={total_chunks}, First: {first_chunk_info}, Last: {last_chunk_info}"
                    )
                elif last_chunk_info and last_chunk_info.get("finish_reason") not in (None, "stop"):
                    logger.warning(
                        f"LLM stream ended with reason={last_chunk_info['finish_reason']}, "
                        f"chunks={chunk_count}/{total_chunks}"
                    )
                return  # 流正常结束
            except Exception as e:
                last_error = e
                if not _is_retryable(e):
                    logger.error(f"LLM stream request failed (non-retryable): {e}")
                    raise
                wait = self.retry_delay * (2 ** attempt)
                logger.warning(f"LLM stream request attempt {attempt + 1} failed: {e}, retrying in {wait}s")
                time.sleep(wait)

        raise RuntimeError(f"LLM stream request failed after {self.retry_count} attempts: {last_error}")

    def chat_structured(
        self,
        messages: list[dict[str, str]],
        schema: Type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel:
        schema_desc = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        format_instruction = (
            "\n\nYou MUST respond with a valid JSON object matching this schema. "
            "Do NOT return the schema definitions (like 'type', 'description'), return the actual data values! "
            "Do NOT include any text before or after the JSON. "
            "Do NOT use markdown code blocks (no ```). Just the raw JSON.\n"
            "IMPORTANT: Keep optional/reasoning fields (review, thought) under 200 characters each. "
            "The required fields (speech, speech_type) MUST appear in your output.\n"
            f"JSON Schema for your response:\n{schema_desc}"
        )

        enhanced_messages = messages.copy()
        if enhanced_messages and enhanced_messages[-1]["role"] == "user":
            enhanced_messages[-1] = {
                **enhanced_messages[-1],
                "content": enhanced_messages[-1]["content"] + format_instruction,
            }
        else:
            enhanced_messages.append({"role": "user", "content": format_instruction})

        last_error: Exception | None = None
        structured_max = max(self.max_tokens, 10000)  # Extra room for structured JSON
        max_attempts = 3  # 增加到3次

        for attempt in range(max_attempts):
            # 逐次增加 max_tokens（应对截断）
            attempt_max = structured_max + attempt * 3000

            try:
                raw = self.chat(
                    enhanced_messages,
                    temperature=temperature,
                    max_tokens=attempt_max,
                )
            except RuntimeError as e:
                # chat() 内部已经重试过了，这里是最终失败
                last_error = e
                logger.error(f"chat_structured: LLM call failed on attempt {attempt + 1}: {e}")
                break

            # 尝试解析JSON
            try:
                parsed = self._extract_json(raw)
                parsed = _fill_missing_fields(schema, parsed)
                return schema.model_validate(parsed)
            except (ValueError, Exception) as e:
                last_error = e
                logger.warning(f"Structured output parse attempt {attempt + 1}/{max_attempts} failed: {e}")

                # 尝试修复截断的JSON
                repaired = _repair_truncated_json(raw)
                if repaired is not None:
                    try:
                        repaired = _fill_missing_fields(schema, repaired)
                        return schema.model_validate(repaired)
                    except Exception as ve:
                        logger.warning(f"Repaired JSON failed validation: {ve}")

                if attempt < max_attempts - 1:
                    # 重试，附带错误反馈
                    enhanced_messages.append({"role": "assistant", "content": raw})
                    # 检测是否是截断导致的失败
                    is_truncated = (
                        "truncated" in str(e).lower()
                        or "Could not extract" in str(e)
                        or raw.rstrip().endswith(("...", "…", '"', ","))
                    )
                    if is_truncated:
                        enhanced_messages.append({
                            "role": "user",
                            "content": (
                                "Your previous response was TRUNCATED (cut off mid-sentence). "
                                "You MUST respond again with a SHORTER, more concise JSON. "
                                "Rules for retry:\n"
                                "- Keep all text fields under 50 characters\n"
                                "- Use abbreviated phrasing\n"
                                "- Do NOT include any text before or after the JSON\n"
                                f"Required fields: {list(schema.model_fields.keys())}"
                            ),
                        })
                    else:
                        enhanced_messages.append({
                            "role": "user",
                            "content": (
                                "Your response was not valid JSON. "
                                "Please respond again with ONLY a valid JSON object, no markdown, no explanation. "
                                f"Required fields: {list(schema.model_fields.keys())}"
                            ),
                        })

        raise RuntimeError(f"Failed to get valid structured output after {max_attempts} attempts: {last_error}")

    @staticmethod
    def _strip_thinking_tags(text: str) -> str:
        """剥离推理模型的思考标签（如 <think>...</think>、<reasoning>...</reasoning>）。"""
        import re
        # 匹配常见的 thinking 标签格式
        stripped = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        stripped = re.sub(r'<reasoning>.*?</reasoning>', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'<analysis>.*?</analysis>', '', stripped, flags=re.DOTALL)
        return stripped.strip()

    def _extract_json(self, text: str) -> dict:
        text = self._strip_thinking_tags(text)
        text = text.strip()

        # Try direct parse
        try:
            result = json.loads(text, strict=False)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Try to find JSON in markdown code block
        for marker in ["```json", "```JSON", "```"]:
            if marker in text:
                start = text.index(marker) + len(marker)
                # skip to next line if language tag is on same line
                remaining = text[start:]
                next_marker_pos = remaining.find("```")
                if "\n" in remaining[:next_marker_pos if next_marker_pos != -1 else len(remaining)]:
                    newline = remaining.index("\n")
                    start = start + newline + 1
                # Find closing marker
                end_pos = text.find("```", start)
                if end_pos != -1:
                    # 正常情况：找到了闭合标记
                    candidate = text[start:end_pos].strip()
                else:
                    # 截断情况：没有闭合标记，取到末尾
                    candidate = text[start:].strip()
                    logger.warning("Markdown code block not closed (truncated), extracting content to end")
                try:
                    result = json.loads(candidate, strict=False)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    # 截断的JSON，尝试修复
                    repaired = _repair_truncated_json(candidate)
                    if repaired is not None:
                        return repaired

        # Try to find first { ... } (greedy)
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            candidate = text[brace_start:brace_end + 1]
            try:
                result = json.loads(candidate, strict=False)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                # Try fixing common issues: trailing commas, single quotes
                fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                fixed = fixed.replace("'", '"')
                try:
                    result = json.loads(fixed, strict=False)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError as e:
                    logger.debug(f"JSON extract fallback failed: {e}")
                    pass

        # Last resort: try to repair truncated JSON
        if brace_start != -1:
            repaired = _repair_truncated_json(text)
            if repaired is not None:
                return repaired

        raise ValueError(f"Could not extract JSON from LLM response: {text[:300]}...")
