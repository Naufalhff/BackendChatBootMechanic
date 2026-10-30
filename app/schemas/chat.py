from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime


class ChatRequest(BaseModel):
    motor_model: Optional[str] = "Honda CB100"
    message: str


class ChatResponse(BaseModel):
    id: int
    user_id: int
    conversation_id: Optional[int] = None
    motor_model: Optional[str] = None
    user_message: str
    normalized_message: Optional[str] = None
    ai_response: str
    image_url: Optional[str] = None
    ai_model: Optional[str] = None
    ai_model_resolved: Optional[str] = None
    client_message_id: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    motor_model: Optional[str] = "Honda CB100"
    ai_model: Optional[str] = None
    title: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    ai_model: Optional[str] = None


class ConversationResponse(BaseModel):
    id: int
    title: Optional[str] = None
    motor_model: Optional[str] = None
    ai_model: Optional[str] = None
    message_count: int = 0
    last_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiModelItem(BaseModel):
    id: str
    label: str
    owned_by: Optional[str] = None
    is_combo: bool = False
    supports_vision: Optional[bool] = None


class AiModelCatalogResponse(BaseModel):
    default_model: str
    models: List[AiModelItem]
