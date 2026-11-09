"""Üyelik: kayıt, e-posta doğrulama, giriş, oturum, parola sıfırlama, hesap silme.

Tasarım notları:
- Parolalar argon2 ile hash'lenir. E-posta küçük harfe çevrilip tekil tutulur.
- Doğrulama ve sıfırlama bağlantıları rastgele 32 baytlık token içerir; veritabanında
  yalnız SHA-256 özeti tutulur. Token tek kullanımlıktır.
- Oturum çerezi (HttpOnly, Secure, SameSite=Lax) de aynı şekilde yalnız özet olarak saklanır.
- Kayıt ve parola sıfırlama uçları, kayıtlı olup olmadığını yanıttan belli etmez.
"""
import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import unicodedata
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import pymysql
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

import db
import mailer

logger = logging.getLogger("nexmeet.auth")

limiter = Limiter(key_func=get_remote_address)
router = APIRouter()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

OTURUM_COOKIE = "nexmeet_oturum"
OTURUM_GUN = 30
DOGRULAMA_SAAT = 24
SIFIRLAMA_SAAT = 1
KILIT_ESIGI = 10
KILIT_DAKIKA = 15
MAIL_KOTA_SAYI = 5
MAIL_KOTA_SAAT = 24
AD_MIN, AD_MAX = 2, 50
PAROLA_MIN, PAROLA_MAX = 10, 128
EPOSTA_MAX = 254

GENEL_GIRIS_HATA = "E-posta veya parola hatalı. Çok sayıda hatalı denemeden sonra hesap 15 dakika kilitlenir."
KAYIT_MESAJ = "Doğrulama e-postası gönderildi (kayıtlıysa)."
TOKEN_HATA = {
    "gecersiz": "Bağlantı geçersiz ya da daha önce kullanılmış.",
    "suresi_dolmus": "Bağlantının süresi dolmuş. Lütfen yeni bir bağlantı isteyin.",
}

# Argon2 parametreleri: OWASP asgari önerisi (512 MB konteyner için uygun bellek)
PH = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
# Kayıtsız e-postalarda da aynı süreyi harcamak için (zamanlama sızıntısını azaltır)
_SAHTE_HASH = PH.hash(secrets.token_urlsafe(24))

EPOSTA_RE = re.compile(r"[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}")
# Güvenli göreli yönlendirme: "/" veya "/room/<id>" (eğik çizgi, ters eğik, sorgu, kaçış içermez)
YONLENDIRME_RE = re.compile(r"/(room/[^/\\?#%\s\x00-\x1f\x7f]{1,64}|hesabim)?")


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def _hash(deger: str) -> str:
    """Verilen metnin SHA-256 özetini (hex) döner. Token'lar veritabanına düz halde değil bu özet olarak yazılır; böylece DB sızsa bile token'lar doğrudan kullanılamaz."""
    return hashlib.sha256(deger.encode("utf-8")).hexdigest()


def _yeni_token() -> tuple[str, str]:
    """Rastgele 32 baytlık (URL-güvenli) bir token üretir ve (token, özeti) çifti döner. Token kullanıcıya gider, veritabanına yalnız özeti yazılır."""
    token = secrets.token_urlsafe(32)
    return token, _hash(token)


def base_url() -> str:
    """Sitenin genel adresini (PUBLIC_BASE_URL, yoksa localhost) sondaki eğik çizgisiz döner. E-posta bağlantıları bu adresle oluşturulur."""
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def _izinli_originler() -> set[str]:
    """ALLOWED_ORIGINS ortam değişkenindeki virgülle ayrılmış adresleri ve genel adresi küme olarak döner. Durum değiştiren isteklerde Origin kontrolü için kullanılır."""
    ham = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000")
    liste = [o.strip().rstrip("/") for o in ham.split(",") if o.strip()]
    liste.append(base_url())
    return set(liste)


def origin_kontrol(request: Request) -> None:
    """Durum değiştiren uçlarda tarayıcı Origin başlığı varsa izinli listede olmalı.

    Origin yoksa (sunucu tarafı istemci) çerez zaten SameSite=Lax ile yalnız aynı site
    isteklerinde gönderilir.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return
    if origin.rstrip("/") not in _izinli_originler():
        raise HTTPException(status_code=403, detail="Geçersiz istek kaynağı.")


def eposta_normalize(ham: Optional[str]) -> str:
    """E-postayı kırpıp küçük harfe çevirir ve biçimini kontrol eder. Geçersizse 400 HTTP hatası fırlatır; geçerliyse temiz adresi döner."""
    eposta = (ham or "").strip().lower()
    if not eposta or len(eposta) > EPOSTA_MAX or not EPOSTA_RE.fullmatch(eposta):
        raise HTTPException(status_code=400, detail="Geçerli bir e-posta adresi girin.")
    return eposta


def ad_dogrula(ham: Optional[str]) -> str:
    """Ad soyadı boşlukları tek boşluğa indirerek temizler, uzunluğunu (AD_MIN-AD_MAX) ve kontrol karakterlerini denetler. Geçersizse 400 hatası fırlatır."""
    ad = " ".join((ham or "").split())
    if not (AD_MIN <= len(ad) <= AD_MAX):
        raise HTTPException(status_code=400, detail=f"Ad soyad {AD_MIN} ile {AD_MAX} karakter arasında olmalıdır.")
    if any(unicodedata.category(c).startswith("C") for c in ad):
        raise HTTPException(status_code=400, detail="Ad soyad geçersiz karakter içeriyor.")
    return ad


def parola_dogrula(parola: Optional[str]) -> None:
    """Parolanın tip ve uzunluk sınırını (PAROLA_MIN-PAROLA_MAX) kontrol eder. Geçersizse 400 hatası fırlatır, geçerliyse bir şey döndürmez."""
    if not isinstance(parola, str) or not (PAROLA_MIN <= len(parola) <= PAROLA_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"Parola en az {PAROLA_MIN}, en çok {PAROLA_MAX} karakter olmalıdır.",
        )


def guvenli_yonlendirme(ham: Optional[str]) -> str:
    """Giriş sonrası dönülecek yolu doğrular. Geçersizse "/" döner (açık yönlendirme yok)."""
    if ham and YONLENDIRME_RE.fullmatch(ham):
        return ham
    return "/"


def _parola_dogru_mu(parola_hash: str, parola: str) -> bool:
    """Verilen parolanın argon2 hash ile eşleşip eşleşmediğini True/False olarak döner. Bozuk hash de False sayılır; istisna dışarı sızmaz."""
    try:
        return PH.verify(parola_hash, parola)
    except (VerificationError, InvalidHashError):
        return False


def _parola_sahte_dogrula(parola: str) -> None:
    """Kayıtlı olmayan e-postalarda da aynı süre harcanması için sahte bir argon2 doğrulaması yapar. Sonucu kullanılmaz; yalnız zamanlamayı dengeler."""
    _parola_dogru_mu(_SAHTE_HASH, parola)


def _ip(request: Request) -> Optional[str]:
    """İsteği yapan istemcinin IP adresini döner (en çok 45 karakter, IPv6 için yeterli). İstemci bilinmiyorsa None döner."""
    return request.client.host[:45] if request.client else None


def _oturum_ac(cur, user_id: int, ip: Optional[str], ua: str, simdi) -> str:
    """Kullanıcı için yeni bir oturum kaydı açar ve ham oturum token'ını döner. Veritabanına yalnız token özeti, IP ve tarayıcı bilgisi yazılır."""
    token, token_hash = _yeni_token()
    cur.execute(
        "INSERT INTO sessions (user_id, token_hash, created_at, expires_at, ip, user_agent) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, token_hash, simdi, simdi + timedelta(days=OTURUM_GUN), ip, (ua or "")[:255]),
    )
    return token


def _cookie_yaz(yanit: JSONResponse, token: str) -> None:
    """Oturum token'ını HttpOnly, Secure ve SameSite=Lax özellikli çerez olarak yanıta ekler. Çerez OTURUM_GUN gün geçerlidir."""
    yanit.set_cookie(
        OTURUM_COOKIE,
        token,
        max_age=OTURUM_GUN * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _cookie_sil(yanit: JSONResponse) -> None:
    """Oturum çerezini, yazarken kullanılan aynı özniteliklerle silmek üzere yanıta ekler. Tarayıcının çerezi düşürmesi için öznitelikler birebir aynı olmalıdır."""
    yanit.delete_cookie(OTURUM_COOKIE, path="/", httponly=True, secure=True, samesite="lax")


def _kullanici_oturumdan(cur, token: Optional[str]) -> Optional[dict]:
    """Verilen oturum token'ından kullanıcıyı bulur. Token yoksa, süresi dolmuşsa, eşleşmezse ya da e-posta doğrulanmamışsa None döner."""
    if not token:
        return None
    token_hash = _hash(token)
    cur.execute(
        "SELECT s.token_hash AS oturum_hash, u.id, u.email, u.display_name, u.email_verified "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = %s AND s.expires_at > %s",
        (token_hash, db.simdi()),
    )
    row = cur.fetchone()
    if not row or not hmac.compare_digest(row["oturum_hash"], token_hash):
        return None
    if not row["email_verified"]:
        return None
    return row


def _kullanici_oturumdan_islem(token: Optional[str]) -> Optional[dict]:
    """Oturum doğrulamasını kendi veritabanı bağlantısıyla çalıştırır. Bloklayıcı olduğu için async uçlarda asyncio.to_thread ile çağrılır."""
    with db.islem() as cur:
        return _kullanici_oturumdan(cur, token)


async def oturumlu_kullanici(request: Request) -> dict:
    """Çerezdeki oturumu doğrular; yoksa 401 fırlatır."""
    row = await asyncio.to_thread(_kullanici_oturumdan_islem, request.cookies.get(OTURUM_COOKIE))
    if not row:
        raise HTTPException(status_code=401, detail="Giriş yapmanız gerekiyor.")
    return row


async def oturum_var_mi(request: Request) -> bool:
    """Sayfa geçitleri için: DB hatasında False döner (kullanıcı girişe yönlenir)."""
    try:
        await oturumlu_kullanici(request)
        return True
    except (HTTPException, pymysql.MySQLError) as e:
        if isinstance(e, pymysql.MySQLError):
            logger.error("Oturum kontrolü veritabanı hatası: %s", e)
        return False


def _mail_kotasi_var(cur, eposta: str) -> bool:
    """Bu e-postaya son MAIL_KOTA_SAAT saatte MAIL_KOTA_SAYI'dan az mail gitmişse True döner. Mail bombalamayı önlemek için kullanılır."""
    cur.execute(
        "SELECT COUNT(*) AS n FROM mail_log WHERE email = %s AND created_at > %s",
        (eposta, db.simdi() - timedelta(hours=MAIL_KOTA_SAAT)),
    )
    return cur.fetchone()["n"] < MAIL_KOTA_SAYI


def _mail_kaydet(cur, eposta: str, tur: str) -> None:
    """Gönderilen mail türünü ve zamanını mail_log tablosuna yazar. Kota kontrolü bu kayıtları sayar."""
    cur.execute(
        "INSERT INTO mail_log (email, kind, created_at) VALUES (%s, %s, %s)",
        (eposta, tur, db.simdi()),
    )


def _token_tuket(cur, token: str, tur: str) -> tuple[Optional[int], Optional[str]]:
    """Token'ı tek kullanımlık olarak tüketir. (kullanıcı_id, hata_kodu) döner."""
    if not isinstance(token, str) or not (20 <= len(token) <= 100):
        return None, "gecersiz"
    token_hash = _hash(token)
    cur.execute(
        "SELECT id, user_id, kind, token_hash, expires_at, used_at "
        "FROM email_tokens WHERE token_hash = %s",
        (token_hash,),
    )
    row = cur.fetchone()
    if (not row or row["kind"] != tur or row["used_at"] is not None
            or not hmac.compare_digest(row["token_hash"], token_hash)):
        return None, "gecersiz"
    simdi = db.simdi()
    if row["expires_at"] <= simdi:
        return None, "suresi_dolmus"
    # Yarış koşulunda iki istekten yalnız biri kazansın
    cur.execute(
        "UPDATE email_tokens SET used_at = %s WHERE id = %s AND used_at IS NULL",
        (simdi, row["id"]),
    )
    if cur.rowcount != 1:
        return None, "gecersiz"
    return row["user_id"], None


def _basarisiz_giris(cur, row: dict, simdi) -> None:
    """Hatalı parola girildiğinde sayacı artırır. KILIT_ESIGI hataya ulaşınca hesabı KILIT_DAKIKA dakika kilitler ve sayacı sıfırlar."""
    sayac = (row["failed_logins"] or 0) + 1
    if sayac >= KILIT_ESIGI:
        cur.execute(
            "UPDATE users SET failed_logins = 0, locked_until = %s WHERE id = %s",
            (simdi + timedelta(minutes=KILIT_DAKIKA), row["id"]),
        )
    else:
        cur.execute("UPDATE users SET failed_logins = %s WHERE id = %s", (sayac, row["id"]))


def _postalari_gonder(postalar: list) -> None:
    """Hazırlanan e-postaları tek tek gönderir. Arka plan görevi olarak çalışır, böylece HTTP yanıtı mail gönderimini beklemez."""
    for posta in postalar:
        mailer.gonder_guvenli(posta)


# ─── Sayfalar ────────────────────────────────────────────────────────────────

@router.get("/giris")
async def sayfa_giris():
    """Giriş sayfasını (giris.html) döner."""
    return FileResponse(FRONTEND_DIR / "giris.html")


@router.get("/kayit")
async def sayfa_kayit():
    """Kayıt sayfasını (kayit.html) döner."""
    return FileResponse(FRONTEND_DIR / "kayit.html")


@router.get("/auth/dogrula")
async def sayfa_dogrula():
    """E-posta doğrulama sayfasını (dogrula.html) döner. Doğrulama bağlantısı bu sayfaya gelir."""
    return FileResponse(FRONTEND_DIR / "dogrula.html")


@router.get("/sifre-unuttum")
async def sayfa_sifre_unuttum():
    """Parola sıfırlama isteme sayfasını (sifre_unuttum.html) döner."""
    return FileResponse(FRONTEND_DIR / "sifre_unuttum.html")


@router.get("/sifre-sifirla")
async def sayfa_sifre_sifirla():
    """Yeni parola belirleme sayfasını (sifre_sifirla.html) döner. Sıfırlama bağlantısı bu sayfaya gelir."""
    return FileResponse(FRONTEND_DIR / "sifre_sifirla.html")


@router.get("/hesabim")
async def sayfa_hesabim(request: Request):
    # Oturumsuz ziyaret girişe yönlenir; giriş sonrası dönüş hedefi YONLENDIRME_RE ile doğrulanır
    if not await oturum_var_mi(request):
        return RedirectResponse(url="/giris?" + urlencode({"next": "/hesabim"}), status_code=302)
    return FileResponse(FRONTEND_DIR / "hesabim.html")


# ─── Kayıt ve doğrulama ──────────────────────────────────────────────────────

class KayitIstek(BaseModel):
    """Kayıt formundan gelen JSON gövdesi: ad_soyad, eposta ve parola alanları. Alanlar boş gelirse doğrulama aşamasında hata verir."""
    ad_soyad: str = ""
    eposta: str = ""
    parola: str = ""


def _kayit_islem(ad: str, eposta: str, parola_hash: str, base: str) -> list:
    """Yeni kullanıcıyı ve doğrulama token'ını veritabanına yazar, doğrulama mailini hazırlar. Kayıtlı e-postalarda hiçbir şey yapmadan boş liste döner; böylece dışarıdan hesap varlığı anlaşılmaz."""
    with db.islem() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (eposta,))
        if cur.fetchone():
            # Kayıtlıysa sessizce hiçbir şey yapılmaz (parola değişmez, mail gitmez)
            return []
        simdi = db.simdi()
        try:
            cur.execute(
                "INSERT INTO users (email, display_name, password_hash, email_verified, "
                "created_at, failed_logins) VALUES (%s, %s, %s, 0, %s, 0)",
                (eposta, ad, parola_hash, simdi),
            )
        except pymysql.err.IntegrityError:
            # Eşzamanlı aynı e-posta kaydı: yanıt aynı kalır
            return []
        user_id = cur.lastrowid
        token, token_hash = _yeni_token()
        cur.execute(
            "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at) "
            "VALUES (%s, 'dogrulama', %s, %s)",
            (user_id, token_hash, simdi + timedelta(hours=DOGRULAMA_SAAT)),
        )
        if not _mail_kotasi_var(cur, eposta):
            return []
        _mail_kaydet(cur, eposta, "dogrulama")
        return [mailer.dogrulama_postasi(eposta, ad, f"{base}/auth/dogrula?token={token}")]


@router.post("/api/auth/kayit")
@limiter.limit("5/hour")
async def kayit(request: Request, istek: KayitIstek, arka_plan: BackgroundTasks):
    """Yeni hesap oluşturma ucu. Girdileri doğrular, parolayı hash'ler ve kaydı yapar. Yanıt her durumda aynıdır, çünkü kayıtlı olup olmadığı yanıttan belli olmamalıdır."""
    origin_kontrol(request)
    ad = ad_dogrula(istek.ad_soyad)
    eposta = eposta_normalize(istek.eposta)
    parola_dogrula(istek.parola)
    # Hash her durumda hesaplanır: kayıtlı/kayıtsız yanıt süreleri birbirine yakın kalır
    parola_hash = await asyncio.to_thread(PH.hash, istek.parola)
    postalar = await asyncio.to_thread(_kayit_islem, ad, eposta, parola_hash, base_url())
    if postalar:
        arka_plan.add_task(_postalari_gonder, postalar)
    return {"mesaj": KAYIT_MESAJ}


class EpostaIstek(BaseModel):
    """Yalnız e-posta alanı içeren istek gövdesi. Doğrulama tekrarı ve parola sıfırlama uçları tarafından kullanılır."""
    eposta: str = ""


def _dogrulama_tekrar_islem(eposta: str, base: str) -> list:
    """Doğrulanmamış bir hesap için eski doğrulama token'larını siler ve yeni bir token üretip mail hazırlar. Kota, hesap yoksa ya da zaten doğrulanmışsa boş liste döner."""
    with db.islem() as cur:
        cur.execute("SELECT id, display_name, email_verified FROM users WHERE email = %s", (eposta,))
        row = cur.fetchone()
        if not row or row["email_verified"]:
            return []
        if not _mail_kotasi_var(cur, eposta):
            return []
        cur.execute(
            "DELETE FROM email_tokens WHERE user_id = %s AND kind = 'dogrulama' AND used_at IS NULL",
            (row["id"],),
        )
        token, token_hash = _yeni_token()
        cur.execute(
            "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at) "
            "VALUES (%s, 'dogrulama', %s, %s)",
            (row["id"], token_hash, db.simdi() + timedelta(hours=DOGRULAMA_SAAT)),
        )
        _mail_kaydet(cur, eposta, "dogrulama")
        return [mailer.dogrulama_postasi(eposta, row["display_name"], f"{base}/auth/dogrula?token={token}")]


@router.post("/api/auth/dogrulama-tekrar")
@limiter.limit("3/hour")
async def dogrulama_tekrar(request: Request, istek: EpostaIstek, arka_plan: BackgroundTasks):
    """Doğrulama mailini yeniden gönderme ucu. Hangi durumda olursa olsun aynı yanıtı döner; hesap varlığı sızmaz."""
    origin_kontrol(request)
    try:
        eposta = eposta_normalize(istek.eposta)
    except HTTPException:
        return {"mesaj": KAYIT_MESAJ}
    postalar = await asyncio.to_thread(_dogrulama_tekrar_islem, eposta, base_url())
    if postalar:
        arka_plan.add_task(_postalari_gonder, postalar)
    return {"mesaj": KAYIT_MESAJ}


def _dogrula_islem(token: str) -> Optional[str]:
    """Doğrulama token'ını tüketir ve kullanıcının e-postasını doğrulanmış yapar. Hata varsa hata kodunu, başarılıysa None döner."""
    with db.islem() as cur:
        user_id, hata = _token_tuket(cur, token, "dogrulama")
        if hata:
            return hata
        cur.execute("UPDATE users SET email_verified = 1 WHERE id = %s", (user_id,))
        return None


class TokenIstek(BaseModel):
    """Yalnız token alanı içeren istek gövdesi. E-posta doğrulama ucu bunu kullanır."""
    token: str = ""


@router.post("/api/auth/dogrula")
async def dogrula(request: Request, istek: TokenIstek):
    """E-posta doğrulama ucu. Token geçersiz ya da süresi dolmuşsa 400 hatası verir; geçerliyse hesabı doğrulanmış yapar."""
    origin_kontrol(request)
    hata = await asyncio.to_thread(_dogrula_islem, istek.token)
    if hata:
        raise HTTPException(status_code=400, detail=TOKEN_HATA[hata])
    return {"mesaj": "E-posta adresiniz doğrulandı. Şimdi giriş yapabilirsiniz."}


# ─── Giriş, oturum, çıkış ────────────────────────────────────────────────────

class GirisIstek(BaseModel):
    """Giriş formundan gelen JSON gövdesi: eposta, parola ve isteğe bağlı yonlendirme alanları. yonlendirme girişten sonra gidilecek yolu belirtir."""
    eposta: str = ""
    parola: str = ""
    yonlendirme: Optional[str] = None


def _giris_islem(eposta: str, parola: str, ip: Optional[str], ua: str) -> tuple[str, Optional[str], Optional[dict]]:
    """Giriş denemesini tek işlemde değerlendirir ve (durum, oturum_token, kullanıcı) üçlüsü döner. Durum: tamam, hata, dogrulanmamis. Hatalı ya da kilitli girişte sayaç güncellenir."""
    with db.islem() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (eposta,))
        row = cur.fetchone()
        if row is None:
            _parola_sahte_dogrula(parola)
            return "hata", None, None
        simdi = db.simdi()
        kilitli = row["locked_until"] is not None and row["locked_until"] > simdi
        dogru = _parola_dogru_mu(row["password_hash"], parola)
        if not dogru:
            if not kilitli:
                _basarisiz_giris(cur, row, simdi)
            return "hata", None, None
        if kilitli:
            return "hata", None, None
        # DİKKAT: argon2 ayarları (time_cost, memory_cost) değişirse eski hash'ler bir sonraki başarılı girişte yeni ayarlarla yeniden hash'lenir.
        # Bu sayede kullanıcı parolasını değiştirmeden güvenlik ayarları yükseltilebilir.
        if PH.check_needs_rehash(row["password_hash"]):
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (PH.hash(parola), row["id"]))
        # Başarılı parola doğrulamasından sonra hatalı deneme sayacı ve kilit sıfırlanır.
        cur.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", (row["id"],))
        if not row["email_verified"]:
            return "dogrulanmamis", None, None
        # Süresi dolmuş oturum kayıtlarını temizler; yeni oturum açılmadan önce tablo şişmesin diye yapılır.
        cur.execute("DELETE FROM sessions WHERE expires_at < %s", (simdi,))
        token = _oturum_ac(cur, row["id"], ip, ua, simdi)
        return "tamam", token, row


@router.post("/api/auth/giris")
@limiter.limit("10/minute")
async def giris(request: Request, istek: GirisIstek):
    """Giriş ucu. Başarılı girişte oturum çerezi yazar ve yönlendirme yolunu döner. Doğrulanmamış hesapta 403, hatalı girişte 401 döner; hata mesajı genel tutulur."""
    origin_kontrol(request)
    yonlendirme = guvenli_yonlendirme(istek.yonlendirme)
    try:
        eposta = eposta_normalize(istek.eposta)
    except HTTPException:
        eposta = None
    parola = istek.parola if isinstance(istek.parola, str) and len(istek.parola) <= PAROLA_MAX else ""
    if eposta is None or not parola:
        await asyncio.to_thread(_parola_sahte_dogrula, "x" * PAROLA_MIN)
        raise HTTPException(status_code=401, detail=GENEL_GIRIS_HATA)

    durum, token, row = await asyncio.to_thread(
        _giris_islem, eposta, parola, _ip(request), request.headers.get("user-agent", "")
    )
    if durum == "hata":
        raise HTTPException(status_code=401, detail=GENEL_GIRIS_HATA)
    if durum == "dogrulanmamis":
        return JSONResponse(
            status_code=403,
            content={
                "detail": "E-posta adresiniz henüz doğrulanmamış. Gelen kutunuzdaki doğrulama bağlantısına tıklayın.",
                "kod": "dogrulanmamis",
            },
        )
    yanit = JSONResponse({
        "ad": row["display_name"],
        "yonlendirme": yonlendirme,
    })
    _cookie_yaz(yanit, token)
    return yanit


@router.get("/api/ben")
async def ben(request: Request):
    """Oturumdaki kullanıcının temel bilgilerini döner. Oturum yoksa 401 hatası verir."""
    kullanici = await oturumlu_kullanici(request)
    return {
        "id": kullanici["id"],
        "email": kullanici["email"],
        "display_name": kullanici["display_name"],
        "email_verified": bool(kullanici["email_verified"]),
    }


def _oturum_sil_islem(token: str) -> None:
    """Verilen token'ın oturum kaydını veritabanından siler. Çıkış işleminde kullanılır."""
    with db.islem() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash(token),))


@router.post("/api/auth/cikis")
async def cikis(request: Request):
    """Çıkış ucu. Oturum kaydını siler ve çerezi temizler. Oturum yoksa da başarılı yanıt döner."""
    origin_kontrol(request)
    token = request.cookies.get(OTURUM_COOKIE)
    if token:
        await asyncio.to_thread(_oturum_sil_islem, token)
    yanit = JSONResponse({"mesaj": "Çıkış yapıldı."})
    _cookie_sil(yanit)
    return yanit


# ─── Parola sıfırlama ────────────────────────────────────────────────────────

def _sifirlama_istek_islem(eposta: str, base: str) -> list:
    """Parola sıfırlama için eski sıfırlama token'larını siler, yenisini üretir ve mail hazırlar. Hesap yoksa ya da kota doluysa boş liste döner."""
    with db.islem() as cur:
        cur.execute("SELECT id, display_name FROM users WHERE email = %s", (eposta,))
        row = cur.fetchone()
        if not row:
            return []
        if not _mail_kotasi_var(cur, eposta):
            return []
        cur.execute(
            "DELETE FROM email_tokens WHERE user_id = %s AND kind = 'sifirlama' AND used_at IS NULL",
            (row["id"],),
        )
        token, token_hash = _yeni_token()
        cur.execute(
            "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at) "
            "VALUES (%s, 'sifirlama', %s, %s)",
            (row["id"], token_hash, db.simdi() + timedelta(hours=SIFIRLAMA_SAAT)),
        )
        _mail_kaydet(cur, eposta, "sifirlama")
        return [mailer.sifirlama_postasi(eposta, row["display_name"], f"{base}/sifre-sifirla?token={token}")]


@router.post("/api/auth/sifre-unuttum")
@limiter.limit("3/hour")
async def sifre_unuttum(request: Request, istek: EpostaIstek, arka_plan: BackgroundTasks):
    """Parola sıfırlama isteme ucu. Hesap var yok fark etmeksizin aynı yanıtı döner; böylece e-postanın kayıtlı olup olmadığı anlaşılmaz."""
    origin_kontrol(request)
    try:
        eposta = eposta_normalize(istek.eposta)
    except HTTPException:
        return {"mesaj": KAYIT_MESAJ}
    postalar = await asyncio.to_thread(_sifirlama_istek_islem, eposta, base_url())
    if postalar:
        arka_plan.add_task(_postalari_gonder, postalar)
    return {"mesaj": KAYIT_MESAJ}


class SifreSifirlaIstek(BaseModel):
    """Sıfırlama formundan gelen JSON gövdesi: token ve yeni parola alanları."""
    token: str = ""
    parola: str = ""


def _sifirla_islem(token: str, parola_hash: str) -> Optional[str]:
    """Sıfırlama token'ını tüketir, yeni parola hash'ini yazar ve kullanıcının tüm oturumlarını siler. Hata varsa hata kodunu, başarılıysa None döner."""
    with db.islem() as cur:
        user_id, hata = _token_tuket(cur, token, "sifirlama")
        if hata:
            return hata
        # Sıfırlama e-posta sahipliğini de kanıtlar: hesap doğrulanmış sayılır
        cur.execute(
            "UPDATE users SET password_hash = %s, email_verified = 1, failed_logins = 0, "
            "locked_until = NULL WHERE id = %s",
            (parola_hash, user_id),
        )
        # Tüm mevcut oturumlar düşer
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        return None


@router.post("/api/auth/sifre-sifirla")
async def sifre_sifirla(request: Request, istek: SifreSifirlaIstek):
    """Parola sıfırlama ucu. Token geçersiz ya da süresi dolmuşsa 400 hatası verir; başarılıysa parola değişir ve tüm oturumlar düşer."""
    origin_kontrol(request)
    parola_dogrula(istek.parola)
    parola_hash = await asyncio.to_thread(PH.hash, istek.parola)
    hata = await asyncio.to_thread(_sifirla_islem, istek.token, parola_hash)
    if hata:
        raise HTTPException(status_code=400, detail=TOKEN_HATA[hata])
    return {"mesaj": "Parolanız güncellendi. Yeni parolanızla giriş yapabilirsiniz."}


# ─── Hesap silme ─────────────────────────────────────────────────────────────

class ParolaIstek(BaseModel):
    """Yalnız parola alanı içeren istek gövdesi. Hesap silme ucu bunu kullanır."""
    parola: str = ""


# Hesap silindiğinde çağrılan geri çağrılar (ör. main.py join token temizliği).
# auth.py main.py'yi import etmez; kayıt main.py tarafından yapılır.
_hesap_silindi_kancalari = []


def hesap_silindi_bildir(user_id: int) -> None:
    for kanca in list(_hesap_silindi_kancalari):
        kanca(user_id)


def _hesap_sil_islem(user_id: int, parola: str) -> Optional[str]:
    """Parolayı doğrulayıp hesabı siler. Dönüş: None (başarılı), parola (yanlış parola), kilit (hesap kilitli) ya da gecersiz (kullanıcı yok)."""
    with db.islem() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            return "gecersiz"
        simdi = db.simdi()
        if row["locked_until"] is not None and row["locked_until"] > simdi:
            return "kilit"
        if not _parola_dogru_mu(row["password_hash"], parola):
            _basarisiz_giris(cur, row, simdi)
            return "parola"
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))  # oturum ve token'lar CASCADE ile silinir
        # Kişisel e-posta, kayıt/doğrulama mail günlüğünde de tutulmaz
        cur.execute("DELETE FROM mail_log WHERE email = %s", (row["email"],))
        hesap_silindi_bildir(user_id)  # bellekteki join token'ları da düşer
        return None


@router.post("/api/auth/hesabi-sil")
@limiter.limit("5/minute")
async def hesabi_sil(request: Request, istek: ParolaIstek):
    """Hesap silme ucu. Kullanıcının parolasını ister; yanlışsa 403, kilitliyse 429 döner. Başarılıysa hesap ve tüm oturumlar silinir."""
    origin_kontrol(request)
    kullanici = await oturumlu_kullanici(request)
    parola = istek.parola if isinstance(istek.parola, str) and len(istek.parola) <= PAROLA_MAX else ""
    hata = await asyncio.to_thread(_hesap_sil_islem, kullanici["id"], parola)
    if hata == "parola":
        raise HTTPException(status_code=403, detail="Parola hatalı.")
    if hata == "kilit":
        raise HTTPException(status_code=429, detail="Çok fazla hatalı deneme. Lütfen daha sonra tekrar deneyin.")
    if hata:
        raise HTTPException(status_code=401, detail="Giriş yapmanız gerekiyor.")
    yanit = JSONResponse({"mesaj": "Hesabınız ve tüm oturumlarınız silindi."})
    _cookie_sil(yanit)
    return yanit
