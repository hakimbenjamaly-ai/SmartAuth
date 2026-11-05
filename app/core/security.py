"""تجزئة كلمات المرور باستخدام PBKDF2-HMAC-SHA256 (مكتبة Python القياسية، دون إنترنت)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

ITERATIONS = 310_000


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    if not password or len(password) < 6:
        raise ValueError("كلمة المرور يجب ألا تقل عن 6 أحرف")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, it, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(it))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def sha256_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
