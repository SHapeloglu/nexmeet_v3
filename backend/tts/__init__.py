"""tts paketi: ses motoru (engine), iş kuyruğu (queue) ve metin parçalama (chunker) yardımcılarını dışarıya açar.
Bu paket kullanılmıyor; import edildiğinde torch ve whisper gerekir (bkz. engine.py)."""
from .engine import TTSEngine
from .queue import tts_queue
from .chunker import split_sentences, estimate_duration

__all__ = ["TTSEngine", "tts_queue", "split_sentences", "estimate_duration"]
