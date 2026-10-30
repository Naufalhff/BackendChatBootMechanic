import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, insert, text, update

from app.config import settings
from app.database.session import Base, engine
from app.database.models import ChatHistory, Conversation, User
from app.api.v1.router import api_router

logger = logging.getLogger(__name__)


CHAT_HISTORY_COLUMNS = {
    "ai_model": "VARCHAR",
    "ai_model_resolved": "VARCHAR",
    "conversation_id": "INTEGER",
    "normalized_message": "TEXT",
    "client_message_id": "VARCHAR",
}


def _backfill_conversations(connection) -> None:
    """Kelompokkan riwayat lama (tanpa conversation_id) ke satu sesi per motor."""
    rows = connection.execute(
        text(
            "SELECT DISTINCT user_id, motor_model "
            "FROM chat_histories WHERE conversation_id IS NULL"
        )
    ).mappings().all()

    for row in rows:
        user_id = row["user_id"]
        motor_model = row["motor_model"]
        params = {"user_id": user_id, "motor_model": motor_model or ""}

        first_chat = connection.execute(
            text(
                "SELECT user_message, ai_model, created_at FROM chat_histories "
                "WHERE user_id = :user_id "
                "AND COALESCE(motor_model, '') = :motor_model "
                "AND conversation_id IS NULL ORDER BY id ASC LIMIT 1"
            ),
            params,
        ).mappings().first()
        if not first_chat:
            continue

        title = (first_chat["user_message"] or "Konsultasi").strip().replace("\n", " ")
        result = connection.execute(
            insert(Conversation).values(
                user_id=user_id,
                title=title[:80],
                motor_model=motor_model,
                ai_model=first_chat["ai_model"],
            )
        )
        conversation_id = result.inserted_primary_key[0]

        connection.execute(
            update(ChatHistory)
            .where(
                ChatHistory.user_id == user_id,
                ChatHistory.conversation_id.is_(None),
                text("COALESCE(motor_model, '') = :motor_model").bindparams(
                    motor_model=motor_model or ""
                ),
            )
            .values(conversation_id=conversation_id)
        )


def ensure_chat_history_schema() -> None:
    """Tambah kolom baru pada tabel lama tanpa merusak data yang sudah ada."""
    inspector = inspect(engine)
    if "chat_histories" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("chat_histories")}
    missing = {name: ddl for name, ddl in CHAT_HISTORY_COLUMNS.items() if name not in columns}
    is_postgres = engine.dialect.name == "postgresql"

    with engine.begin() as connection:
        for name, ddl in missing.items():
            if is_postgres:
                connection.execute(
                    text(
                        f"ALTER TABLE chat_histories "
                        f"ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    )
                )
            else:
                connection.execute(
                    text(f"ALTER TABLE chat_histories ADD COLUMN {name} {ddl}")
                )

        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_histories_client_message_id "
                "ON chat_histories (client_message_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_histories_conversation_id "
                "ON chat_histories (conversation_id)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ux_chat_histories_user_client_message "
                "ON chat_histories (user_id, client_message_id) "
                "WHERE client_message_id IS NOT NULL"
            )
        )

        _backfill_conversations(connection)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        ensure_chat_history_schema()
    except Exception as e:
        logger.exception("Gagal menyiapkan skema chat: %s", e)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA_DIR = settings.MEDIA_DIR
if not os.path.exists(MEDIA_DIR):
    os.makedirs(MEDIA_DIR)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": f"Welcome to {settings.PROJECT_NAME}. Akses /docs untuk dokumentasi Swagger.",
    }
