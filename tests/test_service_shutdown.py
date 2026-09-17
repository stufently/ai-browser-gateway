"""Stop admission synchronously; drain launches beyond the daemon-create gap."""
from concurrent.futures import ThreadPoolExecutor
import signal
import subprocess
from threading import Event, Thread
import unittest
from unittest.mock import patch
from gateway import service
from tests import test_service_config as config
from tests.m11_helpers import request, serving, reply


class ShutdownTests(unittest.TestCase):
    setUp = config.ConfigurationTests.setUp

    def test_main_signal_closes_admission_and_finishes_cleanup(self):
        ready = Event()
        handlers, results, sweeps = {}, [], []
        server = service.make_service(self.env, fetcher_factory=lambda url, **kw:
                                      lambda step, budget: reply())
        def install(number, callback):
            handlers[number] = callback
            if number == signal.SIGINT:
                ready.set()
        def sweep(instance, timeout=20):
            sweeps.append((instance, server.launches.stopped))
        with patch.object(service, 'make_service', return_value=server), \
                patch.object(service.signal, 'signal', install), \
                patch.object(service, 'sweep_providers', sweep):
            thread = Thread(target=lambda: results.append(service.main()), daemon=True)
            thread.start()
            self.assertTrue(ready.wait(2))
            status, body = request(server.server_address, token='private-test-token')
            self.assertEqual(status, 200)
            self.assertTrue(body['ok'])
            handlers[signal.SIGTERM]()
            handlers[signal.SIGTERM]()
            thread.join(3)
        self.assertEqual(results, [0], 'main did not finish shutdown')
        self.assertEqual((sweeps[0], sweeps[-1]), (('test-one', False), ('test-one', True)))
        with self.assertRaisesRegex(RuntimeError, 'service_stopping'):
            server.factory('http://example.invalid')

    def test_waiting_browser_cannot_fetch_after_stop(self):
        waiting, observed = Event(), []
        def factory(url, **kw):
            def fetch(step, budget):
                observed.append(step.provider)
                return reply(step.provider, text='', html='')
            return fetch
        server = service.make_service(self.env, fetcher_factory=factory)
        sem = server.slots
        sem.acquire()
        class Semaphore:
            def acquire(self, **kw):
                waiting.set()
                return sem.acquire(**kw)
            def release(self):
                sem.release()
        server.slots = Semaphore()
        with serving(server) as address, ThreadPoolExecutor(1) as pool:
            future = pool.submit(request, address, {'url': 'https://example.invalid/',
                'budget_ms': 3000}, token='private-test-token')
            self.assertTrue(waiting.wait(2), 'browser queue not reached')
            server.launches.stop()
            sem.release()
            future.result(timeout=3)
        self.assertEqual(observed, ['curl'], 'queued browser fetched after stop')

    def test_admitted_launch_is_drained_before_final_sweep(self):
        entered, release, removed, done = (Event() for _ in range(4))
        live = set()
        class Inner:
            def run(self, argv, timeout, *, env=None):
                entered.set()
                if not release.wait(2):
                    raise AssertionError('barrier not released')
                live.add('owned')
                if not removed.wait(timeout):
                    raise subprocess.TimeoutExpired(argv, timeout)
                return 0, '', ''
        server = service.make_service(self.env)
        self.addCleanup(server.server_close)
        launcher = service.LabeledLauncher('test-one', 'req', Inner(), gate=server.launches)
        def sweep(instance, timeout=20):
            self.assertEqual(instance, 'test-one')
            self.assertGreater(timeout, 0)
            if live:
                live.clear()
                removed.set()
        def finish():
            server.launches.drain('test-one')
            done.set()
        with ThreadPoolExecutor(2) as pool, patch.object(service, 'sweep_providers', sweep):
            launch = pool.submit(launcher.run, ['docker', 'run', '--rm', 'test'], 2)
            self.assertTrue(entered.wait(1))
            server.launches.stop()
            cleanup = pool.submit(finish)
            self.assertFalse(done.wait(.05), 'cleanup ended before delayed creation')
            release.set()
            self.assertEqual(launch.result(timeout=3), (0, '', ''))
            cleanup.result(timeout=3)
        self.assertFalse(live)
        with self.assertRaisesRegex(RuntimeError, 'service_stopping'):
            launcher.run(['docker', 'run', 'test'], 2)

    def test_cleanup_scope_timeout_and_errors(self):
        with patch.object(service.subprocess, 'run', return_value=
                subprocess.CompletedProcess([], 0, 'own-a\nown-b\n', '')) as run:
            service.sweep_providers('test-one', timeout=.75)
        self.assertEqual(run.call_args_list[0].args[0], ['docker', 'ps', '-aq',
            '--filter', 'label=abg.owner=ai-browser-gateway',
            '--filter', 'label=abg.instance=test-one', '--filter', 'label=abg.role=provider'])
        self.assertEqual(run.call_args_list[1].args[0], ['docker', 'rm', '--force', 'own-a', 'own-b'])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], .75)
            self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)
            self.assertNotIn('shell', call.kwargs)
        for error in (OSError(), subprocess.TimeoutExpired('docker', .75)):
            with patch.object(service.subprocess, 'run', side_effect=error):
                service.sweep_providers('test-one', timeout=.75)
