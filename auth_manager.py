"""
Auth Manager for NebulaLab (Distributed Linux Lab)
Gère l'authentification sécurisée, le hachage des mots de passe et les jetons JWT.
Utilise bcrypt directement pour une compatibilité parfaite avec Python 3.12+.
"""

import os
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

try:
    from jose import jwt, JWTError as PyJWTError
except ImportError:
    import jwt
    from jwt import PyJWTError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.auth")


class AuthManager:
    def __init__(self, db_manager, secret_key: Optional[str] = None, algorithm: str = "HS256"):
        self.db_manager = db_manager
        self.secret_key = secret_key or os.getenv("SECRET_KEY", "nebulalab-super-secret-cluster-key-2026")
        self.algorithm = algorithm
        self.access_token_expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24h

    def get_password_hash(self, password: str) -> str:
        """Hache un mot de passe de manière sécurisée"""
        pw_bytes = password.encode('utf-8')[:72]
        if HAS_BCRYPT:
            salt = bcrypt.gensalt()
            return bcrypt.hashpw(pw_bytes, salt).decode('utf-8')
        else:
            # Fallback SHA256 avec sel
            salt = os.urandom(16).hex()
            h = hashlib.sha256(salt.encode() + pw_bytes).hexdigest()
            return f"sha256${salt}${h}"

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Vérifie un mot de passe"""
        try:
            pw_bytes = plain_password.encode('utf-8')[:72]
            if hashed_password.startswith("sha256$"):
                _, salt, h = hashed_password.split("$")
                return hashlib.sha256(salt.encode() + pw_bytes).hexdigest() == h
            elif HAS_BCRYPT:
                return bcrypt.checkpw(pw_bytes, hashed_password.encode('utf-8'))
            return False
        except Exception as e:
            logger.debug(f"Erreur vérification mot de passe : {e}")
            return False

    async def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authentifie un utilisateur"""
        try:
            user = await self.db_manager.get_user_by_username(username)
            if not user:
                logger.warning(f"Tentative de connexion utilisateur inconnu : {username}")
                return None

            if not self.verify_password(password, user["hashed_password"]):
                logger.warning(f"Mot de passe incorrect pour : {username}")
                return None

            if not user.get("is_active", True):
                logger.warning(f"Compte utilisateur désactivé : {username}")
                return None

            await self.db_manager.update_last_login(user["id"])
            logger.info(f"Authentification réussie pour {username}")
            return user
        except Exception as e:
            logger.error(f"Erreur lors de l'authentification ({username}) : {e}")
            return None

    def create_access_token(self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """Génère un jeton JWT signé"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)

        to_encode.update({"exp": expire, "iat": datetime.utcnow()})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Décode et valide un jeton JWT"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except Exception as e:
            logger.debug(f"Jeton JWT invalide ou expiré : {e}")
            return None

    async def create_user(self, username: str, email: str, password: str, role: str = "admin") -> Optional[Dict[str, Any]]:
        """Crée un utilisateur dans la base de données"""
        try:
            hashed_pwd = self.get_password_hash(password)
            user_id = await self.db_manager.create_user(username, email, hashed_pwd, role)
            if user_id:
                return await self.db_manager.get_user_by_id(user_id)
            return None
        except Exception as e:
            logger.error(f"Erreur création utilisateur {username} : {e}")
            return None

    async def ensure_default_admin(self):
        """S'assure qu'un utilisateur administrateur par défaut existe"""
        try:
            admin = await self.db_manager.get_user_by_username("admin")
            if not admin:
                default_password = os.getenv("ADMIN_PASSWORD", "admin123")
                await self.create_user("admin", "admin@nebulalab.local", default_password, role="admin")
                logger.info(f"Utilisateur admin par défaut créé (username: admin / password: {default_password})")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de l'admin par défaut : {e}")