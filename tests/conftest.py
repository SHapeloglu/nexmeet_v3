"""Test ortamı: tek kullanımlık MySQL (docker, 127.0.0.1:33999) ve yerel mail klasörü.

Çalıştırma (proje kökünden):
    TEST_DB_PASSWORD=<docker'a verilen root parolası> nice -n 10 .venv-test/bin/pytest tests -q

Test MySQL'i ortak sunucuya (mysql-ortak) BAĞLANMAZ; yalnız TEST_DB_PORT (varsayılan 33999).
"""
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

_parola = os.getenv("TEST_DB_PASSWORD")
if not _parola:
    pytest.exit(
        "TEST_DB_PASSWORD tanımlı değil. Yalnız tek kullanımlık nexmeet-test-mysql konteyneri için.",
        returncode=2,
    )

os.environ.update({
    "DB_HOST": "127.0.0.1",
    "DB_PORT": os.getenv("TEST_DB_PORT", "33999"),
    "DB_USER": "root",
    "DB_PASSWORD": _parola,
    "DB_NAME": "nexmeet",
    "MAIL_BACKEND": "dosya",
    "PUBLIC_BASE_URL": "http://localhost:8000",
    "ALLOWED_ORIGINS": "http://localhost:8000",
    "SECRET_KEY": "test-secret-key-0123456789abcdef0123456789",
})
