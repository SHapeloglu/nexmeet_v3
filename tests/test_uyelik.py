"""Üyelik akışı testleri. Gerçek MySQL (test konteyneri) ve dosya tabanlı mail kullanır."""
import glob
import os
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

import db

PAROLA = "gizliParola123"
EPOSTA = "ayse@example.com"
AD = "Ayşe Yılmaz"


# ─── Fixture'lar ─────────────────────────────────────────────────────────────

@pytest.fixture
def istemci(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_DIR", str(tmp_path / "mail"))
    import main
    import auth

    auth.limiter.reset()
    with db.islem() as cur:
        cur.execute("DELETE FROM users")  # email_tokens/sessions CASCADE ile silinir
        cur.execute("DELETE FROM mail_log")
    with TestClient(
        main.app,
        base_url="https://testserver",  # Secure çerezlerin gönderilebilmesi için
        headers={"Origin": "http://localhost:8000"},
    ) as c:
        yield c
    auth.limiter.reset()


def mailler():
    klasor = Path(os.environ["MAIL_DIR"])
    return sorted(glob.glob(str(klasor / "*.txt")))


def son_mail_metni():
    dosyalar = mailler()
    assert dosyalar, "Hiç mail yazılmadı"
    return Path(dosyalar[-1]).read_text(encoding="utf-8")


def son_token(tur="dogrulama"):
    yol = "auth/dogrula" if tur == "dogrulama" else "sifre-sifirla"
    eslesme = re.search(re.escape(yol) + r"\?token=([A-Za-z0-9_\-]+)", son_mail_metni())
    assert eslesme, "Mailde bağlantı bulunamadı"
    return eslesme.group(1)


def kayit(c, eposta=EPOSTA, parola=PAROLA, ad=AD):
    r = c.post("/api/auth/kayit", json={"ad_soyad": ad, "eposta": eposta, "parola": parola})
    assert r.status_code == 200, r.text
    return r


def kayit_ve_dogrula(c, eposta=EPOSTA, parola=PAROLA, ad=AD):
    kayit(c, eposta, parola, ad)
    token = son_token("dogrulama")
    r = c.post("/api/auth/dogrula", json={"token": token})
    assert r.status_code == 200, r.text
    return token


def giris(c, eposta=EPOSTA, parola=PAROLA, yonlendirme=None):
    govde = {"eposta": eposta, "parola": parola}
    if yonlendirme is not None:
        govde["yonlendirme"] = yonlendirme
    return c.post("/api/auth/giris", json=govde)


def db_satir(sorgu, parametreler=()):
    with db.islem() as cur:
        cur.execute(sorgu, parametreler)
        return cur.fetchone()


# ─── Tam akış ────────────────────────────────────────────────────────────────

def test_tam_akis_kayit_dogrula_giris_ben_join_cikis(istemci):
    c = istemci
    kayit(c, eposta="Ayse@Example.com")
    # E-posta küçük harfe çevrilip saklanır
    assert db_satir("SELECT email FROM users")["email"] == EPOSTA

    token = son_token("dogrulama")
    # Doğrulanmadan giriş reddedilir
    r = giris(c)
    assert r.status_code == 403 and r.json()["kod"] == "dogrulanmamis"
    assert "nexmeet_oturum" not in r.cookies

    assert c.post("/api/auth/dogrula", json={"token": token}).status_code == 200

    r = giris(c, yonlendirme="/room/abc")
    assert r.status_code == 200, r.text
    assert r.json()["yonlendirme"] == "/room/abc"
    cerez = r.headers["set-cookie"].lower()
    assert "httponly" in cerez and "secure" in cerez and "samesite=lax" in cerez
    assert "max-age=2592000" in cerez  # 30 gün, sabit

    r = c.get("/api/ben")
    assert r.status_code == 200
    assert r.json()["display_name"] == AD and r.json()["email_verified"] is True

    # join-token: istemci "name" gönderse bile ad hesaptan gelir
    r = c.post("/api/join-token", json={"room_id": "toplanti1", "name": "Saldırgan"})
    assert r.status_code == 200, r.text
    jeton, peer = r.json()["token"], r.json()["peer_id"]

    import main
    with c.websocket_connect(f"/ws/toplanti1/{peer}?token={jeton}") as ws:
        mesaj = ws.receive_json()
        assert mesaj["type"] == "room-joined"
        assert main.manager.peer_names[peer] == AD

    r = c.post("/api/auth/cikis")
    assert r.status_code == 200
    assert c.get("/api/ben").status_code == 401
    assert c.post("/api/join-token", json={"room_id": "toplanti1"}).status_code == 401


def test_join_token_girissiz_401(istemci):
    r = istemci.post("/api/join-token", json={"room_id": "oda"})
    assert r.status_code == 401


def test_join_token_dogrulanmamis_kullanici_401(istemci):
    import hashlib
    kayit(istemci)  # hesap doğrulanmadı
    # Geçerli bir oturum kaydı olsa bile doğrulanmamış hesap için 401 (oturumu doğrudan DB'ye yazıyoruz)
    ham = "elle-olusturulmus-oturum-token-degeri-1234567890"
    with db.islem() as cur:
        cur.execute("INSERT INTO sessions (user_id, token_hash, created_at, expires_at) "
                    "SELECT id, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP() + INTERVAL 1 DAY FROM users",
                    (hashlib.sha256(ham.encode()).hexdigest(),))
    istemci.cookies.set("nexmeet_oturum", ham)
    assert istemci.post("/api/join-token", json={"room_id": "oda"}).status_code == 401
    assert istemci.get("/api/ben").status_code == 401


# ─── Kayıt ───────────────────────────────────────────────────────────────────

def test_kayit_dogrulama_girdileri(istemci):
    c = istemci
    gecersiz = [
        {"ad_soyad": "A", "eposta": EPOSTA, "parola": PAROLA},                 # ad çok kısa
        {"ad_soyad": "x" * 51, "eposta": EPOSTA, "parola": PAROLA},            # ad çok uzun
        {"ad_soyad": AD, "eposta": "bozuk-eposta", "parola": PAROLA},          # e-posta biçimi
        {"ad_soyad": AD, "eposta": EPOSTA, "parola": "kisa9char"},            # 9 karakter
        {"ad_soyad": AD, "eposta": EPOSTA, "parola": "p" * 129},               # 129 karakter
        {"ad_soyad": "Bir\x07Zil", "eposta": EPOSTA, "parola": PAROLA},       # kontrol karakteri
    ]
    import auth
    for govde in gecersiz:
        auth.limiter.reset()  # geçersiz istekler de hız sınırına sayılır; her durum ayrı ölçülsün
        assert c.post("/api/auth/kayit", json=govde).status_code == 400, govde
    assert mailler() == []


def test_kayitli_eposta_sessiz_kalir(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    onceki_mail = len(mailler())
    r = c.post("/api/auth/kayit", json={"ad_soyad": "Başka Biri", "eposta": EPOSTA, "parola": "baskaParola99"})
    assert r.status_code == 200 and r.json()["mesaj"] == "Doğrulama e-postası gönderildi (kayıtlıysa)."
    assert len(mailler()) == onceki_mail          # mail gitmedi
    assert db_satir("SELECT display_name FROM users")["display_name"] == AD  # değişmedi
    assert giris(c).status_code == 200            # eski parola geçerli


def test_kayitsiz_eposta_ve_kayitli_ayni_yanit(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    r1 = c.post("/api/auth/dogrulama-tekrar", json={"eposta": "yok@example.com"})
    r2 = c.post("/api/auth/dogrulama-tekrar", json={"eposta": "yok@example.com"})
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == {"mesaj": "Doğrulama e-postası gönderildi (kayıtlıysa)."}


def test_origin_reddi(istemci):
    r = istemci.post(
        "/api/auth/kayit",
        json={"ad_soyad": AD, "eposta": EPOSTA, "parola": PAROLA},
        headers={"Origin": "https://kotu-site.example"},
    )
    assert r.status_code == 403
    assert mailler() == []


# ─── Giriş ve kilit ──────────────────────────────────────────────────────────

def test_yanlis_parola_ve_kayitsiz_eposta_ayni_mesaj(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    yanlis = giris(c, parola="yanlisParola999")
    kayitsiz = giris(c, eposta="yok@example.com")
    assert yanlis.status_code == kayitsiz.status_code == 401
    assert yanlis.json()["detail"] == kayitsiz.json()["detail"]


def test_hesap_kilidi_ve_sayac_sifirlanmasi(istemci):
    c = istemci
    import auth
    kayit_ve_dogrula(c)
    for _ in range(10):
        assert giris(c, parola="yanlisParola999").status_code == 401
    # Kilit: doğru parola da reddedilir (limit sayacı için sıfırla)
    auth.limiter.reset()
    assert giris(c).status_code == 401
    assert db_satir("SELECT locked_until FROM users")["locked_until"] is not None

    # Süre dolunca tekrar girilebilir
    with db.islem() as cur:
        cur.execute("UPDATE users SET locked_until = UTC_TIMESTAMP() - INTERVAL 1 MINUTE")
    auth.limiter.reset()
    assert giris(c).status_code == 200


def test_basarili_giris_hata_sayacini_sifirlar(istemci):
    c = istemci
    import auth
    kayit_ve_dogrula(c)
    for _ in range(9):
        giris(c, parola="yanlisParola999")
    auth.limiter.reset()
    assert giris(c).status_code == 200
    assert db_satir("SELECT failed_logins FROM users")["failed_logins"] == 0


# ─── Token'lar ───────────────────────────────────────────────────────────────

def test_token_yeniden_kullanim_reddi(istemci):
    c = istemci
    token = kayit_ve_dogrula(c)
    r = c.post("/api/auth/dogrula", json={"token": token})
    assert r.status_code == 400
    assert "daha önce kullanılmış" in r.json()["detail"]


def test_suresi_dolmus_dogrulama_tokeni_reddi(istemci):
    c = istemci
    kayit(c)
    token = son_token("dogrulama")
    with db.islem() as cur:
        cur.execute("UPDATE email_tokens SET expires_at = UTC_TIMESTAMP() - INTERVAL 1 MINUTE")
    r = c.post("/api/auth/dogrula", json={"token": token})
    assert r.status_code == 400
    assert "süresi dolmuş" in r.json()["detail"]
    assert giris(c).status_code == 403  # hesap hâlâ doğrulanmamış


def test_token_turu_karisamaz(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    c.post("/api/auth/sifre-unuttum", json={"eposta": EPOSTA})
    sifirlama_tokeni = son_token("sifirlama")
    # Sıfırlama tokeni doğrulama ucunda geçersiz
    assert c.post("/api/auth/dogrula", json={"token": sifirlama_tokeni}).status_code == 400


def test_token_db_de_yalniz_ozet(istemci):
    import hashlib
    kayit(istemci, eposta="ozet@example.com")
    token = son_token("dogrulama")
    satir = db_satir("SELECT token_hash FROM email_tokens ORDER BY id DESC LIMIT 1")
    assert satir["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert satir["token_hash"] != token


# ─── Parola sıfırlama ────────────────────────────────────────────────────────

def test_parola_sifirlama_eski_oturumu_dusurur(istemci):
    c = istemci
    import auth
    kayit_ve_dogrula(c)
    assert giris(c).status_code == 200
    assert c.get("/api/ben").status_code == 200

    assert c.post("/api/auth/sifre-unuttum", json={"eposta": EPOSTA}).status_code == 200
    token = son_token("sifirlama")
    yeni = "yeniParola2024"
    r = c.post("/api/auth/sifre-sifirla", json={"token": token, "parola": yeni})
    assert r.status_code == 200, r.text

    # Eski oturum düşer
    assert c.get("/api/ben").status_code == 401
    # Eski parola çalışmaz, yeni parola çalışır
    auth.limiter.reset()
    assert giris(c, parola=PAROLA).status_code == 401
    auth.limiter.reset()
    assert giris(c, parola=yeni).status_code == 200
    # Sıfırlama tokeni tek kullanımlık
    assert c.post("/api/auth/sifre-sifirla", json={"token": token, "parola": "ucuncuParola77"}).status_code == 400


def test_sifirlama_suresi_dolmus_token(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    c.post("/api/auth/sifre-unuttum", json={"eposta": EPOSTA})
    token = son_token("sifirlama")
    with db.islem() as cur:
        cur.execute("UPDATE email_tokens SET expires_at = UTC_TIMESTAMP() - INTERVAL 1 MINUTE "
                    "WHERE kind = 'sifirlama'")
    r = c.post("/api/auth/sifre-sifirla", json={"token": token, "parola": "yeniParola2024"})
    assert r.status_code == 400 and "süresi dolmuş" in r.json()["detail"]


def test_sifre_unuttum_kayitsiz_sessiz(istemci):
    r = istemci.post("/api/auth/sifre-unuttum", json={"eposta": "yok@example.com"})
    assert r.status_code == 200
    assert mailler() == []


# ─── Açık yönlendirme ve sayfa geçidi ────────────────────────────────────────

@pytest.mark.parametrize("girdi,beklenen", [
    ("/room/abc", "/room/abc"),
    ("/room/Toplantı-1", "/room/Toplantı-1"),
    ("/", "/"),
    (None, "/"),
    ("", "/"),
    ("https://kotu.example", "/"),
    ("//kotu.example", "/"),
    ("/\\kotu.example", "/"),
    ("/room/../../x", "/"),
    ("/room/a?x=1", "/"),
    ("/room/a%0d%0aSet-Cookie", "/"),
    ("javascript:alert(1)", "/"),
    ("/room/" + "a" * 65, "/"),
])
def test_guvenli_yonlendirme(girdi, beklenen):
    import auth
    assert auth.guvenli_yonlendirme(girdi) == beklenen


def test_giris_acik_yonlendirme_reddedilir(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    r = giris(c, yonlendirme="https://kotu.example/phish")
    assert r.status_code == 200 and r.json()["yonlendirme"] == "/"


def test_oda_sayfasi_girissiz_girise_yonlenir(istemci):
    r = istemci.get("/room/abc", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/giris?next=%2Froom%2Fabc"
    r = istemci.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/giris?next=%2F"


def test_oda_sayfasi_girisli_acilir(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    assert giris(c).status_code == 200
    r = c.get("/room/abc", follow_redirects=False)
    assert r.status_code == 200
    assert "NexMeet" in r.text


def test_uyelik_sayfalari_acilir(istemci):
    for yol in ["/giris", "/kayit", "/auth/dogrula", "/sifre-unuttum", "/sifre-sifirla"]:
        assert istemci.get(yol).status_code == 200, yol


# ─── Hız sınırı ──────────────────────────────────────────────────────────────

def test_kayit_hiz_siniri(istemci):
    c = istemci
    for i in range(5):
        assert c.post("/api/auth/kayit", json={"ad_soyad": AD, "eposta": f"k{i}@example.com",
                                               "parola": PAROLA}).status_code == 200
    assert c.post("/api/auth/kayit", json={"ad_soyad": AD, "eposta": "k9@example.com",
                                           "parola": PAROLA}).status_code == 429


def test_giris_hiz_siniri(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    kodlar = [giris(c, parola="yanlisParola999").status_code for _ in range(11)]
    assert kodlar[:10] == [401] * 10
    assert kodlar[10] == 429


def test_mail_gunluk_kotasi(istemci):
    c = istemci
    import auth
    kayit(c)  # 1. mail
    for _ in range(4):  # 2.–5. mail (istek başına 3/saat IP sınırı için sıfırlanır)
        auth.limiter.reset()
        c.post("/api/auth/dogrulama-tekrar", json={"eposta": EPOSTA})
    assert len(mailler()) == 5
    auth.limiter.reset()
    c.post("/api/auth/dogrulama-tekrar", json={"eposta": EPOSTA})
    assert len(mailler()) == 5  # 24 saatte en çok 5 mail


# ─── Hesap silme ─────────────────────────────────────────────────────────────

def test_hesap_silme(istemci):
    c = istemci
    import auth
    kayit_ve_dogrula(c)
    assert giris(c).status_code == 200

    r = c.post("/api/auth/hesabi-sil", json={"parola": "yanlisParola999"})
    assert r.status_code == 403
    assert db_satir("SELECT COUNT(*) AS n FROM users")["n"] == 1

    r = c.post("/api/auth/hesabi-sil", json={"parola": PAROLA})
    assert r.status_code == 200
    assert db_satir("SELECT COUNT(*) AS n FROM users")["n"] == 0
    assert db_satir("SELECT COUNT(*) AS n FROM sessions")["n"] == 0
    assert c.get("/api/ben").status_code == 401

    auth.limiter.reset()
    assert giris(c).status_code == 401


def test_hesap_silme_girissiz_401(istemci):
    r = istemci.post("/api/auth/hesabi-sil", json={"parola": PAROLA})
    assert r.status_code == 401


def test_hesabim_sayfasi_girissiz_girise_yonlenir(istemci):
    r = istemci.get("/hesabim", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/giris?next=%2Fhesabim"


def test_hesabim_sayfasi_girisli_acilir(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    assert giris(c).status_code == 200
    r = c.get("/hesabim", follow_redirects=False)
    assert r.status_code == 200
    assert 'id="hesapSilForm"' in r.text
    assert 'id="silBtn"' in r.text
    assert "/static/js/hesabim.js" in r.text


def test_cikis_oturumu_db_den_siler(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    giris(c)
    assert db_satir("SELECT COUNT(*) AS n FROM sessions")["n"] == 1
    c.post("/api/auth/cikis")
    assert db_satir("SELECT COUNT(*) AS n FROM sessions")["n"] == 0


def test_suresi_dolmus_oturum_reddedilir(istemci):
    c = istemci
    kayit_ve_dogrula(c)
    giris(c)
    with db.islem() as cur:
        cur.execute("UPDATE sessions SET expires_at = UTC_TIMESTAMP() - INTERVAL 1 MINUTE")
    assert c.get("/api/ben").status_code == 401


# ─── Sağlık ve veritabanı hatası ─────────────────────────────────────────────

def test_saglik_db_tamam(istemci):
    r = istemci.get("/api/saglik")
    assert r.json() == {"durum": "tamam", "db": "tamam"}


def test_db_erisilemezse_uyelik_503_toplanti_calisir(istemci, monkeypatch):
    c = istemci
    monkeypatch.setenv("DB_PORT", "33998")  # kapalı port
    r = giris(c)
    assert r.status_code == 503
    assert c.get("/api/saglik").json() == {"durum": "tamam", "db": "hata"}
    # Veritabanından bağımsız toplantı uçları çalışmaya devam eder
    assert c.get("/api/room/oda/info").status_code == 200
    monkeypatch.undo()
    assert c.get("/api/saglik").json()["db"] == "tamam"


# ─── Güvenlik yardımcıları ───────────────────────────────────────────────────

def test_mail_html_kacislanir():
    import mailer
    posta = mailer.dogrulama_postasi("a@example.com", "<script>alert(1)</script>",
                                     "http://localhost:8000/auth/dogrula?token=abc")
    assert "<script>" not in posta["html"]
    assert "&lt;script&gt;" in posta["html"]


def test_parola_hash_argon2(istemci):
    kayit(istemci)
    hash_ = db_satir("SELECT password_hash FROM users")["password_hash"]
    assert hash_.startswith("$argon2id$")
    assert PAROLA not in hash_
