"""Single-process HTTP API. Deployment and service configuration belong to M12."""
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import sys
from threading import BoundedSemaphore, Lock
from gateway.api_http import Handler
from gateway.api_limit import limit_fetcher
from gateway.fetch import ProductFetcher


def make_server(address, *, token, browser_limit=1, profiles=None,
                entrances=None, fetcher_factory=None, rotate_profiles=False):
    if (not isinstance(token, str) or not token
            or any(not 33 <= ord(char) <= 126 for char in token)
            or type(browser_limit) is not int or browser_limit <= 0
            or not isinstance(address, (tuple, list)) or len(address) != 2
            or not isinstance(address[0], str) or not address[0]
            or type(address[1]) is not int or not 0 <= address[1] <= 65535):
        raise ValueError('invalid configuration')
    try:
        profiles, entrances = dict(profiles or {}), dict(entrances or {})
        if any(not isinstance(key, str) or not key or key == 'direct' for key in profiles):
            raise ValueError
        if fetcher_factory is not None and not callable(fetcher_factory):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('invalid configuration') from None
    server = ThreadingHTTPServer(tuple(address), Handler)
    server.token = token.encode('ascii')
    server.profiles, server.entrances = profiles, entrances
    server.factory = ProductFetcher if fetcher_factory is None else fetcher_factory
    server.slots = BoundedSemaphore(browser_limit)
    server.rotate_profiles = bool(rotate_profiles)
    server.rotate_lock = Lock()
    server.rotate_index = 0
    return server


def main():
    try:
        token = os.environ.get('ABG_TOKEN')
        if token is None:
            token = Path(os.environ['ABG_TOKEN_FILE']).expanduser().read_text(encoding='ascii').rstrip('\r\n')
        server = make_server((os.environ.get('ABG_BIND', '0.0.0.0'), int(os.environ.get('ABG_PORT', '8765'))),
                             token=token, browser_limit=int(os.environ.get('ABG_BROWSER_LIMIT', '1')))
    except Exception:
        print('{"error":"invalid_configuration"}', file=sys.stderr)
        return 1
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
