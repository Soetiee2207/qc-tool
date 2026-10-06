"""Explicit UI-triggered response selectors and controlled diagnostics."""
import re
from urllib.parse import urlsplit


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    port = parts.port
    default = 443 if parts.scheme == 'https' else 80
    return f'{parts.scheme}://{parts.hostname}' + (f':{port}' if port and port != default else '')


def validate_capture(spec: object) -> None:
    if not isinstance(spec, dict) or set(spec) - {'method', 'path', 'origin', 'save_as', 'timeout_ms'} or not {'method', 'path', 'origin'} <= set(spec):
        raise ValueError('Capture requires method/path/origin and optional save_as/timeout_ms only')
    if not isinstance(spec['method'], str) or spec['method'] not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}:
        raise ValueError('Capture method must be an explicit HTTP method')
    path = spec['path']
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or any(c.isspace() or ord(c) < 32 for c in path) or any(c in path for c in ('?', '#', '\\')):
        raise ValueError('Capture requires an exact application path without query/fragment')
    try:
        url = spec['origin']
        parts = urlsplit(url)
        if (not isinstance(url, str) or parts.scheme not in {'http', 'https'} or not parts.hostname
                or parts.username or parts.password or parts.path or parts.query or parts.fragment
                or origin_of(url) != url or any(c.isspace() for c in url)):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Capture origin must be a normalized HTTP origin') from None
    if not isinstance(spec.get('save_as', 'res'), str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', spec.get('save_as', 'res')):
        raise ValueError('Capture response name must be an identifier')
    timeout = spec.get('timeout_ms', 10000)
    if type(timeout) is not int or not 100 <= timeout <= 30000:
        raise ValueError('Capture timeout must be an integer from 100 to 30000 ms')
