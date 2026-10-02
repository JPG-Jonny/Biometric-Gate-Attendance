import os
from urllib.parse import urlparse
from dotenv import load_dotenv


def base_url():
    load_dotenv('.env.terminal')
    url = os.environ.get('API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost','127.0.0.1','::1'}):
        raise ValueError('Use HTTPS for non-loopback API URLs')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Do not put credentials, queries or fragments in API_BASE_URL')
    return url


def terminal_settings():
    url = base_url()
    terminal = os.environ['TERMINAL_UUID']
    token = os.environ['TERMINAL_API_TOKEN']
    direction = os.environ.get('TERMINAL_DIRECTION', 'IN')
    if len(token) < 32 or direction not in {'IN','OUT'}:
        raise ValueError('Set a random token (32+ characters) and an IN/OUT direction')
    return url, terminal, token, direction
