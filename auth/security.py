"""
Security helpers for password hashing and JWT token generation.
"""
import os
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

try:
    from jose import jwt
except ImportError:
    import jwt


def hash_password(password: str) -> str:
    pw_bytes = password.encode('utf-8')[:72]
    if HAS_BCRYPT:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(pw_bytes, salt).decode('utf-8')
    salt = os.urandom(16).hex()
    h = hashlib.sha256(salt.encode() + pw_bytes).hexdigest()
    return f"sha256${salt}${h}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pw_bytes = plain_password.encode('utf-8')[:72]
        if hashed_password.startswith("sha256$"):
            _, salt, h = hashed_password.split("$")
            return hashlib.sha256(salt.encode() + pw_bytes).hexdigest() == h
        elif HAS_BCRYPT:
            return bcrypt.checkpw(pw_bytes, hashed_password.encode('utf-8'))
        return False
    except Exception:
        return False


def create_jwt(data: Dict[str, Any], secret_key: str, expires_minutes: int = 1440, algorithm: str = "HS256") -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_jwt(token: str, secret_key: str, algorithm: str = "HS256") -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, secret_key, algorithms=[algorithm])
    except Exception:
        return None
