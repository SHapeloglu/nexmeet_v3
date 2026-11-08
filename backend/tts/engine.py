"""TTS ve STT motoru: Whisper ile konuşma tanıma, Chatterbox ile ses klonlu sentez, ayrıca TTS kuyruğu için kullanılan çekirdek.
DİKKAT: Bu paket şu an kullanılmıyor. main.py bu paketi import etmez; canlı sistem çeviri ve sesi ayrı TTS servisinden (Kokoro, CPU) alır. Dosya EC2 + GPU tasarımından kalma: torch, whisper ve /home/ubuntu yolları sabit yazılı.
Import edilirse torch ve whisper kurulu olmalıdır; import sırasında /home/ubuntu altında klasörler oluşturulmaya çalışılır."""
import os
import time
import asyncio
import hashlib
import torch
import torchaudio
import whisper
from pathlib import Path
from typing import Dict, Optional, Tuple, AsyncGenerator

# ─── Paths ───────────────────────────────────────────────────────────────────
VOICE_PROFILES_DIR = Path("/home/ubuntu/nexmeet/voice_profiles")
TEMP_RECORDINGS_DIR = Path("/home/ubuntu/nexmeet/temp_recordings")
RECORDINGS_DIR = Path("/home/ubuntu/nexmeet/recordings")

# Klasörler yoksa oluşturulur. DİKKAT: /home/ubuntu yolları EC2 kurulumuna aittir; bu yollar başka makinede yoksa import sırasında izin ya da yol hatası alınabilir.
for d in [VOICE_PROFILES_DIR, TEMP_RECORDINGS_DIR, RECORDINGS_DIR]:
    d.mkdir(exist_ok=True)

# ─── TTSEngine ────────────────────────────────────────────────────────────────
class TTSEngine:
    """Ses tanıma (Whisper) ve ses klonlu sentez (Chatterbox) motorunun tek örneği (singleton). Modeller ağır olduğu için initialize ile bir kez yüklenir; tüm konuşmacılar aynı nesneyi kullanır."""
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        """Model alanlarını boş başlatır ve ses önbelleğini kurar. Modeller burada yüklenmez; initialize çağrılmadan kullanılamaz."""
        self.tts_model = None
        self.stt_model = None
        self._speaker_cache: Dict[str, Tuple[dict, float]] = {}
        self._cache_ttl = 3600  # 1 saat
        self._initialized = False

    @classmethod
    def get_instance(cls):
        """TTSEngine'in tek örneğini döner, yoksa oluşturur. TTS kuyruğu (queue.py) motora bu metodla ulaşır."""
        if cls._instance is None:
            cls._instance = TTSEngine()
        return cls._instance

    async def initialize(self):
        """Modelleri yükle — sunucu başlarken bir kez çalışır."""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            import logging
            logger = logging.getLogger(__name__)
            logger.info("STT modeli yükleniyor (Whisper small)...")
            self.stt_model = whisper.load_model("small")
            logger.info("TTS modeli yükleniyor (Chatterbox)...")
            from chatterbox.tts import ChatterboxTTS
            self.tts_model = ChatterboxTTS.from_pretrained(device="cpu")
            self._initialized = True
            logger.info("✅ TTS ve STT modelleri hazır")

    # ─── Speaker Cache ────────────────────────────────────────────────────────
    def _get_cached_embedding(self, peer_id: str) -> Optional[dict]:
        """RAM cache'den embedding al, süresi dolduysa None döndür."""
        if peer_id in self._speaker_cache:
            embedding, ts = self._speaker_cache[peer_id]
            if time.time() - ts < self._cache_ttl:
                return embedding
            del self._speaker_cache[peer_id]
        return None

    def _set_cached_embedding(self, peer_id: str, embedding: dict):
        """Konuşmacının ses bilgisini zaman damgasıyla RAM önbelleğine yazar. Süre kontrolü _get_cached_embedding tarafında yapılır."""
        self._speaker_cache[peer_id] = (embedding, time.time())

    def _cleanup_cache(self):
        """Süresi dolmuş cache girişlerini temizle."""
        now = time.time()
        expired = [k for k, (_, ts) in self._speaker_cache.items()
                   if now - ts > self._cache_ttl]
        for k in expired:
            del self._speaker_cache[k]

    def get_profile_path(self, peer_id: str) -> Path:
        """Konuşmacının ses profili dosyasının yolunu döner. Dosya adı peer_id değerinin MD5 özetidir, böylece kimlik doğrudan dosya adında görünmez. Gerçek ses dosyası .wav olarak kaydedilir; .pt yalnız yol türetmek için kullanılır."""
        safe_id = hashlib.md5(peer_id.encode()).hexdigest()
        return VOICE_PROFILES_DIR / f"{safe_id}.pt"

    def has_voice_profile(self, peer_id: str) -> bool:
        """Konuşmacının ses profili diskte var mı diye bakar. True veya False döner."""
        return self.get_profile_path(peer_id).exists()

    async def save_voice_profile(self, peer_id: str, wav_path: str):
        """Ses örneğinden embedding hesapla, diske ve cache'e kaydet."""
        async with self._lock:
            profile_path = self.get_profile_path(peer_id)
            # Diske kaydet (ham ses — embedding değil, model her sürümde uyumlu kalsın)
            import shutil
            shutil.copy2(wav_path, str(profile_path).replace(".pt", ".wav"))
            # Cache'e işaretle
            self._set_cached_embedding(peer_id, {"wav_path": str(profile_path).replace(".pt", ".wav")})
            return True

    def get_voice_wav_path(self, peer_id: str) -> Optional[str]:
        """Kullanıcının ses örneği WAV dosyasının yolunu döndür."""
        # Önce RAM cache
        cached = self._get_cached_embedding(peer_id)
        if cached:
            return cached.get("wav_path")
        # Sonra disk
        wav_path = str(self.get_profile_path(peer_id)).replace(".pt", ".wav")
        if os.path.exists(wav_path):
            self._set_cached_embedding(peer_id, {"wav_path": wav_path})
            return wav_path
        return None

    # ─── STT ─────────────────────────────────────────────────────────────────
    async def transcribe(self, audio_path: str, language: str = "tr") -> str:
        """Ses dosyasını metne çevir."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.stt_model.transcribe(audio_path, language=language)
        )
        return result["text"].strip()

    # ─── Çeviri ──────────────────────────────────────────────────────────────
    async def translate(self, text: str, source_lang: str = "tr", target_lang: str = "en") -> str:
        """deep-translator ile ücretsiz çeviri."""
        try:
            from deep_translator import GoogleTranslator
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: GoogleTranslator(
                    source=source_lang[:2].lower(),
                    target=target_lang[:2].lower()
                ).translate(text)
            )
            return result or text
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Translation error: {e}")
            return text
    # ─── TTS ─────────────────────────────────────────────────────────────────
    async def synthesize(self, text: str, peer_id: str, output_path: str) -> bool:
        """Metni sese çevir, kullanıcının ses klonuyla."""
        wav_path = self.get_voice_wav_path(peer_id)

        async with self._lock:
            loop = asyncio.get_event_loop()
            try:
                if wav_path and os.path.exists(wav_path):
                    # Ses klonuyla üret
                    wav = await loop.run_in_executor(
                        None,
                        lambda: self.tts_model.generate(
                            text=text,
                            audio_prompt_path=wav_path,
                            exaggeration=0.5,
                        )
                    )
                else:
                    # Ses örneği yoksa varsayılan sesle üret
                    wav = await loop.run_in_executor(
                        None,
                        lambda: self.tts_model.generate(text=text)
                    )

                # Kaydet
                torchaudio.save(output_path, wav, self.tts_model.sr)
                return True
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"TTS error: {e}")
                return False

    # ─── Ana Pipeline ─────────────────────────────────────────────────────────
    async def process_speech(
        self,
        audio_path: str,
        speaker_peer_id: str,
        source_lang: str = "tr",
        target_lang: str = "en",
        output_path: str = "/tmp/tts_output.wav"
    ) -> Optional[str]:
        """
        Tam pipeline:
        ses → STT → çeviri → TTS (ses klonu) → çıktı dosyası
        """
        # STT ve embedding yükleme paralel çalışır
        transcribe_task = asyncio.create_task(
            self.transcribe(audio_path, language=source_lang)
        )

        # Embedding zaten cache'deyse 0ms, değilse diskten yükle
        voice_path = self.get_voice_wav_path(speaker_peer_id)

        # STT sonucunu bekle
        text = await transcribe_task
        if not text:
            return None

        # Çeviri
        translated = await self.translate(text, source_lang.upper(), target_lang.upper())
        if not translated:
            return None

        # TTS
        success = await self.synthesize(translated, speaker_peer_id, output_path)
        if not success:
            return None

        return output_path
