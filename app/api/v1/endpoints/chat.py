import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import get_current_user
from app.config import settings
from app.core.llm import (
    LlmError,
    check_model_available,
    fetch_available_models,
    generate_response_with_rag,
)
from app.core.normalizer import normalize_query
from app.database.models import ChatHistory, Conversation, User
from app.database.session import get_db
from app.schemas.chat import (
    AiModelCatalogResponse,
    AiModelItem,
    ChatResponse,
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
)

router = APIRouter()

RATE_LIMIT_WINDOW_SECONDS = 60.0
_rate_lock = threading.Lock()
_rate_buckets: Dict[int, deque] = {}

IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
EXTENSION_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _enforce_rate_limit(user_id: int) -> None:
    limit = settings.CHAT_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return

    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets.setdefault(user_id, deque())
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Terlalu banyak permintaan. Coba lagi sebentar lagi.",
            )
        bucket.append(now)


async def _ensure_model_allowed(model: str) -> None:
    try:
        available = await check_model_available(model)
    except LlmError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    if available is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{model}' tidak tersedia. Silakan pilih model lain.",
        )


def _get_conversation(db: Session, user_id: int, conversation_id: int) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .first()
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesi konsultasi tidak ditemukan.",
        )
    return conversation


def _to_conversation_response(
    db: Session, conversation: Conversation
) -> ConversationResponse:
    message_count = (
        db.query(func.count(ChatHistory.id))
        .filter(ChatHistory.conversation_id == conversation.id)
        .scalar()
        or 0
    )
    last_chat = (
        db.query(ChatHistory)
        .filter(ChatHistory.conversation_id == conversation.id)
        .order_by(ChatHistory.id.desc())
        .first()
    )

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        motor_model=conversation.motor_model,
        ai_model=conversation.ai_model,
        message_count=message_count,
        last_message=(last_chat.user_message[:120] if last_chat else None),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def _save_image(image: UploadFile) -> tuple:
    content_type = (image.content_type or "").lower()
    extension = IMAGE_EXTENSIONS.get(content_type)

    if not extension and content_type in (
        "",
        "application/octet-stream",
        "binary/octet-stream",
    ):
        # Sebagian klien tidak mengirim MIME; fallback ke ekstensi file.
        candidate = os.path.splitext(image.filename or "")[1].lower()
        if candidate in EXTENSION_MIME_TYPES:
            extension = candidate
            content_type = EXTENSION_MIME_TYPES[candidate]

    if not extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format gambar harus JPG, PNG, WEBP, atau GIF.",
        )

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File gambar kosong.",
        )
    if len(image_bytes) > settings.MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "Ukuran gambar terlalu besar (maks "
                f"{settings.MAX_IMAGE_BYTES // 1_000_000} MB)."
            ),
        )

    media_dir = settings.MEDIA_DIR
    os.makedirs(media_dir, exist_ok=True)
    filename = f"{uuid.uuid4()}{extension}"
    filepath = os.path.join(media_dir, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)

    return f"/media/{filename}", image_bytes, content_type


def _load_past_image(image_url: Optional[str]) -> Optional[tuple]:
    """Ambil kembali satu gambar terakhir agar konteks visual tidak hilang."""
    if not image_url or not image_url.startswith("/media/"):
        return None

    filename = os.path.basename(image_url)
    filepath = os.path.join(settings.MEDIA_DIR, filename)
    if not os.path.isfile(filepath):
        return None
    if os.path.getsize(filepath) > settings.MAX_IMAGE_BYTES:
        return None

    extension = os.path.splitext(filename)[1].lower()
    mime = EXTENSION_MIME_TYPES.get(extension, "image/jpeg")
    try:
        with open(filepath, "rb") as f:
            return f.read(), mime
    except OSError:
        return None


def _remove_media_urls(image_urls: List[str]) -> None:
    for image_url in image_urls:
        if not image_url or not image_url.startswith("/media/"):
            continue
        filepath = os.path.join(
            settings.MEDIA_DIR, os.path.basename(image_url)
        )
        try:
            os.remove(filepath)
        except OSError:
            pass


def _build_past_messages(history: List[ChatHistory]) -> List[dict]:
    past_messages = []
    image_attached = False

    for chat in reversed(history):
        item = {
            "user_message": chat.normalized_message or chat.user_message,
            "ai_response": chat.ai_response,
        }

        # Hanya bawa satu gambar terbaru supaya token tidak membengkak.
        if not image_attached and chat.image_url:
            loaded = _load_past_image(chat.image_url)
            if loaded:
                item["image_bytes"], item["image_mime"] = loaded
                image_attached = True

        past_messages.append(item)

    past_messages.reverse()
    return past_messages


@router.get("/models", response_model=AiModelCatalogResponse)
async def list_ai_models(
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
):
    """
    Mengambil daftar model dan combo yang tersedia di 9Router.
    Daftar di-cache di backend agar tidak memanggil 9Router setiap request.
    Gunakan `?refresh=true` untuk memaksa pengambilan ulang.
    """
    try:
        models = await fetch_available_models(force_refresh=refresh)
    except LlmError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    items = [AiModelItem(**model) for model in models]
    default_model = settings.NINEROUTER_MODEL
    if items and not any(item.id == default_model for item in items):
        # Jangan tawarkan model default yang tidak ada di katalog 9Router.
        default_model = items[0].id

    return AiModelCatalogResponse(default_model=default_model, models=items)


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Membuat sesi konsultasi baru. Setiap sesi punya konteks sendiri."""
    model = (payload.ai_model or settings.NINEROUTER_MODEL).strip()
    await _ensure_model_allowed(model)

    conversation = Conversation(
        user_id=current_user.id,
        title=(payload.title or "").strip() or None,
        motor_model=payload.motor_model,
        ai_model=model,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return _to_conversation_response(db, conversation)


@router.get("/conversations", response_model=List[ConversationResponse])
def list_conversations(
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_conversation_response(db, item) for item in conversations]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _get_conversation(db, current_user.id, conversation_id)
    return _to_conversation_response(db, conversation)


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _get_conversation(db, current_user.id, conversation_id)

    if payload.ai_model is not None:
        model = payload.ai_model.strip()
        await _ensure_model_allowed(model)
        conversation.ai_model = model

    if payload.title is not None:
        conversation.title = payload.title.strip()[:80] or conversation.title

    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conversation)
    return _to_conversation_response(db, conversation)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _get_conversation(db, current_user.id, conversation_id)
    image_urls = [
        row[0]
        for row in db.query(ChatHistory.image_url)
        .filter(ChatHistory.conversation_id == conversation.id)
        .all()
        if row[0]
    ]
    db.query(ChatHistory).filter(
        ChatHistory.conversation_id == conversation.id
    ).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
    _remove_media_urls(image_urls)
    return {"deleted": True, "conversation_id": conversation_id}


@router.delete("/history")
def clear_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    image_urls = [
        row[0]
        for row in db.query(ChatHistory.image_url)
        .filter(ChatHistory.user_id == current_user.id)
        .all()
        if row[0]
    ]
    deleted_messages = (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == current_user.id)
        .delete(synchronize_session=False)
    )
    db.query(Conversation).filter(
        Conversation.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.commit()
    _remove_media_urls(image_urls)
    return {"deleted_messages": deleted_messages}


@router.post("/send", response_model=ChatResponse)
async def send_message(
    message: str = Form(...),
    motor_model: Optional[str] = Form("Honda CB100"),
    image: Optional[UploadFile] = File(None),
    model: Optional[str] = Form(None),
    conversation_id: Optional[int] = Form(None),
    client_message_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mengirimkan pesan konsultasi mekanik.
    Mendukung pengiriman teks dan lampiran foto motor rusak (multimodal).
    Menggunakan normalisasi slang otomotif Indonesia sebelum diproses LLM RAG (9Router).
    Parameter `model` opsional untuk memilih model 9Router; jika kosong memakai NINEROUTER_MODEL.
    Parameter `conversation_id` opsional; jika kosong, backend membuat sesi baru.
    Parameter `client_message_id` dipakai untuk mencegah pesan terkirim dua kali.
    """
    _enforce_rate_limit(current_user.id)

    message = (message or "").strip()
    if not message and not image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pesan atau gambar wajib diisi.",
        )
    if len(message) > settings.MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Pesan terlalu panjang (maks "
                f"{settings.MAX_MESSAGE_CHARS} karakter)."
            ),
        )

    # Idempotensi: jika request yang sama diulang, kembalikan hasil sebelumnya.
    if client_message_id:
        existing = (
            db.query(ChatHistory)
            .filter(
                ChatHistory.user_id == current_user.id,
                ChatHistory.client_message_id == client_message_id,
            )
            .first()
        )
        if existing:
            return existing

    requested_model = (model or "").strip()

    if conversation_id is not None:
        conversation = _get_conversation(db, current_user.id, conversation_id)
        resolved_model = (
            requested_model or conversation.ai_model or settings.NINEROUTER_MODEL
        )
    else:
        resolved_model = requested_model or settings.NINEROUTER_MODEL
        title = message[:80] if message else "Konsultasi foto"
        conversation = Conversation(
            user_id=current_user.id,
            title=title,
            motor_model=motor_model,
            ai_model=resolved_model,
        )
        db.add(conversation)
        db.flush()

    await _ensure_model_allowed(resolved_model)

    if conversation.motor_model:
        motor_model = conversation.motor_model

    image_url = None
    image_bytes = None
    image_mime = None

    if image:
        image_url, image_bytes, image_mime = await _save_image(image)

    normalized_message = normalize_query(message)

    history = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.conversation_id == conversation.id,
            ChatHistory.user_id == current_user.id,
        )
        .order_by(ChatHistory.id.desc())
        .limit(20)
        .all()
    )
    history.reverse()
    past_messages = _build_past_messages(history)
    selected_model = resolved_model

    try:
        ai_response, resolved_model = await generate_response_with_rag(
            user_message=normalized_message,
            past_messages=past_messages,
            image_bytes=image_bytes,
            image_mime=image_mime or "image/jpeg",
            model=selected_model,
            max_context_chars=settings.NINEROUTER_MAX_CONTEXT_CHARS,
        )
    except LlmError as e:
        db.rollback()
        if image_url:
            try:
                os.remove(
                    os.path.join(settings.MEDIA_DIR, os.path.basename(image_url))
                )
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )

    db_chat = ChatHistory(
        user_id=current_user.id,
        conversation_id=conversation.id,
        motor_model=motor_model,
        user_message=message,
        normalized_message=normalized_message,
        ai_response=ai_response,
        image_url=image_url,
        ai_model=selected_model,
        ai_model_resolved=resolved_model,
        client_message_id=(client_message_id or "").strip() or None,
    )
    db.add(db_chat)

    if not conversation.title:
        conversation.title = (message[:80] or "Konsultasi foto")
    # Simpan pilihan user (mis. combo), bukan model hasil resolve 9Router.
    conversation.ai_model = selected_model
    conversation.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except IntegrityError:
        # Dua request dengan client_message_id sama bisa balapan. Yang kalah
        # mengambil hasil yang sudah tersimpan agar tidak terjadi duplikasi.
        db.rollback()
        if image_url:
            try:
                os.remove(
                    os.path.join(settings.MEDIA_DIR, os.path.basename(image_url))
                )
            except OSError:
                pass

        existing = None
        if client_message_id:
            existing = (
                db.query(ChatHistory)
                .filter(
                    ChatHistory.user_id == current_user.id,
                    ChatHistory.client_message_id == client_message_id,
                )
                .first()
            )
        if existing:
            return existing

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pesan bentrok dengan data lain. Silakan coba lagi.",
        )

    db.refresh(db_chat)

    return db_chat


@router.get("/history", response_model=List[ChatResponse])
def get_chat_history(
    conversation_id: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mengambil riwayat konsultasi pengguna saat ini.
    Gunakan `conversation_id` agar hanya mengambil satu sesi.
    """
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    query = db.query(ChatHistory).filter(ChatHistory.user_id == current_user.id)
    if conversation_id is not None:
        _get_conversation(db, current_user.id, conversation_id)
        query = query.filter(ChatHistory.conversation_id == conversation_id)

    history = (
        query.order_by(ChatHistory.id.desc()).offset(offset).limit(limit).all()
    )
    history.reverse()
    return history
