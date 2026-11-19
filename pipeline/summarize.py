"""Multimodal summarisation over an OpenAI-compatible endpoint.

Works with DeepSeek V4.1 Flash by default. The model only ever returns JSON;
`templates/card.html` owns the layout. If the endpoint rejects image input
(4xx mentioning image/vision/multimodal) we retry once with text only and tag
the log line `vision_fallback`.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any

import requests

from config import Settings
from pipeline.download import (
    MAX_CHAPTERS as _MAX_CHAPTERS,
    MIN_CHAPTERS as _MIN_CHAPTERS,
    chapter_count_for,
)
from util import BiliNoteError

MIN_CHAPTERS, MAX_CHAPTERS = 3, 5
MIN_POINTS, MAX_POINTS = 2, 3
IMAGE_MAX_EDGE = 768
VISION_HINTS = ("image", "vision", "multimodal", "image_url", "图片")

SCHEMA_HINT = """{
  "title": "视频标题",
  "up_name": "UP 主昵称",
  "duration": 213,
  "chapters": [
    {"heading": "章节标题（8~16 字）", "points": ["要点，≤30 字", "要点"], "timestamp": 46}
  ],
  "frames": [
    {"ts": 12, "reason": "为什么选这一帧（10 字内）"}
  ]
}"""


class SummarizeError(BiliNoteError):
    pass


class VisionUnsupported(SummarizeError):
    """Endpoint refused image input — caller retries text-only."""


def encode_image(path: Path) -> str:
    """Local frame → compact JPEG data URL (keeps request size sane)."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise SummarizeError("缺少 pillow 依赖，无法编码截图") from exc

    with Image.open(path) as img:
        img = img.convert("RGB")
        if max(img.size) > IMAGE_MAX_EDGE:
            img.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def build_prompt(title: str, up_name: str, duration: int, frames: list[dict[str, Any]],
                 chapters_target: int = MAX_CHAPTERS) -> str:
    listing = "\n".join(f"- {f['label']}（ts={int(f['ts'])} 秒）" for f in frames)
    short = duration < 20
    min_points = 1 if short else MIN_POINTS
    max_points = 2 if short else MAX_POINTS

    rules = [
        f"章节数必须正好 = {chapters_target} 个，不多不少，按时间排序。",
        f"frames 数量必须正好 = {len(frames)} 个，ts 只能取自上面列出的时间点，"
        "reason 用一句话说明画面内容。",
        f"每章 points {min_points}~{max_points} 条，每条 ≤30 个汉字，具体不空泛。",
        "title / up_name / duration 使用上面给出的真实值（duration 用整数秒），不要编造。",
    ]
    if short:
        rules.append(
            "视频很短，只输出 2 个章节，每章 1~2 条要点，不要强行按时间切片"
            "（不要为了凑章节拆出无意义段落）。"
        )
    rules.append("全文简体中文，保留专有名词原文。只输出 JSON。")
    numbered = "\n".join(f"{i + 1}. {rule}" for i, rule in enumerate(rules))

    return f"""你在看视频《{title}》（UP 主：{up_name}，时长 {duration} 秒）的 {len(frames)} 张均匀采样截图。
请据此写一份「图文卡片」文案，输出严格 JSON。

截图时间点：
{listing}

JSON 结构（不要输出多余字段，不要 markdown 代码块）：
{SCHEMA_HINT}

硬性约束（必须遵守）：
{numbered}"""


def _error_blob(resp) -> str:
    try:
        return json.dumps(resp.json(), ensure_ascii=False)[:600]
    except ValueError:
        return (resp.text or "")[:600]


def _is_vision_rejection(resp) -> bool:
    if not (400 <= resp.status_code < 500):
        return False
    blob = _error_blob(resp).lower()
    return any(hint in blob for hint in VISION_HINTS)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise SummarizeError(f"模型返回的不是合法 JSON：{text[:200]}")


def _call(settings: Settings, messages: list[dict[str, Any]], logger=None) -> dict[str, Any]:
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2400,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
        )
    except requests.RequestException as exc:
        raise SummarizeError(f"调用模型失败：{exc}") from exc

    # Some OpenAI-compatible gateways reject response_format; retry once without it.
    if resp.status_code in (400, 422) and "response_format" in _error_blob(resp).lower():
        if logger:
            logger.warning("端点不支持 response_format，去掉后重试（json_mode_fallback）")
        payload.pop("response_format", None)
        resp = requests.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
        )

    if resp.status_code != 200:
        blob = _error_blob(resp)
        if _is_vision_rejection(resp):
            raise VisionUnsupported(f"端点不支持图片输入：HTTP {resp.status_code} {blob}")
        raise SummarizeError(f"模型调用失败：HTTP {resp.status_code} {blob}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise SummarizeError(f"模型响应结构异常：{_error_blob(resp)}") from exc
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return _extract_json(content)


def _messages(prompt: str, images: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for uri in images:
        content.append({"type": "image_url", "image_url": {"url": uri}})
    return [
        {"role": "system", "content": "你只输出严格 JSON，不解释。"},
        {"role": "user", "content": content},
    ]


def _parse_ts(value: Any) -> int:
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value or "").strip()
    if ":" in text:
        total = 0
        for part in [p for p in text.split(":") if p.strip().isdigit()]:
            total = total * 60 + int(part)
        return total
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _snap(ts: int, sampled: list[int]) -> int:
    return min(sampled, key=lambda s: abs(s - ts))


def normalize(raw: dict[str, Any], duration: int, sampled_ts: list[int] | None = None,
              chapters_target: int | None = None,
              fallback_title: str = "", fallback_up: str = "") -> dict[str, Any]:
    """Clamp model output into the shape the template expects.

    Chapter count follows `chapters_target` (time-based); frames always follow
    the evenly sampled timestamps (coverage first), the model's `reason` is
    attached when its ts snaps onto a sampled frame.
    """
    duration = max(1, int(duration or raw.get("duration") or 1))
    target = int(chapters_target or chapter_count_for(duration))
    target = max(_MIN_CHAPTERS, min(target, _MAX_CHAPTERS))
    min_chapters = min(2 if target <= 2 else 3, target)
    max_points = 2 if duration < 20 else MAX_POINTS
    sampled = [int(t) for t in (sampled_ts or [])] or [
        int(duration * (i + 0.5) / 12) for i in range(12)
    ]

    chapters: list[dict[str, Any]] = []
    for ch in raw.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        heading = str(ch.get("heading") or "").strip()
        points = [str(p).strip() for p in (ch.get("points") or []) if str(p).strip()]
        if not heading or not points:
            continue
        chapters.append(
            {
                "heading": heading[:26],
                "points": [p[:44] for p in points[:max_points]],
                "timestamp": min(_parse_ts(ch.get("timestamp")), duration - 1),
            }
        )
        if len(chapters) >= target:
            break

    if len(chapters) < min_chapters:
        while len(chapters) < min_chapters:
            idx = len(chapters)
            ts = int(duration * (idx + 1) / (min_chapters + 1))
            chapters.append(
                {
                    "heading": f"第 {idx + 1} 部分",
                    "points": ["（模型未给出该段要点）"],
                    "timestamp": max(0, min(ts, duration - 1)),
                }
            )
    chapters.sort(key=lambda c: c["timestamp"])

    reasons: dict[int, str] = {}
    for fr in raw.get("frames") or []:
        if not isinstance(fr, dict):
            continue
        ts = _snap(min(_parse_ts(fr.get("ts")), duration - 1), sampled)
        reason = str(fr.get("reason") or "").strip()[:20]
        if reason and ts not in reasons:
            reasons[ts] = reason

    frames = [{"ts": ts, "reason": reasons.get(ts, "")} for ts in sorted(set(sampled))]

    return {
        "title": str(raw.get("title") or fallback_title or "未命名视频").strip(),
        "up_name": str(raw.get("up_name") or fallback_up or "").strip(),
        "duration": duration,
        "chapters": chapters,
        "frames": frames,
    }


def summarize(settings: Settings, frames: list[dict[str, Any]], duration: int,
              title: str = "", up_name: str = "", logger=None) -> dict[str, Any]:
    """`frames` = [{"path": Path, "ts": int, "label": "MM:SS"}, ...]"""
    if not settings.llm_api_key:
        raise SummarizeError(
            "缺少 LLM_API_KEY，无法调用多模态模型。",
            hint="在 .env 中填写 LLM_API_KEY（默认 LLM_BASE_URL=https://api.deepseek.com/v1）。",
        )

    chapters_target = chapter_count_for(duration)
    prompt = build_prompt(title or "未命名视频", up_name, duration, frames, chapters_target)
    images = [encode_image(Path(f["path"])) for f in frames]
    if logger:
        logger.info("调用 %s 总结（%d 张截图）", settings.llm_model, len(images))

    try:
        raw = _call(settings, _messages(prompt, images), logger=logger)
    except VisionUnsupported as exc:
        if logger:
            logger.warning("vision_fallback：端点不接受图片输入，改为纯文本重试（%s）", exc.message)
        raw = _call(settings, _messages(prompt, []), logger=logger)

    return normalize(
        raw,
        duration,
        sampled_ts=[int(f["ts"]) for f in frames],
        chapters_target=chapters_target,
        fallback_title=title,
        fallback_up=up_name,
    )
