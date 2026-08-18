from fastapi import APIRouter
from app.api.v1.endpoints import auth, chat, motor

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(chat.router, prefix="/chat", tags=["Consultation & Chatbot"])
api_router.include_router(motor.router, prefix="/motor", tags=["Motorcycle Catalog"])
