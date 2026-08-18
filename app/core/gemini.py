import os
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from google import genai
from google.genai import types

from app.config import settings
from app.core.prompts import SYSTEM_PROMPT

_cached_content_name: Optional[str] = None
_cache_expiry: Optional[datetime] = None


def get_gemini_client() -> Optional[genai.Client]:
    if not settings.GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception:
        return None


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


def get_or_create_context_cache(
    client: genai.Client, model: str, combined_text: str, force_refresh: bool = False
) -> Tuple[Optional[str], int]:
    global _cached_content_name, _cache_expiry

    try:
        token_check = client.models.count_tokens(model=model, contents=combined_text)
        token_count = token_check.total_tokens
    except Exception:
        token_count = 0

    if token_count < 32768:
        return None, token_count

    if (
        not force_refresh
        and _cached_content_name
        and _cache_expiry
        and datetime.utcnow() < _cache_expiry
    ):
        return _cached_content_name, token_count

    if not force_refresh:
        try:
            for cache in client.caches.list():
                if cache.display_name == "pocket_mechanic_knowledge":
                    _cached_content_name = cache.name
                    _cache_expiry = datetime.utcnow() + timedelta(hours=12)
                    return _cached_content_name, token_count
        except Exception:
            pass

    try:
        ttl_seconds = 86400
        cache = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                display_name="pocket_mechanic_knowledge",
                system_instruction=SYSTEM_PROMPT,
                contents=[types.Content(parts=[types.Part.from_text(text=combined_text)])],
                ttl=f"{ttl_seconds}s",
            ),
        )
        _cached_content_name = cache.name
        _cache_expiry = datetime.utcnow() + timedelta(seconds=ttl_seconds - 300)
        return _cached_content_name, token_count
    except Exception:
        return None, token_count


def generate_response_with_rag(
    user_message: str,
    past_messages: List[Tuple[str, str, Optional[str]]] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = "image/jpeg",
) -> str:
    client = get_gemini_client()
    if not client:
        return (
            "[API KEY BELUM DIATUR] Halo! Saya Pocket Mechanic. "
            "Silakan konfigurasi GEMINI_API_KEY di file .env backend untuk mengaktifkan kecerdasan RAG."
        )

    model_name = settings.GEMINI_MODEL
    context_text = load_knowledge_documents()
    cache_name, total_tokens = get_or_create_context_cache(client, model_name, context_text)

    contents = []

    if past_messages:
        for u_msg, a_resp in past_messages:
            contents.append(
                types.Content(
                    role="user", parts=[types.Part.from_text(text=u_msg)]
                )
            )
            contents.append(
                types.Content(
                    role="model", parts=[types.Part.from_text(text=a_resp)]
                )
            )

    current_parts = []
    if image_bytes:
        current_parts.append(
            types.Part.from_bytes(data=image_bytes, mime_type=image_mime)
        )
    current_parts.append(types.Part.from_text(text=user_message))
    contents.append(types.Content(role="user", parts=current_parts))

    try:
        if cache_name:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    cached_content=cache_name,
                ),
            )
        else:
            system_instruction_fallback = SYSTEM_PROMPT
            if context_text:
                system_instruction_fallback += (
                    "\n\nBerikut adalah DOKUMEN REFERENSI MANUAL & HACK KOMUNITAS "
                    "yang dapat Anda gunakan untuk menjawab pertanyaan:\n" + context_text
                )

            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction_fallback,
                ),
            )

        return response.text
    except Exception as e:
        return f"Terjadi kesalahan saat menghubungi server Gemini: {str(e)}"
