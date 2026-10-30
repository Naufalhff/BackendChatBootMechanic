import base64
import json
import os
from typing import List, Optional, Tuple, Union

import httpx

from app.config import settings
from app.core.prompts import SYSTEM_PROMPT


def load_knowledge_documents() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    knowledge_dir = os.path.join(base_dir, "pocket-mechanic-knowledge")

    if not os.path.exists(knowledge_dir):
        return ""

    documents = []

    for root, dirs, files in os.walk(knowledge_dir):
        for file in files:
            if file.endswith((".txt", ".md")) and "slang_otomotif_indonesia.json" not in file:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        documents.append(f"=== SUMBER DOKUMEN: {file} ===\n{content}\n")
                except Exception:
                    pass

    return "\n".join(documents)


def build_system_instruction() -> str:
    context_text = load_knowledge_documents()
    if not context_text:
        return SYSTEM_PROMPT

    return (
        SYSTEM_PROMPT
        + "\n\nBerikut adalah DOKUMEN REFERENSI MANUAL & HACK KOMUNITAS "
        "yang dapat Anda gunakan untuk menjawab pertanyaan:\n"
        + context_text
    )


def _build_user_content(
    user_message: str,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = "image/jpeg",
) -> Union[str, List[dict]]:
    if not image_bytes:
        return user_message

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    mime = image_mime or "image/jpeg"

    return [
        {"type": "text", "text": user_message},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        },
    ]


def _build_messages(
    user_message: str,
    past_messages: Optional[List[Tuple[str, str, Optional[str]]]] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = "image/jpeg",
) -> List[dict]:
    messages = [{"role": "system", "content": build_system_instruction()}]

    if past_messages:
        for item in past_messages:
            u_msg, a_resp = item[0], item[1]
            if not u_msg or not a_resp:
                continue
            messages.append({"role": "user", "content": u_msg})
            messages.append({"role": "assistant", "content": a_resp})

    messages.append(
        {"role": "user", "content": _build_user_content(user_message, image_bytes, image_mime)}
    )
    return messages


def _extract_message_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""

    content = (choices[0].get("message") or {}).get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("text"):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)

    return ""


def _extract_stream_text(raw_body: str) -> str:
    """Fallback parser when server membalas SSE walau stream=False."""
    chunks = []
    for line in raw_body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choices = data.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        text = delta.get("content")
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks)


def generate_response_with_rag(
    user_message: str,
    past_messages: List[Tuple[str, str, Optional[str]]] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = "image/jpeg",
    model: Optional[str] = None,
) -> str:
    if not settings.NINEROUTER_API_KEY:
        return (
            "[API KEY BELUM DIATUR] Halo! Saya Pocket Mechanic. "
            "Silakan konfigurasi NINEROUTER_API_KEY di file .env backend untuk mengaktifkan kecerdasan RAG."
        )

    model_name = model or settings.NINEROUTER_MODEL
    url = settings.NINEROUTER_BASE_URL.rstrip("/") + "/chat/completions"

    payload = {
        "model": model_name,
        "messages": _build_messages(user_message, past_messages, image_bytes, image_mime),
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {settings.NINEROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=settings.NINEROUTER_TIMEOUT) as client:
            response = client.post(url, headers=headers, json=payload)

        if response.status_code >= 400:
            detail = response.text[:300]
            return (
                f"Terjadi kesalahan saat menghubungi server 9Router "
                f"(HTTP {response.status_code}): {detail}"
            )

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/event-stream"):
            text = _extract_stream_text(response.text)
        else:
            text = _extract_message_text(response.json())

        if not text:
            return "Maaf, server 9Router tidak mengembalikan jawaban. Silakan coba lagi."

        return text
    except httpx.HTTPError as e:
        return f"Terjadi kesalahan saat menghubungi server 9Router: {str(e)}"
    except Exception as e:
        return f"Terjadi kesalahan saat menghubungi server 9Router: {str(e)}"
