import base64
import json
import os
import time
from typing import List, Optional, Tuple, Union

import httpx

from app.config import settings
from app.core.prompts import SYSTEM_PROMPT

MODELS_CACHE_TTL_SECONDS = 300.0

_models_cache: Optional[List[dict]] = None
_models_cache_at: float = 0.0

_knowledge_cache: Optional[str] = None
_knowledge_cache_signature: Optional[tuple] = None


class LlmError(Exception):
    """Kesalahan saat berkomunikasi dengan 9Router."""


def _models_url() -> str:
    return settings.NINEROUTER_BASE_URL.rstrip("/") + "/models"


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.NINEROUTER_API_KEY}",
        "Content-Type": "application/json",
    }


def get_allowed_model_ids() -> Optional[set]:
    """None berarti semua model boleh dipakai."""
    raw = settings.NINEROUTER_ALLOWED_MODELS.strip()
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_model_allowed(model_id: str) -> bool:
    allowed = get_allowed_model_ids()
    if allowed is None:
        return True
    return model_id in allowed or model_id == settings.NINEROUTER_MODEL


def _extract_supports_vision(item: dict) -> Optional[bool]:
    capabilities = item.get("capabilities")
    if isinstance(capabilities, dict):
        for key in ("vision", "image_input", "image"):
            value = capabilities.get(key)
            if isinstance(value, bool):
                return value
    elif isinstance(capabilities, list):
        return any(str(cap).lower() in {"vision", "image", "image_input"} for cap in capabilities)

    architecture = item.get("architecture")
    modalities = item.get("input_modalities")
    if modalities is None and isinstance(architecture, dict):
        modalities = architecture.get("input_modalities")
    if isinstance(modalities, list):
        return any("image" in str(modality).lower() for modality in modalities)

    return None


def _extract_is_combo(item: dict) -> bool:
    if isinstance(item.get("is_combo"), bool):
        return item["is_combo"]
    if str(item.get("type", "")).lower() == "combo":
        return True
    return str(item.get("owned_by", "")).lower() in {"combo", "combos", "9router"}


def _normalize_model_item(item: dict) -> Optional[dict]:
    if not isinstance(item, dict):
        return None

    model_id = item.get("id") or item.get("name")
    if not model_id:
        return None

    model_id = str(model_id)
    owned_by = item.get("owned_by")
    return {
        "id": model_id,
        "label": str(item.get("display_name") or item.get("name") or model_id),
        "owned_by": None if owned_by is None else str(owned_by),
        "is_combo": _extract_is_combo(item),
        "supports_vision": _extract_supports_vision(item),
    }


async def fetch_available_models(force_refresh: bool = False) -> List[dict]:
    """Ambil daftar model + combo dari 9Router (di-cache beberapa menit)."""
    global _models_cache, _models_cache_at

    now = time.monotonic()
    if (
        not force_refresh
        and _models_cache is not None
        and now - _models_cache_at < MODELS_CACHE_TTL_SECONDS
    ):
        return _models_cache

    if not settings.NINEROUTER_API_KEY:
        raise LlmError(
            "NINEROUTER_API_KEY belum diatur di .env backend, daftar model tidak tersedia."
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(_models_url(), headers=_auth_headers())
    except httpx.HTTPError as e:
        raise LlmError(f"Gagal menghubungi 9Router untuk daftar model: {str(e)}")

    if response.status_code >= 400:
        raise LlmError(
            f"9Router menolak permintaan daftar model "
            f"(HTTP {response.status_code}): {response.text[:300]}"
        )

    try:
        payload = response.json()
    except ValueError:
        raise LlmError("Respons daftar model dari 9Router bukan JSON yang valid.")

    raw_items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise LlmError("Format daftar model dari 9Router tidak dikenali.")

    models = []
    seen = set()
    for item in raw_items:
        normalized = _normalize_model_item(item)
        if normalized and normalized["id"] not in seen:
            seen.add(normalized["id"])
            models.append(normalized)

    allowed = get_allowed_model_ids()
    if allowed is not None:
        models = [
            model
            for model in models
            if model["id"] in allowed or model["id"] == settings.NINEROUTER_MODEL
        ]

    models.sort(key=lambda model: model["id"].lower())

    _models_cache = models
    _models_cache_at = now
    return models


async def check_model_available(model: str) -> bool:
    """Validasi model; LlmError dilempar jika daftar model tidak bisa diambil."""
    if not model or model == settings.NINEROUTER_MODEL:
        return True

    if not is_model_allowed(model):
        return False

    models = await fetch_available_models()
    return any(item["id"] == model for item in models)


def _knowledge_files() -> List[str]:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    knowledge_dir = os.path.join(base_dir, "pocket-mechanic-knowledge")

    if not os.path.exists(knowledge_dir):
        return []

    files = []
    for root, dirs, filenames in os.walk(knowledge_dir):
        for file in filenames:
            if file.endswith((".txt", ".md")) and "slang_otomotif_indonesia.json" not in file:
                files.append(os.path.join(root, file))
    return sorted(files)


def load_knowledge_documents() -> str:
    """Baca dokumen knowledge sekali saja, invalidasi jika file berubah."""
    global _knowledge_cache, _knowledge_cache_signature

    files = _knowledge_files()
    signature = tuple(
        (path, os.path.getmtime(path)) for path in files if os.path.exists(path)
    )
    if _knowledge_cache is not None and signature == _knowledge_cache_signature:
        return _knowledge_cache

    documents = []
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            documents.append(
                f"=== SUMBER DOKUMEN: {os.path.basename(file_path)} ===\n{content}\n"
            )
        except Exception:
            pass

    _knowledge_cache = "\n".join(documents)
    _knowledge_cache_signature = signature
    return _knowledge_cache


def build_system_instruction(max_chars: Optional[int] = None) -> str:
    context_text = load_knowledge_documents()
    if not context_text:
        return SYSTEM_PROMPT

    if max_chars is not None and len(context_text) > max_chars:
        context_text = (
            context_text[:max_chars]
            + "\n\n[...dokumen dipotong karena batas konteks...]"
        )

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
    past_messages: Optional[List[dict]] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = "image/jpeg",
    max_context_chars: Optional[int] = None,
) -> List[dict]:
    budget = max_context_chars or settings.NINEROUTER_MAX_CONTEXT_CHARS

    # Sisakan ruang untuk pesan terbaru dan instruksi sistem.
    system_budget = max(int(budget * 0.6), 1000)
    system_instruction = build_system_instruction(max_chars=system_budget)

    remaining = budget - len(system_instruction) - len(user_message)
    selected_history: List[dict] = []

    if past_messages:
        for item in reversed(past_messages):
            u_msg = (item.get("user_message") or "").strip()
            a_resp = (item.get("ai_response") or "").strip()
            if not u_msg or not a_resp:
                continue

            cost = len(u_msg) + len(a_resp)
            if selected_history and cost > remaining:
                break
            if not selected_history and cost > remaining:
                # Tetap sertakan potongan jawaban terakhir agar konteks tidak kosong.
                a_resp = a_resp[: max(remaining // 2, 0)]
                cost = len(u_msg) + len(a_resp)

            selected_history.append(item)
            remaining -= cost

        selected_history.reverse()

    messages = [{"role": "system", "content": system_instruction}]

    for item in selected_history:
        messages.append(
            {
                "role": "user",
                "content": _build_user_content(
                    item.get("user_message") or "",
                    item.get("image_bytes"),
                    item.get("image_mime") or "image/jpeg",
                ),
            }
        )
        messages.append(
            {"role": "assistant", "content": item.get("ai_response") or ""}
        )

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


async def generate_response_with_rag(
    user_message: str,
    past_messages: Optional[List[dict]] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = "image/jpeg",
    model: Optional[str] = None,
    max_context_chars: Optional[int] = None,
) -> Tuple[str, str]:
    """Kembalikan (teks_jawaban, model_yang_benar_benar_dipakai)."""
    if not settings.NINEROUTER_API_KEY:
        raise LlmError(
            "NINEROUTER_API_KEY belum diatur di .env backend, "
            "kecerdasan RAG belum bisa diaktifkan."
        )

    model_name = (model or settings.NINEROUTER_MODEL).strip() or settings.NINEROUTER_MODEL
    if not is_model_allowed(model_name):
        raise LlmError(f"Model '{model_name}' tidak diizinkan oleh server.")

    url = settings.NINEROUTER_BASE_URL.rstrip("/") + "/chat/completions"

    payload = {
        "model": model_name,
        "messages": _build_messages(
            user_message,
            past_messages,
            image_bytes,
            image_mime,
            max_context_chars=max_context_chars,
        ),
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.NINEROUTER_TIMEOUT) as client:
            response = await client.post(url, headers=_auth_headers(), json=payload)
    except httpx.HTTPError as e:
        raise LlmError(f"Gagal menghubungi 9Router: {str(e)}")

    if response.status_code >= 400:
        detail = response.text[:300]
        raise LlmError(
            f"9Router menolak permintaan (HTTP {response.status_code}): {detail}"
        )

    content_type = response.headers.get("content-type", "")
    resolved_model = model_name

    if content_type.startswith("text/event-stream"):
        text = _extract_stream_text(response.text)
    else:
        try:
            data = response.json()
            text = _extract_message_text(data)
            resolved_model = str(data.get("model") or model_name)
        except ValueError:
            raise LlmError("Respons dari 9Router bukan JSON yang valid.")

    if not text:
        raise LlmError("9Router tidak mengembalikan jawaban. Silakan coba lagi.")

    return text, resolved_model
