# Pocket Mechanic — Backend

API konsultasi mekanik berbasis FastAPI + SQLAlchemy + 9Router (LLM/RAG).

## Menjalankan

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Dokumentasi interaktif: `http://localhost:8000/docs`.

## Environment

Wajib:

| Variable | Keterangan |
| --- | --- |
| `DATABASE_URL` | URL database, contoh `postgresql+psycopg2://user:pass@host:5432/db` |
| `SECRET_KEY` | Secret untuk JWT |
| `NINEROUTER_API_KEY` | API key 9Router |
| `NINEROUTER_BASE_URL` | Base URL 9Router, contoh `https://9router.hariinidev.tech/v1` |
| `NINEROUTER_MODEL` | Model default, contoh `coding-V2` |

Opsional:

| Variable | Default | Keterangan |
| --- | --- | --- |
| `NINEROUTER_TIMEOUT` | `150` | Timeout request LLM (detik) |
| `NINEROUTER_ALLOWED_MODELS` | kosong | Daftar model yang boleh dipakai, pisah koma. Kosong = semua model dari 9Router |
| `NINEROUTER_MAX_CONTEXT_CHARS` | `24000` | Batas perkiraan karakter dokumen + riwayat yang dikirim ke model |
| `CHAT_RATE_LIMIT_PER_MINUTE` | `30` | Batas request chat per user per menit |
| `MAX_MESSAGE_CHARS` | `8000` | Panjang pesan maksimum |
| `MAX_IMAGE_BYTES` | `5000000` | Ukuran gambar maksimum |
| `MEDIA_DIR` | `media` | Folder penyimpanan gambar |

## Endpoint utama

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`
- `GET /api/v1/chat/models` — daftar model/combo 9Router (terfilter allowlist)
- `GET/POST /api/v1/chat/conversations` — daftar/buat sesi
- `GET/PATCH/DELETE /api/v1/chat/conversations/{id}` — detail/ubah/hapus sesi
- `POST /api/v1/chat/send` — kirim pesan (form-data: `message`, `motor_model`, `model`, `conversation_id`, `client_message_id`, `image`)
- `GET /api/v1/chat/history?conversation_id=&limit=&offset=` — riwayat per sesi (N pesan terbaru, urut lama → baru)
- `DELETE /api/v1/chat/history` — hapus seluruh riwayat user

## Catatan migrasi

Saat startup backend otomatis:

1. Membuat tabel `conversations` jika belum ada.
2. Menambah kolom baru pada `chat_histories` (`conversation_id`, `normalized_message`, `ai_model_resolved`, `client_message_id`).
3. Membuat index, termasuk unique index untuk idempotensi `client_message_id`.
4. Mengelompokkan riwayat lama tanpa sesi ke satu conversation per user + motor.

Migrasi bersifat idempotent dan aman dijalankan berulang.

## Keterbatasan yang diketahui

- Respons chat belum streaming (SSE); mobile menunggu jawaban lengkap.
- File di `/media` disajikan statis dengan nama UUID dan validasi tipe/ukuran, tetapi belum memakai autentikasi per file.
- Rate limiter dan cache daftar model disimpan di memori per proses (bukan Redis).
- Belum ada kebijakan retensi data otomatis.
