import json
import os
import re
from typing import Dict, Optional

DEFAULT_SLANG_DICT: Dict[str, str] = {
    "seher": "piston",
    "sehernya": "piston-nya",
    "pistonnya": "piston-nya",
    "kop": "cylinder head (kepala silinder)",
    "blok": "cylinder block (blok silinder)",
    "noken": "camshaft (noken as)",
    "noken as": "camshaft (noken as)",
    "kruk as": "crankshaft (poros engkol)",
    "askruk": "crankshaft (poros engkol)",
    "stang seher": "connecting rod (stang piston)",
    "klep": "valve (katup)",
    "klepnya": "valve-nya (katupnya)",
    "platina": "breaker points (platina)",
    "kondensor": "condenser (kondensator)",
    "spul": "stator coil (spul magnet)",
    "spulnya": "stator coil-nya (spulnya)",
    "kiprok": "regulator rectifier (kiprok)",
    "kiproknya": "regulator rectifier-nya (kiproknya)",
    "koil": "ignition coil (koil)",
    "karbu": "carburetor (karburator)",
    "karbunya": "carburetor-nya (karburatornya)",
    "kamprat": "timing chain (rantai keteng)",
    "keteng": "timing chain (rantai keteng)",
    "membran": "reed valve (katup buluh)",
    "sekur klep": "valve lapping (skir katup)",
    "skir klep": "valve lapping (skir katup)",
    "stroke up": "stroke up (peningkatan langkah piston)",
    "bore up": "bore up (peningkatan diameter piston)",
    "porting": "porting polish (pemolesan lubang masuk/buang)",
    "karbu banjir": "carburetor overflow (karburator banjir/meluap)",
    "pengapian ilang": "lost spark (kehilangan pengapian)",
    "pengapian hilang": "lost spark (kehilangan pengapian)",
    "oli samping": "2-stroke engine oil (oli samping)",
    "kanibal": "parts substitution (substitusi suku cadang)",
    "kanibalan": "parts substitution (substitusi suku cadang)",
}


def normalize_query(query: str, dictionary_path: Optional[str] = None) -> str:
    if not query:
        return ""

    slang_dict = DEFAULT_SLANG_DICT.copy()

    if dictionary_path and os.path.exists(dictionary_path):
        try:
            with open(dictionary_path, "r", encoding="utf-8") as f:
                custom_dict = json.load(f)
                if isinstance(custom_dict, dict):
                    slang_dict.update(custom_dict)
        except Exception:
            pass

    normalized = query

    sorted_slang_keys = sorted(slang_dict.keys(), key=len, reverse=True)

    for slang in sorted_slang_keys:
        standard = slang_dict[slang]
        pattern = rf"\b{re.escape(slang)}\b"
        normalized = re.sub(pattern, standard, normalized, flags=re.IGNORECASE)

    return normalized
