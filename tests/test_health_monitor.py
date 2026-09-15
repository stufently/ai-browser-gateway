import unittest
from gateway.health_monitor import _url


class HealthMonitorTests(unittest.TestCase):
    def test_url_rules_for_compose_and_ping(self):
        health = 'http://api:8765/health'
        ping = 'https://example.invalid/ping-id'
        self.assertTrue(_url(health, ping=False, allow_local=False))
        self.assertTrue(_url(ping, ping=True, allow_local=False))
        self.assertFalse(_url('http://api:8765/health', ping=True, allow_local=False))
        self.assertFalse(_url('http://127.0.0.1:9/health', ping=False, allow_local=False))
        self.assertTrue(_url('http://127.0.0.1:9/x', ping=True, allow_local=True))
        self.assertFalse(_url('https://u:p@h.invalid/x', ping=True, allow_local=False))
        self.assertFalse(_url('https://h.invalid/x?q=1', ping=True, allow_local=False))
        self.assertFalse(_url('https://h.invalid', ping=True, allow_local=False))
