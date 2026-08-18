from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class ChatRequest(BaseModel):
    motor_model: Optional[str] = "Honda CB100"
    message: str


class ChatResponse(BaseModel):
    id: int
    user_id: int
    motor_model: Optional[str] = None
    user_message: str
    ai_response: str
    image_url: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
