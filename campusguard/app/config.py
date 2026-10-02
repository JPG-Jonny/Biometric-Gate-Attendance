import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from cryptography.fernet import Fernet
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    encryption_key: str
    public_origin: str = 'http://127.0.0.1:8000'
    environment: str = 'development'
    metrics_token: str = ''
    session_hours: int = 8
    timezone: str = 'Asia/Kolkata'
    class_start: str = '09:00'
    class_end: str = '16:00'
    face_threshold: float = 0.50
    match_margin: float = 0.05
    cooldown_seconds: int = 30
    max_offline_days: int = 7
    pool_size: int = 8

    def __post_init__(self):
        if not self.database_url:
            raise ValueError('DATABASE_URL is required')
        origin = urlparse(self.public_origin)
        if origin.scheme not in {'http', 'https'} or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username or origin.password:
            raise ValueError('PUBLIC_ORIGIN must be an origin without a path or credentials')
        if self.environment not in {'development', 'production'} or not 1 <= self.session_hours <= 24:
            raise ValueError('Invalid environment or session lifetime')
        if self.environment == 'production' and (origin.scheme != 'https' or len(self.metrics_token) < 32):
            raise ValueError('Production requires HTTPS PUBLIC_ORIGIN and METRICS_TOKEN (32+ characters)')
        Fernet(self.encryption_key.encode())
        ZoneInfo(self.timezone)
        if time.fromisoformat(self.class_start) >= time.fromisoformat(self.class_end):
            raise ValueError('CLASS_START must be before CLASS_END (same-day schedule)')
        if not 0 < self.face_threshold <= 0.6 or not 0 <= self.match_margin <= 0.2:
            raise ValueError('Invalid face threshold or ambiguity margin')
        if not 1 <= self.pool_size <= 64 or not 1 <= self.cooldown_seconds <= 3600:
            raise ValueError('Invalid pool size or cooldown')
        if not 1 <= self.max_offline_days <= 30:
            raise ValueError('MAX_OFFLINE_DAYS must be 1..30')

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            database_url=os.getenv('DATABASE_URL', ''),
            encryption_key=os.getenv('BIOMETRIC_ENCRYPTION_KEY', ''),
            public_origin=os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8000'),
            environment=os.getenv('ENVIRONMENT', 'development'),
            metrics_token=os.getenv('METRICS_TOKEN', ''),
            session_hours=int(os.getenv('SESSION_HOURS', '8')),
            timezone=os.getenv('CAMPUS_TIMEZONE', 'Asia/Kolkata'),
            class_start=os.getenv('CLASS_START', '09:00'),
            class_end=os.getenv('CLASS_END', '16:00'),
            face_threshold=float(os.getenv('FACE_THRESHOLD', '0.50')),
            match_margin=float(os.getenv('MATCH_MARGIN', '0.05')),
            cooldown_seconds=int(os.getenv('COOLDOWN_SECONDS', '30')),
            max_offline_days=int(os.getenv('MAX_OFFLINE_DAYS', '7')),
            pool_size=int(os.getenv('DB_POOL_SIZE', '8')),
        )
