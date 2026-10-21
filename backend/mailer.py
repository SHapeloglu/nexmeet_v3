"""E-posta gönderimi.

MAIL_BACKEND=smtp  (varsayılan): SMTP sunucusuna STARTTLS ile gönderir.
MAIL_BACKEND=dosya: gerçek mail göndermez; MAIL_DIR klasörüne .txt yazar (test).

Parola veya anahtar hiçbir zaman loglanmaz.
"""
import html
import logging
import os
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger("nexmeet.mail")

BASE_DIR = Path(__file__).resolve().parent.parent


def _kac(metin: str) -> str:
    return html.escape(metin, quote=True)


def _html_sablon(baslik: str, govde_html: str, buton_metni: str, link: str) -> str:
    """Sade, mobil uyumlu Türkçe HTML e-posta gövdesi."""
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:24px;background:#f4f4f7;font-family:Arial,Helvetica,sans-serif;color:#1c1c28;">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px;">
<div style="font-size:20px;font-weight:bold;margin-bottom:12px;">NexMeet</div>
<h1 style="font-size:18px;margin:0 0 16px 0;">{_kac(baslik)}</h1>
{govde_html}
<p style="margin:24px 0;"><a href="{_kac(link)}" style="display:inline-block;background:#6EE7B7;color:#0a0a0f;text-decoration:none;padding:12px 20px;border-radius:10px;font-weight:bold;">{_kac(buton_metni)}</a></p>
<p style="font-size:12px;color:#6b6b80;">Buton çalışmazsa bu bağlantıyı tarayıcınıza yapıştırın:<br>{_kac(link)}</p>
</div>
</body></html>"""


def dogrulama_postasi(alici: str, ad: str, link: str) -> dict:
    """Hesap e-posta doğrulama maili (24 saat geçerli bağlantı)."""
    konu = "NexMeet — e-posta adresinizi doğrulayın"
    metin = (
        f"Merhaba {ad},\n\n"
        "NexMeet hesabınızı etkinleştirmek için aşağıdaki bağlantıya tıklayın.\n"
        "Bağlantı 24 saat geçerlidir ve yalnız bir kez kullanılabilir.\n\n"
        f"{link}\n\n"
        "Bu kaydı siz yapmadıysanız bu e-postayı yok sayabilirsiniz.\n"
    )
    govde = (
        f'<p style="font-size:15px;line-height:1.5;">Merhaba {_kac(ad)},</p>'
        '<p style="font-size:15px;line-height:1.5;">NexMeet hesabınızı etkinleştirmek için '
        'aşağıdaki düğmeye tıklayın. Bağlantı 24 saat geçerlidir.</p>'
    )
    return {
        "alici": alici,
        "konu": konu,
        "metin": metin,
        "html": _html_sablon("E-posta adresinizi doğrulayın", govde,
                             "E-postamı doğrula", link),
    }


def sifirlama_postasi(alici: str, ad: str, link: str) -> dict:
    """Parola sıfırlama maili (1 saat geçerli, tek kullanımlık bağlantı)."""
    konu = "NexMeet — parola sıfırlama"
    metin = (
        f"Merhaba {ad},\n\n"
        "Parolanızı sıfırlamak için aşağıdaki bağlantıya tıklayın.\n"
        "Bağlantı 1 saat geçerlidir ve yalnız bir kez kullanılabilir.\n\n"
        f"{link}\n\n"
        "Bu isteği siz yapmadıysanız bu e-postayı yok sayın; parolanız değişmeyecektir.\n"
    )
    govde = (
        f'<p style="font-size:15px;line-height:1.5;">Merhaba {_kac(ad)},</p>'
        '<p style="font-size:15px;line-height:1.5;">Parolanızı sıfırlamak için aşağıdaki '
        'düğmeye tıklayın. Bağlantı 1 saat geçerlidir.</p>'
        '<p style="font-size:13px;color:#6b6b80;">Bu isteği siz yapmadıysanız bu e-postayı '
        'yok sayın; parolanız değişmeyecektir.</p>'
    )
    return {
        "alici": alici,
        "konu": konu,
        "metin": metin,
        "html": _html_sablon("Parola sıfırlama", govde, "Parolamı sıfırla", link),
    }


def _dosyaya_yaz(posta: dict) -> None:
    klasor = Path(os.getenv("MAIL_DIR", str(BASE_DIR / "mail_kutusu")))
    klasor.mkdir(parents=True, exist_ok=True)
    zaman = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    dosya = klasor / f"{zaman}_{uuid.uuid4().hex[:8]}.txt"
    dosya.write_text(
        f"Kime: {posta['alici']}\nKonu: {posta['konu']}\n\n{posta['metin']}",
        encoding="utf-8",
    )


def _smtp_gonder(posta: dict) -> None:
    host = os.getenv("SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP_HOST tanımlı değil")
    port = int(os.getenv("SMTP_PORT", "587"))
    kullanici = os.getenv("SMTP_USER", "")
    parola = os.getenv("SMTP_PASSWORD", "")
    gonderen = os.getenv("SMTP_FROM") or kullanici

    mesaj = EmailMessage()
    mesaj["Subject"] = posta["konu"]
    mesaj["From"] = gonderen
    mesaj["To"] = posta["alici"]
    mesaj.set_content(posta["metin"])
    mesaj.add_alternative(posta["html"], subtype="html")

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if kullanici:
            smtp.login(kullanici, parola)
        smtp.send_message(mesaj)


def gonder(posta: dict) -> None:
    """Postayı gönderir; hata olursa istisna fırlatır."""
    backend = os.getenv("MAIL_BACKEND", "smtp").strip().lower()
    if backend == "dosya":
        _dosyaya_yaz(posta)
    elif backend == "smtp":
        _smtp_gonder(posta)
    else:
        raise RuntimeError(f"Bilinmeyen MAIL_BACKEND: {backend}")


def gonder_guvenli(posta: dict) -> bool:
    """Gönderir; hatayı yalnız türüyle birlikte loglar ve False döner."""
    try:
        gonder(posta)
        return True
    except Exception as e:  # noqa: BLE001 - arka plan işi, uygulamayı düşürmemeli
        logger.error("Mail gönderilemedi (%s): %s", type(e).__name__, e)
        return False
