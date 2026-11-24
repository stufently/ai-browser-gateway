"""Local image inventory for the production route.

The 30s healthcheck and 60s monitor see results at most 15s old. The cache
limits unauthenticated health requests to one Docker call per 15s and lets
rebuilt images restore health within 15s. The 3s Docker timeout fits inside
the healthcheck's 4s and the monitor's 5s request timeouts.
"""
from copy import deepcopy
import subprocess
from threading import Lock
import time

from bench.providers import registry
from gateway import product


def route_images():
    request = product.ProductRequest('https://example.com/', max_age_hours=1.0)
    return tuple(sorted({registry.by_name(step.provider).image for step in product.plan_product(request)}))


class ImageCheck:
    def __init__(self, images=None, *, run=None, clock=None, ttl=15.0, timeout=3.0):
        self.images = route_images() if images is None else tuple(sorted(images))
        self.run = run
        self.clock = clock
        self.ttl = ttl
        self.timeout = timeout
        self._lock = Lock()
        self._cached = None
        self._checked_at = 0.0

    def _probe(self):
        argv = ['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}']
        for image in self.images:
            argv.extend(('--filter', 'reference=' + image))
        run = subprocess.run if self.run is None else self.run
        result = run(argv, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
        if result.returncode:
            return {'ok': False, 'error': 'provider_images_unknown'}
        present = {line.strip() for line in result.stdout.splitlines()}
        missing = [image for image in self.images if image not in present]
        if missing:
            return {'ok': False, 'error': 'provider_images_missing', 'missing': missing}
        return {'ok': True}

    def status(self):
        clock = time.monotonic if self.clock is None else self.clock
        with self._lock:
            try:
                if self._cached is None or clock() - self._checked_at >= self.ttl:
                    try:
                        result = self._probe()
                    except Exception:
                        result = {'ok': False, 'error': 'provider_images_unknown'}
                    self._checked_at = clock()
                    self._cached = result
                return deepcopy(self._cached)
            except Exception:
                return {'ok': False, 'error': 'provider_images_unknown'}
