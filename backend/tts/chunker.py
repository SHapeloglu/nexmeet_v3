import re
from typing import List

def split_sentences(text: str) -> List[str]:
    """
    Metni cümlelere böl.
    İlk cümle hazır olunca hemen göndermek için.
    """
    # Nokta, !, ? ile biten cümleleri ayır
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    # Boş ve çok kısa cümleleri filtrele
    sentences = [s.strip() for s in sentences if len(s.strip()) > 2]
    # Çok uzun cümleleri böl (max 100 karakter)
    result = []
    for s in sentences:
        if len(s) > 100:
            # Virgülden böl
            parts = re.split(r'(?<=,)\s+', s)
            result.extend([p.strip() for p in parts if len(p.strip()) > 2])
        else:
            result.append(s)
    return result if result else [text.strip()]


def estimate_duration(text: str, wpm: int = 150) -> float:
    """Konuşma süresini tahmin et (saniye)."""
    words = len(text.split())
    return (words / wpm) * 60
