"""Print NEW configuration secrets for local use. Never commit the output."""
import secrets
from cryptography.fernet import Fernet
if __name__=='__main__':
    for name in ('METRICS_TOKEN','TERMINAL_API_TOKEN','POSTGRES_PASSWORD','RUNTIME_DB_PASSWORD'):
        print(name+'='+secrets.token_urlsafe(32))
    for name in ('BIOMETRIC_ENCRYPTION_KEY','QUEUE_ENCRYPTION_KEY','BACKUP_ENCRYPTION_KEY'):
        print(name+'='+Fernet.generate_key().decode())
