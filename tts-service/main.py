"""NexMeet TTS servisi (FastAPI).

Akış: gelen ses -> faster-whisper ile metin (STT) -> Argos ile tr->en çeviri -> Kokoro ile İngilizce ses (TTS).
Çağıran: backend/main.py içindeki /api/tts/* proxy'si (nexmeet konteyneri). Servis 127.0.0.1:5000'de dinler.
Gerekenler: API_KEY ortam değişkeni; kokoro-v1.0.onnx, voices-v1.0.bin ve models/translate-tr_en-1_5/ dosyaları.
Modeller import sırasında yüklenir, bu yüzden servis açılışı birkaç saniye sürer.
"""
import os
import re
import hmac
import base64
import tempfile
import logging
from fastapi import FastAPI, Header, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from faster_whisper import WhisperModel
import ctranslate2
import sentencepiece as spm
from kokoro_onnx import Kokoro
import soundfile as sf
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PEER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"  # profil dosya adı için güvenli karakterler (path traversal engeli)
API_KEY = os.environ["API_KEY"]  # ortam değişkeni zorunlu, sabit değer yok
# FastAPI uygulaması. Aşağıdaki endpoint'ler bu nesneye bağlanır; uvicorn 'main:app' ile bu nesneyi çalıştırır.
app = FastAPI()

# CORS ayarı: tarayıcının başka adreslerden yaptığı isteklere izin verir.
# Servis yalnız 127.0.0.1'de dinlediği için '*' kabul edilebilir; dışarı açılırsa bu ayar gözden geçirilmeli.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("Whisper modeli yükleniyor...")
# Whisper 'tiny' en küçük ve en hızlı modeldir; doğruluğu sınırlıdır (bu yüzden halüsinasyon filtresi var).
# int8: model ağırlıklarını küçültür, RAM ve CPU kullanımını azaltır.
stt_model = WhisperModel("tiny", device="cpu", compute_type="int8")
logger.info("✅ Whisper hazır")

# Yerel çeviri (Argos Translate tr→en, CTranslate2) — 2026-10-16: Google bu sunucunun
# IP'sini engellediği için ücretsiz GoogleTranslator yerine. Model: models/ (gitignore'da)
logger.info("Çeviri modeli yükleniyor...")
CEVIRI_DIZIN = "models/translate-tr_en-1_5"
# Argos çevirisinin CTranslate2 motoru (CPU, int8).
# inter_threads / intra_threads: kaç iş parçacığı kullanılacağı. Değerler küçük tutulmuş; gerekçesi kodda yazılı değil (TODO(kontrol): sunucudaki diğer servislerle CPU paylaşımı olabilir).
ceviri_model = ctranslate2.Translator(
    f"{CEVIRI_DIZIN}/model", device="cpu", compute_type="int8",
    inter_threads=1, intra_threads=2,
)
ceviri_sp = spm.SentencePieceProcessor(model_file=f"{CEVIRI_DIZIN}/sentencepiece.model")
# Desteklenen (kaynak, hedef) dil çiftleri. Yeni dil eklemek için hem bu kümeye hem de ilgili Argos çeviri paketine ihtiyaç var.
CEVIRI_CIFTLERI = {("tr", "en")}
logger.info("✅ Çeviri hazır")

def cevir(text: str, source: str, target: str) -> str:
    """
    Verilen metni kaynak dilden hedef dile çevirir (şu an yalnız tr→en).
    Metin cümlelere bölünür, Argos (yerel CTranslate2 modeli) ile toplu çevrilir ve
    sonuçlar tek boşlukla birleştirilir. Desteklenmeyen dil çiftinde HTTP 400 fırlatır.
    Metin boşsa boş string döner; çağıran taraf bunu kontrol eder.
    """
    if (source, target) not in CEVIRI_CIFTLERI:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen dil çifti: {source}→{target}")
    # Model cümle düzeyinde eğitildi; uzun metni cümlelere bölüp toplu çevir
    cumleler = [c for c in re.split(r"(?<=[.!?…])\s+", text.strip()) if c]
    if not cumleler:
        return ""
    sonuc = ceviri_model.translate_batch(
        [ceviri_sp.encode(c, out_type=str) for c in cumleler],
        beam_size=2, max_decoding_length=256,
    )
    return " ".join(ceviri_sp.decode(r.hypotheses[0]) for r in sonuc)

logger.info("Kokoro modeli yükleniyor...")
# Kokoro TTS (ONNX): metinden İngilizce ses üretir. Model dosyaları bu klasörde olmalı; yoksa servis açılışta hata verir.
kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
logger.info("✅ Kokoro hazır")

# Whisper sessizlikte veya gürültüde sık uydurduğu kalıplar (ör. 'altyazı', 'abone ol').
# Metin bunlardan birini içeriyorsa reddedilir. DİKKAT: eşleşme 'içerir' mantığıyla yapılır; kısa parçalar normal konuşmada da geçebilir.
HALLUCINATIONS = [
    "altyazı", "subtitle", "abone ol", "subscribe", "m.k",
    "teşekkür", "thanks for watching", "sesli betim",
    "audio description", "bu dizinin", "derneği", "betimleme"
]

class SynthesizeRequest(BaseModel):
    """
    /synthesize endpoint'inin gövde (JSON) modeli.
    audio_base64 veya text alanlarından biri dolu olmalı. İkisi de boşsa davranış kodda ayrıca kontrol edilmiyor (TODO(kontrol)).
    peer_id ve session_id şu an kodda kullanılmıyor; şema gereği alınıyor.
    """
    audio_base64: str = ""
    text: str = ""
    peer_id: str
    source_lang: str = "tr"
    target_lang: str = "en"
    session_id: str = ""

class VoiceProfileRequest(BaseModel):
    """
    /voice-profile endpoint'inin gövde modeli.
    audio_base64: kaydedilecek ses (base64). peer_id: dosya adı olacağı için yalnız
    güvenli karakterler kabul edilir (PEER_ID_PATTERN, yol üzerinden saldırıyı engeller).
    """
    audio_base64: str
    peer_id: str = Field(pattern=PEER_ID_PATTERN)

def verify_api_key(x_api_key: str = Header(...)):
    # compare_digest: iki metni, içerikleri hakkında zamanlama farkı vermeden karşılaştırır.
    # '==' kullanılsaydı yanıt süresinden anahtar tahmin edilebilirdi (timing attack).
    """
    İstekteki x-api-key başlığını ortam değişkenindeki API_KEY ile karşılaştırır.
    Eşleşmezse HTTP 401 fırlatır, eşleşirse anahtarı döner.
    Not: bu bir FastAPI Depends değildir; her endpoint bunu kendisi elle çağırır.
    """
    if not hmac.compare_digest(x_api_key.encode(), API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Geçersiz API key")
    return x_api_key

@app.get("/health")
async def health():
    """
    Servisin ayakta olduğunu gösteren basit kontrol: {"status": "ok"} döner.
    Anahtar istemez. Modellerin yüklü olup olmadığına bakmaz, yalnızca süreç çalışıyor mu bilgisini verir.
    """
    return {"status": "ok"}

@app.post("/voice-profile")
async def save_voice_profile(req: VoiceProfileRequest, x_api_key: str = Header(...)):
    """
    Gönderilen base64 ses kaydını voice_profiles/<peer_id>.wav olarak yazar.
    peer_id, VoiceProfileRequest içinde doğrulandığı için dosya yolu güvenlidir.
    DİKKAT: base64 bozuksa yakalanmış bir hata yok; istemci 500 alır.
    DİKKAT: kaydedilen ses şu an sentezde kullanılmıyor (Kokoro klonlama yapmaz).
    """
    verify_api_key(x_api_key)
    audio_bytes = base64.b64decode(req.audio_base64)
    os.makedirs("voice_profiles", exist_ok=True)
    # peer_id Pydantic'te doğrulandığı için yol güvenli. Buraya doğrulanmamış kullanıcı girdisi konmamalı.
    profile_path = f"voice_profiles/{req.peer_id}.wav"
    with open(profile_path, "wb") as f:
        f.write(audio_bytes)
    logger.info(f"Ses profili kaydedildi: {req.peer_id}")
    return {"success": True, "message": "Ses profili kaydedildi"}

@app.get("/voice-profile/{peer_id}")
async def get_voice_profile(peer_id: str = Path(pattern=PEER_ID_PATTERN), x_api_key: str = Header(...)):
    """
    Verilen peer_id için ses profili dosyasının var olup olmadığını döner: {"exists": True/False}.
    peer_id yol parametresinde de Pydantic ile doğrulanır. Dosya içeriğini okumaz, yalnızca varlığına bakar.
    """
    verify_api_key(x_api_key)
    profile_path = f"voice_profiles/{peer_id}.wav"
    exists = os.path.exists(profile_path)
    return {"exists": exists}

@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest, x_api_key: str = Header(...)):
    """
    Ana endpoint: sesi (veya doğrudan metni) alır, İngilizceye çevirir ve İngilizce ses üretir.
    Akış: (1) text boşsa audio_base64 Whisper ile metne çevrilir ve halüsinasyon filtresinden geçer;
    (2) cevir() ile tr→en çeviri; (3) Kokoro ile WAV üretilip base64 olarak döner.
    Hatalar: 401 yanlış anahtar; 400 ses tanınamadı, çevrilecek metin yok veya desteklenmeyen dil.
    """
    verify_api_key(x_api_key)

    # Metin direkt geldiyse STT'yi atla
    if req.text:
        text = req.text
        # DİKKAT: kullanıcının konuşma metni loga yazılır; log'da kişisel veri olabilir.
        logger.info(f"Direkt metin: {text}")
    else:
        # Whisper bir dosya yolu bekler, bu yüzden gelen ses geçici bir WAV dosyasına yazılır.
        # delete=False: with bloğu bitince dosya silinmesin; silme işini aşağıdaki finally yapar.
        # STT ile ses tanı
        audio_bytes = base64.b64decode(req.audio_base64)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            audio_path = f.name

        try:
            # transcribe segment listesi değil, üreteç (generator) döner. Gerçek tanıma aşağıdaki satırda for/join ile okunduğunda yapılır. İkinci değer kullanılmadığı için _ ile atılır.
            segments, _ = stt_model.transcribe(audio_path, language=req.source_lang)
            text = " ".join([s.text for s in segments]).strip()
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

        if not text:
            raise HTTPException(status_code=400, detail="Ses tanınamadı")

        # DİKKAT: text.lower() Python'un genel küçük harf dönüşümüdür; Türkçe büyük İ harfini doğru çevirmez, bu yüzden büyük harfli bazı kalıplar yakalanmayabilir.
        if any(h in text.lower() for h in HALLUCINATIONS):
            logger.info(f"Halüsinasyon filtrelendi: {text}")
            raise HTTPException(status_code=400, detail="Ses tanınamadı")

        logger.info(f"STT: {text}")

    # Çeviri
    translated = cevir(text, req.source_lang, req.target_lang)
    if not translated:
        raise HTTPException(status_code=400, detail="Çevrilecek metin yok")
    logger.info(f"Çeviri: {translated}")

    # Kokoro TTS
    # DİKKAT: aşağıdaki iki dal aynı değeri veriyor (af_heart, en-us); hedef dile göre ses seçimi şu an yok.
    # TODO(kontrol): hedef dil İngilizce dışında olursa ses ayarının nasıl yapılacağı kararlaştırılmamış.
    if req.target_lang == "en":
        voice = "af_heart"
        lang = "en-us"
    else:
        voice = "af_heart"
        lang = "en-us"

    # Kokoro sentezi senkron (bloklayıcı) bir çağrıdır. async endpoint içinde çalıştığı için bu süre boyunca sunucu diğer istekleri geciktirebilir.
    # DİKKAT: yük artarsa bu çağrı ayrı bir thread'e taşınmalı. speed=1.0 normal konuşma hızıdır.
    samples, sample_rate = kokoro.create(translated, voice=voice, speed=1.0, lang=lang)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = f.name

    try:
        # soundfile dosya yolu bekler; ses önce geçici WAV dosyasına yazılır, sonra baytları okunur.
        sf.write(out_path, samples, sample_rate)
        with open(out_path, "rb") as f:
            out_bytes = f.read()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)

    return {
        "audio_base64": base64.b64encode(out_bytes).decode(),
        "text": text,
        "translated": translated,
        # Ses süresi milisaniye cinsinden: örnek sayısı / örnekleme hızı.
        "duration_ms": len(samples) * 1000 // sample_rate
    }
