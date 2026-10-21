"""MySQL erişimi (PyMySQL, senkron).

Bu modüldeki fonksiyonlar bloklayıcıdır; async uçlardan `asyncio.to_thread`
ile çağrılmalıdır. Her işlem kendi bağlantısını açar ve kapatır.
"""
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone

import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger("nexmeet.db")

SEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        email           VARCHAR(254) NOT NULL,
        display_name    VARCHAR(100) NOT NULL,
        password_hash   VARCHAR(255) NOT NULL,
        email_verified  TINYINT(1)   NOT NULL DEFAULT 0,
        created_at      DATETIME     NOT NULL,
        failed_logins   INT          NOT NULL DEFAULT 0,
        locked_until    DATETIME     NULL,
        UNIQUE KEY uq_users_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS email_tokens (
        id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id     INT UNSIGNED NOT NULL,
        kind        ENUM('dogrulama', 'sifirlama') NOT NULL,
        token_hash  CHAR(64)     NOT NULL,
        expires_at  DATETIME     NOT NULL,
        used_at     DATETIME     NULL,
        UNIQUE KEY uq_email_tokens_hash (token_hash),
        CONSTRAINT fk_email_tokens_user FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id     INT UNSIGNED NOT NULL,
        token_hash  CHAR(64)     NOT NULL,
        created_at  DATETIME     NOT NULL,
        expires_at  DATETIME     NOT NULL,
        ip          VARCHAR(45)  NULL,
        user_agent  VARCHAR(255) NULL,
        UNIQUE KEY uq_sessions_hash (token_hash),
        KEY ix_sessions_user (user_id),
        CONSTRAINT fk_sessions_user FOREIGN KEY (user_id)
            REFERENCES users (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS mail_log (
        id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        email       VARCHAR(254) NOT NULL,
        kind        VARCHAR(20)  NOT NULL,
        created_at  DATETIME     NOT NULL,
        KEY ix_mail_log_email (email, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

_sema_hazir = False


def simdi() -> datetime:
    """UTC zamanı, tzsiz (MySQL DATETIME ile uyumlu)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _baglan():
    # Parola asla loglanmaz; hata mesajlarında yalnız host/port/ad yer alır.
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "nexmeet"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
        autocommit=False,
    )


def sema_olustur() -> None:
    """Tabloları yoksa oluşturur. Başarısızsa istisna fırlatır."""
    global _sema_hazir
    conn = _baglan()
    try:
        with conn.cursor() as cur:
            for ddl in SEMA:
                cur.execute(ddl)
        conn.commit()
    finally:
        conn.close()
    _sema_hazir = True


@contextmanager
def islem():
    """Tek bağlantıda işlem. Blok normal biterse commit, istisnada rollback."""
    if not _sema_hazir:
        sema_olustur()
    conn = _baglan()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def kontrol() -> None:
    """Sağlık kontrolü: veritabanına bağlanıp SELECT 1 çalıştırır."""
    with islem() as cur:
        cur.execute("SELECT 1 AS ok")
        cur.fetchone()
