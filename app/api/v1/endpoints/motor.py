from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class MotorCatalogItem(BaseModel):
    id: str
    model_name: str
    brand: str
    series: str
    engine_type: str
    tier: int
    support_status: str
    description: str
    recommended_parts_substitutions: Optional[List[str]] = None


CLASSIC_MOTORS_DATA = [
    {
        "id": "honda_cb100",
        "model_name": "Honda CB100",
        "brand": "Honda",
        "series": "CB-Series",
        "engine_type": "4-Tak",
        "tier": 1,
        "support_status": "Verified RAG",
        "description": "Dukungan penuh RAG. Membaca manual book resmi (Shop Manual) dan arsip trik kanibalan kelistrikan/mesin komunitas.",
        "recommended_parts_substitutions": [
            "Kiprok Nmax (untuk konversi 12V)",
            "CDI Shogun 110 (untuk konversi Platina ke CDI)",
            "Piston GL Max (untuk bore up harian)",
        ],
    },
    {
        "id": "honda_gl_max",
        "model_name": "Honda GL Max",
        "brand": "Honda",
        "series": "GL-Series",
        "engine_type": "4-Tak",
        "tier": 1,
        "support_status": "Verified RAG",
        "description": "Dukungan penuh RAG. Dilatih dengan Buku Pedoman Reparasi (BPR) mesin Neotech/Black Engine dan panduan karburator Keihin.",
        "recommended_parts_substitutions": [
            "Karburator PE28 (opsi performa harian)",
            "Noken as Tiger (substitusi langsung)",
            "Rantai keteng / kamprat Kaze (opsi kuat anti-bising)",
        ],
    },
    {
        "id": "honda_gl_pro",
        "model_name": "Honda GL Pro",
        "brand": "Honda",
        "series": "GL-Series",
        "engine_type": "4-Tak",
        "tier": 1,
        "support_status": "Verified RAG",
        "description": "Dukungan penuh RAG. Menggunakan katalog part resmi AHM dan panduan modifikasi stroke up menggunakan part Honda Tiger.",
        "recommended_parts_substitutions": [
            "Kruk as Tiger (untuk stroke up)",
            "Koil Suzuki Blue/RM85 (kelistrikan stabil)",
            "Kampas kopling GL Pro Series (lebih tebal dari Neotech)",
        ],
    },
    {
        "id": "honda_c70",
        "model_name": "Honda C70 (Pitung)",
        "brand": "Honda",
        "series": "C-Series",
        "engine_type": "4-Tak",
        "tier": 1,
        "support_status": "Verified RAG",
        "description": "Dukungan penuh RAG. Fokus pada spesifikasi pengapian platina asli 6V dan skema konversi kelistrikan ke 12V menggunakan mesin Grand/Supra C-Series.",
        "recommended_parts_substitutions": [
            "Koil/Spul Supra Fit (untuk konversi 12V)",
            "Noken as Honda Grand (kanibal mesin C-Series)",
            "Piston Supra X 100cc (bore-up aman)",
        ],
    },
    {
        "id": "honda_tiger",
        "model_name": "Honda Tiger 2000 / Revo",
        "brand": "Honda",
        "series": "GL-Series",
        "engine_type": "4-Tak",
        "tier": 1,
        "support_status": "Verified RAG",
        "description": "Dukungan penuh RAG. Mencakup troubleshooting penyakit bawaan rantai keteng berisik, modifikasi kelistrikan fullwave, dan bongkar mesin transmisi 6-percepatan.",
        "recommended_parts_substitutions": [
            "Rantai keteng DID 102 mata + Tonjokan otomatis modif manual",
            "Kiprok Tiger original/Shogun FL125 (kelistrikan fullwave)",
            "Piston Megapro (opsi kompresi lebih rendah untuk bensin murah)",
        ],
    },
    {
        "id": "vespa_px150",
        "model_name": "Vespa PX 150",
        "brand": "Piaggio",
        "series": "Vespa Classic",
        "engine_type": "2-Tak",
        "tier": 2,
        "support_status": "Generic Support",
        "description": "Dukungan umum. RAG belum terverifikasi manual resmi. Menggunakan pengetahuan otomotif umum tentang mesin 2-Tak Vespa lama (oli samping, karbu Delorto, platina/CDI PX).",
        "recommended_parts_substitutions": [],
    },
    {
        "id": "yamaha_rxking",
        "model_name": "Yamaha RX-King",
        "brand": "Yamaha",
        "series": "RX-Series",
        "engine_type": "2-Tak",
        "tier": 2,
        "support_status": "Generic Support",
        "description": "Dukungan umum. Memberikan arahan berdasarkan pengetahuan umum motor 2-Tak legendaris Yamaha (membran / reed valve, setelan oli samping, dan karburator Mikuni VM26).",
        "recommended_parts_substitutions": [],
    },
]


@router.get("/", response_model=List[MotorCatalogItem])
def list_supported_motors():
    return CLASSIC_MOTORS_DATA
