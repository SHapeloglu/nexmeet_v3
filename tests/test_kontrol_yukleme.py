"""Yükleme, indirme, kontrol yetkisi ve peer ayrılması testleri. Gerçek MySQL (test konteyneri) ve dosya tabanlı mail kullanır."""
import glob
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db

PAROLA = "gizliParola123"
EPOSTA = "ayse@example.com"
AD = "Ayşe Yılmaz"


# ─── Fixture ve yardımcılar ──────────────────────────────────────────────────

def _durumu_sifirla(main, auth):
    """Hız sınırı sayaçlarını ve bellek içi oda/token/dosya/kontrol durumunu temizler."""
    auth.limiter.reset()
    main.join_tokens.clear()
    main.shared_files.clear()
    main.control_sessions.clear()
    main.manager.rooms.clear()
    main.manager.peer_names.clear()
    main.manager.chat_history.clear()


@pytest.fixture
def istemci(tmp_path, monkeypatch):
    """Her test için temiz durum: geçici yükleme klasörü, sıfırlanmış bellek durumu ve hesaplar, giriş yapılmamış istemci."""
    monkeypatch.setenv("MAIL_DIR", str(tmp_path / "mail"))
    import main
    import auth

    yukleme = tmp_path / "uploads"
    yukleme.mkdir()
    monkeypatch.setattr(main, "UPLOADS_DIR", yukleme)
    _durumu_sifirla(main, auth)
    with db.islem() as cur:
        cur.execute("DELETE FROM users")  # email_tokens/sessions CASCADE ile silinir
        cur.execute("DELETE FROM mail_log")
    with TestClient(
        main.app,
        base_url="https://testserver",  # Secure çerezlerin gönderilebilmesi için
        headers={"Origin": "http://localhost:8000"},
    ) as c:
        yield c
    _durumu_sifirla(main, auth)


def _son_mail_metni():
    """MAIL_DIR altındaki en son yazılmış mailin metnini döner."""
    dosyalar = sorted(glob.glob(str(Path(os.environ["MAIL_DIR"]) / "*.txt")))
    assert dosyalar, "Hiç mail yazılmadı"
    return Path(dosyalar[-1]).read_text(encoding="utf-8")


def _oturum_ac(c):
    """Bir hesap oluşturur, e-postasını doğrular ve giriş yapar (istemci çerezi taşır)."""
    r = c.post("/api/auth/kayit", json={"ad_soyad": AD, "eposta": EPOSTA, "parola": PAROLA})
    assert r.status_code == 200, r.text
    eslesme = re.search(r"auth/dogrula\?token=([A-Za-z0-9_\-]+)", _son_mail_metni())
    assert eslesme, "Mailde doğrulama bağlantısı bulunamadı"
    assert c.post("/api/auth/dogrula", json={"token": eslesme.group(1)}).status_code == 200
    r = c.post("/api/auth/giris", json={"eposta": EPOSTA, "parola": PAROLA})
    assert r.status_code == 200, r.text


def _join(c, oda):
    """Giriş yapmış kullanıcı için verilen odaya join token ve peer_id üretir (her çağrı yeni bir peer)."""
    r = c.post("/api/join-token", json={"room_id": oda})
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["peer_id"]


def _yukle(c, oda, token, peer, ad="rapor.txt", icerik=b"merhaba dunya", ekstra=None):
    """Odaya multipart dosya yükler; ekstra alanlar form verisine eklenir."""
    veri = {"peer_id": peer, "token": token, **(ekstra or {})}
    return c.post(f"/api/upload/{oda}", files={"file": (ad, icerik, "text/plain")}, data=veri)


# ─── Dosya yükleme ───────────────────────────────────────────────────────────

def test_yukleme_gecersiz_token_401(istemci):
    """Geçersiz join token ile dosya yükleme 401 döner ve paylaşım kaydı oluşmaz."""
    import main
    r = _yukle(istemci, "oda1", "gecersiz-token", "peer-yok")
    assert r.status_code == 401
    assert main.shared_files == {}


@pytest.mark.parametrize("dosya_adi", ["zarar.exe", "ZARAR.EXE", "betik.sh"])
def test_yukleme_engelli_uzanti_415(istemci, dosya_adi):
    """Engelli uzantılı dosya (.exe büyük/küçük harf farkı dahil, .sh) 415 ile reddedilir ve kaydedilmez."""
    import main
    _oturum_ac(istemci)
    token, peer = _join(istemci, "oda1")
    r = _yukle(istemci, "oda1", token, peer, ad=dosya_adi)
    assert r.status_code == 415, r.text
    assert main.shared_files == {}


def test_yukleme_boyut_siniri_413(istemci, monkeypatch):
    """MAX_FILE_SIZE aşan dosya 413 ile reddedilir; tam sınır değerindeki dosya kabul edilir."""
    import main
    monkeypatch.setattr(main, "MAX_FILE_SIZE", 100)
    _oturum_ac(istemci)
    token, peer = _join(istemci, "oda1")

    r = _yukle(istemci, "oda1", token, peer, icerik=b"x" * 101)
    assert r.status_code == 413, r.text
    assert main.shared_files == {}

    r = _yukle(istemci, "oda1", token, peer, icerik=b"x" * 100)
    assert r.status_code == 200, r.text


def test_yukleyen_adi_join_tokendan_gelir(istemci):
    """Yükleyen adı istemcinin gönderdiği uploader_name yerine join token'daki hesap adından alınır (yayında, kayıtta ve oda listesinde)."""
    import main
    _oturum_ac(istemci)
    token, peer = _join(istemci, "oda1")
    dinleyici_token, dinleyici_peer = _join(istemci, "oda1")

    with istemci.websocket_connect(f"/ws/oda1/{dinleyici_peer}?token={dinleyici_token}") as ws:
        assert ws.receive_json()["type"] == "room-joined"
        r = _yukle(istemci, "oda1", token, peer, ekstra={"uploader_name": "Saldırgan"})
        assert r.status_code == 200, r.text
        yayin = ws.receive_json()

    file_id = r.json()["file_id"]
    assert yayin["type"] == "file-shared"
    assert yayin["file_id"] == file_id
    assert yayin["uploader"] == AD
    assert main.shared_files[file_id]["uploader"] == AD

    liste = istemci.get("/api/room/oda1/files", params={"token": dinleyici_token}).json()["files"]
    assert [f["uploader"] for f in liste if f["file_id"] == file_id] == [AD]


# ─── Dosya indirme ───────────────────────────────────────────────────────────

def test_indirme_ayni_oda_tokeniyle_icerik_doner(istemci):
    """Dosya yüklendiği odanın token'ı ile indirilir; içerik birebir aynıdır ve attachment olarak sunulur."""
    _oturum_ac(istemci)
    token, peer = _join(istemci, "oda1")
    file_id = _yukle(istemci, "oda1", token, peer, icerik=b"gizli icerik").json()["file_id"]

    r = istemci.get(f"/api/download/{file_id}", params={"token": token})
    assert r.status_code == 200, r.text
    assert r.content == b"gizli icerik"
    assert r.headers["content-disposition"].startswith("attachment")


def test_indirme_baska_oda_tokeni_403(istemci):
    """Başka bir odanın geçerli token'ı ile dosya indirilemez (403)."""
    _oturum_ac(istemci)
    token, peer = _join(istemci, "oda1")
    file_id = _yukle(istemci, "oda1", token, peer).json()["file_id"]
    diger_token, _ = _join(istemci, "oda2")

    r = istemci.get(f"/api/download/{file_id}", params={"token": diger_token})
    assert r.status_code == 403, r.text


def test_indirme_gecersiz_token_401(istemci):
    """Geçersiz token ile dosya indirme 401 döner."""
    _oturum_ac(istemci)
    token, peer = _join(istemci, "oda1")
    file_id = _yukle(istemci, "oda1", token, peer).json()["file_id"]

    r = istemci.get(f"/api/download/{file_id}", params={"token": "gecersiz-token"})
    assert r.status_code == 401, r.text


# ─── Kontrol oturumu oluşturma ───────────────────────────────────────────────

def test_kontrol_istegi_gecersiz_token_401(istemci):
    """Geçersiz token ile kontrol isteği açılamaz (401) ve kontrol oturumu kaydedilmez."""
    import main
    r = istemci.post("/api/control/request", json={"token": "gecersiz-token", "target_peer_id": "hedef"})
    assert r.status_code == 401, r.text
    assert main.control_sessions == {}


def test_kontrol_istegi_dakikada_10_ile_sinirli(istemci):
    """/api/control/request dakikada en fazla 10 istek kabul eder; 11. istek 429 döner."""
    _oturum_ac(istemci)
    token, _ = _join(istemci, "oda1")
    for i in range(10):
        r = istemci.post("/api/control/request", json={"token": token, "target_peer_id": f"hedef{i}"})
        assert r.status_code == 200, r.text

    r = istemci.post("/api/control/request", json={"token": token, "target_peer_id": "hedef-11"})
    assert r.status_code == 429, r.text


def test_kontrol_istegi_oturum_olusturur(istemci):
    """Geçerli token ile istek, kontrolcü ve hedef bilgisi kayıtlı, onaysız bir kontrol oturumu açar; hedef odada değilse sent False döner."""
    import main
    _oturum_ac(istemci)
    token, peer = _join(istemci, "oda1")

    r = istemci.post("/api/control/request", json={"token": token, "target_peer_id": "hedef"})
    assert r.status_code == 200, r.text
    assert r.json()["sent"] is False

    oturum = main.control_sessions[r.json()["session_id"]]
    assert oturum["room_id"] == "oda1"
    assert oturum["controller_peer_id"] == peer
    assert oturum["target_peer_id"] == "hedef"
    assert oturum["approved"] is False


# ─── Kontrol yetkisi (durdurma) ──────────────────────────────────────────────

def test_kontrol_durdurma_yetkisiz_token_403_oturum_kalir(istemci):
    """Ne kontrolcü ne hedef olan peer'in token'ı oturumu durduramaz: 403 döner ve oturum control_sessions içinde kalır."""
    import main
    _oturum_ac(istemci)
    kontrolcu_token, _ = _join(istemci, "oda1")
    _, hedef_peer = _join(istemci, "oda1")
    yabanci_token, _ = _join(istemci, "oda1")
    sid = istemci.post(
        "/api/control/request", json={"token": kontrolcu_token, "target_peer_id": hedef_peer}
    ).json()["session_id"]

    r = istemci.post("/api/control/stop", json={"token": yabanci_token, "session_id": sid})
    assert r.status_code == 403, r.text
    assert sid in main.control_sessions


def test_kontrolcu_durdurunca_oturum_silinir(istemci):
    """Kontrolcünün token'ı ile durdurma başarılı döner ve oturumu control_sessions'tan siler."""
    import main
    _oturum_ac(istemci)
    kontrolcu_token, _ = _join(istemci, "oda1")
    _, hedef_peer = _join(istemci, "oda1")
    sid = istemci.post(
        "/api/control/request", json={"token": kontrolcu_token, "target_peer_id": hedef_peer}
    ).json()["session_id"]

    r = istemci.post("/api/control/stop", json={"token": kontrolcu_token, "session_id": sid})
    assert r.status_code == 200, r.text
    assert sid not in main.control_sessions


# ─── Peer ayrılması (WebSocket) ──────────────────────────────────────────────

def test_onayli_oturumda_hedef_ayrilinca_oturum_silinir(istemci):
    """Onaylı kontrol oturumunda hedef peer'in WebSocket bağlantısı kapanınca oturum control_sessions'tan silinir."""
    import main
    _oturum_ac(istemci)
    kontrolcu_token, _ = _join(istemci, "oda1")
    hedef_token, hedef_peer = _join(istemci, "oda1")

    with istemci.websocket_connect(f"/ws/oda1/{hedef_peer}?token={hedef_token}") as ws:
        assert ws.receive_json()["type"] == "room-joined"

        r = istemci.post("/api/control/request", json={"token": kontrolcu_token, "target_peer_id": hedef_peer})
        assert r.status_code == 200, r.text
        assert r.json()["sent"] is True
        sid = r.json()["session_id"]

        istek = ws.receive_json()
        assert istek["type"] == "control-request" and istek["session_id"] == sid

        r = istemci.post(
            "/api/control/respond",
            json={"token": hedef_token, "session_id": sid, "approved": True},
        )
        assert r.status_code == 200, r.text
        assert main.control_sessions[sid]["approved"] is True

    # Hedef bağlantısı kapandı: sunucu ayrılma yolunda oturumu iptal etmiş olmalı
    assert sid not in main.control_sessions
