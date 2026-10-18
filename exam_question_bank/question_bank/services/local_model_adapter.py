"""Optional local AI model adapter (Ollama / OpenAI-compatible chat).

Kept isolated so the rest of the application never depends on it. If the model
service is unreachable or returns invalid data, callers receive ``None`` and the
rule-based classifier result stands. Nothing is ever sent to a remote service
unless the user has explicitly enabled remote access.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ..config import AI


@dataclass
class AIModelStatus:
    available: bool
    endpoint: str
    detail: str = ""


def _post_json(url: str, payload: dict, timeout: float) -> Optional[dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _is_local(url: str) -> bool:
    return any(h in url for h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"))


def check_status() -> AIModelStatus:
    if not AI.enabled:
        return AIModelStatus(False, AI.base_url, "AI disabled (set QB_AI_ENABLED=1 to enable)")
    if not AI.allow_remote and not _is_local(AI.base_url):
        return AIModelStatus(False, AI.base_url, "Remote AI blocked; set QB_AI_ALLOW_REMOTE=1 to allow")
    tag_url = AI.base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(tag_url, timeout=min(AI.timeout, 5.0)) as resp:
            json.loads(resp.read().decode("utf-8"))
        return AIModelStatus(True, AI.base_url, "reachable")
    except Exception as exc:
        return AIModelStatus(False, AI.base_url, f"unreachable: {exc}")


def classify_with_model(question_text: str, context_text: str,
                        allowed: dict[str, list[str]]) -> Optional[dict]:
    """Ask the model for a structured classification. Returns dict or None."""
    status = check_status()
    if not status.available:
        return None

    allowed_lines = []
    for subject, topics in allowed.items():
        allowed_lines.append(f"{subject}: {', '.join(topics)}")
    taxonomy_blob = "\n".join(allowed_lines)

    system = (
        "You are a strict exam-question classifier. Reply with ONLY a JSON object "
        'with keys: subject, topic, subtopic, tags (array), reason. '
        "subject and topic MUST be chosen from the allowed taxonomy. "
        "Never invent new subjects or topics. If unsure, use the closest allowed "
        "topic and set subtopic to null."
    )
    user = (
        f"Allowed taxonomy (subject: topics):\n{taxonomy_blob}\n\n"
        f"Shared context:\n{context_text[:1500]}\n\n"
        f"Question:\n{question_text[:1500]}\n\n"
        "Return JSON only."
    )
    payload = {
        "model": AI.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    url = AI.base_url.rstrip("/") + "/api/chat"
    resp = _post_json(url, payload, AI.timeout)
    if not resp:
        return None
    content = (resp.get("message") or {}).get("content") or resp.get("response")
    if not content:
        return None
    return _parse_json(content)


def _parse_json(content: str) -> Optional[dict]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        obj = json.loads(content[start:end + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj
