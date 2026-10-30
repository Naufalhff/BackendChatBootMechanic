import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import get_current_user
from app.core.llm import generate_response_with_rag
from app.core.normalizer import normalize_query
from app.database.models import ChatHistory, User
from app.database.session import get_db
from app.schemas.chat import ChatResponse

router = APIRouter()


@router.post("/send", response_model=ChatResponse)
async def send_message(
    message: str = Form(...),
    motor_model: Optional[str] = Form("Honda CB100"),
    image: Optional[UploadFile] = File(None),
    model: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mengirimkan pesan konsultasi mekanik.
    Mendukung pengiriman teks dan lampiran foto motor rusak (multimodal).
    Menggunakan normalisasi slang otomotif Indonesia sebelum diproses LLM RAG (9Router).
    Parameter `model` opsional untuk memilih model 9Router; jika kosong memakai NINEROUTER_MODEL.
    """
    image_url = None
    image_bytes = None

    if image:
        if not image.content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File yang diunggah harus berupa gambar.",
            )

        try:
            image_bytes = await image.read()

            ext = os.path.splitext(image.filename)[1] or ".jpg"
            filename = f"{uuid.uuid4()}{ext}"
            filepath = os.path.join("media", filename)

            with open(filepath, "wb") as f:
                f.write(image_bytes)

            image_url = f"/media/{filename}"
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Gagal memproses unggahan gambar: {str(e)}",
            )

    normalized_message = normalize_query(message)

    db_history = (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == current_user.id)
        .order_by(ChatHistory.created_at.desc())
        .limit(10)
        .all()
    )
    db_history.reverse()

    past_messages = []
    for chat in db_history:
        past_messages.append((chat.user_message, chat.ai_response))

    ai_response = generate_response_with_rag(
        user_message=normalized_message,
        past_messages=past_messages,
        image_bytes=image_bytes,
        image_mime=image.content_type if image else "image/jpeg",
        model=model,
    )

    db_chat = ChatHistory(
        user_id=current_user.id,
        motor_model=motor_model,
        user_message=message,
        ai_response=ai_response,
        image_url=image_url,
    )
    db.add(db_chat)
    db.commit()
    db.refresh(db_chat)

    return db_chat


@router.get("/history", response_model=List[ChatResponse])
def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mengambil seluruh riwayat konsultasi chat pengguna saat ini.
    """
    history = (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == current_user.id)
        .order_by(ChatHistory.created_at.asc())
        .all()
    )
    return history
