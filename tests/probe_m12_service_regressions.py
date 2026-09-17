#!/usr/bin/env python3
"""Frozen M12 shutdown/configuration regressions. Run ONLY in Docker uid 1002.

    python3 -m unittest -v tests.probe_m12_service_regressions

Real HTTP, service entrypoint, product ladder, semaphore and DockerLauncher;
only Docker subprocess IO is simulated. Child processes and SIGTERM stay in
this test container. No Docker socket, external targets or private fix API.
"""
import concurrent.futures
import io
from http.client import RemoteDisconnected
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TOKEN = 'regression-test-token'
INSTANCE = 'regression-own'
OWNER = 'ai-browser-gateway'
# Watchdog for this fixture: a 20s provider deadline plus instant fake Docker IO.
# This is not a new production shutdown timeout.
BOUND = 30


def container_only():
    if not Path('/.dockerenv').exists() or os.getuid() != 1002:
        raise RuntimeError('probe requires Docker user 1002:1002')


def configuration(root, proxy='http://u:p@proxy.invalid:8126'):
    for name, text in [('token', TOKEN + '\n'), ('profiles',
                       '[profile.alpha]\nurl = ' + json.dumps(proxy) + '\n')]:
        p = root / name
        p.write_text(text)
        p.chmod(0o600)
    return dict(ABG_TOKEN_FILE=str(root / 'token'),
                ABG_PROFILES_FILE=str(root / 'profiles'), ABG_INSTANCE=INSTANCE,
                ABG_BIND='127.0.0.1', ABG_PORT='0')


def http(address, path='/normal', browser=True):
    from http.client import HTTPConnection
    conn = HTTPConnection(*address, timeout=BOUND + 2)
    try:
        conn.request('POST', '/v1/fetch', json.dumps(dict(
            url='http://target.invalid' + path, budget_ms=20000,
            allow_browser=browser)), {'Authorization': 'Bearer ' + TOKEN,
                                     'Content-Type': 'application/json'})
        res = conn.getresponse()
        return res.status, json.loads(res.read())
    finally:
        conn.close()


def child(scenario):
    container_only()
    sys.path.insert(0, str(ROOT))
    from gateway import service
    emit_lock, state_lock = threading.Lock(), threading.Lock()
    gate, quit_event = threading.Event(), threading.Event()
    containers, launches, removed = {}, [], []
    shutting = threading.Event()
    server_box = []
    serial = 0

    def emit(kind, **data):
        with emit_lock:
            print(json.dumps(dict(event=kind, **data)), flush=True)

    def labels(instance=INSTANCE, owner=OWNER, role='provider'):
        return {'abg.owner': owner, 'abg.instance': instance, 'abg.role': role}

    controls = {'other-owner': labels(owner='foreign'),
                'other-instance': labels(instance='foreign'),
                'other-role': labels(role='monitor'), 'unlabeled': {},
                'foreign-labeled': {'foreign.run': 'keep'}}

    real_run = subprocess.run

    def docker_run(argv, **kw):
        nonlocal serial
        if argv[0] != 'docker':
            return real_run(argv, **kw)
        timeout = kw.get('timeout')
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 40:
            raise AssertionError('Docker call lacks a finite bounded timeout')
        if kw.get('shell') or kw.get('stdin') != subprocess.DEVNULL:
            raise AssertionError('unsafe subprocess forwarding')
        if argv[1] == 'ps':
            filters = [argv[i + 1][6:] for i, a in enumerate(argv)
                       if a == '--filter' and argv[i + 1].startswith('label=')]
            with state_lock:
                found = [cid for cid, lab in containers.items()
                         if all(lab.get(k) == v for k, v in
                                (f.split('=', 1) for f in filters))]
            emit('sweep', filters=filters, found=found)
            return subprocess.CompletedProcess(argv, 0, '\n'.join(found), '')
        if argv[1] == 'rm':
            with state_lock:
                for cid in argv[2:]:
                    if not cid.startswith('-'):
                        containers.pop(cid, None)
                        removed.append(cid)
            emit('remove', ids=argv[2:])
            return subprocess.CompletedProcess(argv, 0, '', '')
        if argv[1] != 'run':
            raise AssertionError('unexpected Docker operation')
        url = next(a for a in argv if a.startswith('http://target.invalid'))
        provider = next(a for a in argv if a.startswith('abg-') and ':' in a)
        lab = dict(argv[i + 1].split('=', 1) for i, a in enumerate(argv) if a == '--label')
        if scenario == 'admitted' and url.endswith('/admitted'):
            emit('admitted')  # Real DockerLauncher entered; daemon has not created yet.
            if not gate.wait(10):
                raise AssertionError('admission barrier not released')
        with state_lock:
            serial += 1
            cid = 'fake-' + str(serial)
            containers[cid] = lab
            launch = dict(cid=cid, argv=argv, timeout=timeout,
                          proxy=(kw.get('env') or {}).get('ABG_PROXY'),
                          after_signal=shutting.is_set(), url=url)
            launches.append(launch)
        if '--cidfile' in argv:
            Path(argv[argv.index('--cidfile') + 1]).write_text(cid)
        emit('launch', **launch)
        if url.endswith('/admitted'):
            emit('created_admitted', cid=cid)
        if url.endswith('/admitted'):
            # Emulate a running docker run, which only completes when removed.
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with state_lock:
                    if cid not in containers:
                        break
                if quit_event.wait(.01):
                    break
        with state_lock:
            containers.pop(cid, None)  # docker run --rm
        empty = url.endswith('/browser') and 'curl' in provider
        status = 403 if url.endswith('/egress') and 'ABG_PROXY' not in (kw.get('env') or {}) else 200
        body = '' if empty else 'probe-page'
        payload = dict(ok=True, sentinel=False, status=status, final_url=url,
                       title='', html='<p>' + body + '</p>', text=body, err=None,
                       elapsed_ms=1, startup_ms=0, cpu_ms=0, peak_rss_mb=0,
                       bytes=len(body), redirects=0, challenge='none')
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), '')

    real_make, real_signal = service.make_service, signal.signal

    def make(*a, **kw):
        server = real_make(*a, **kw)
        server_box.append(server)
        if scenario == 'pending':
            sem = server.slots
            sem.acquire()

            class ObservedSemaphore:
                def acquire(self, *a, **kw):
                    emit('browser_wait')
                    return sem.acquire(*a, **kw)

                def release(self):
                    return sem.release()
            server.slots = ObservedSemaphore()
        emit('ready', address=server.server_address)
        return server

    def install(sig, handler):
        def observed(*a):
            shutting.set()
            emit('signal', number=a[0])
            return handler(*a)
        return real_signal(sig, observed)

    def control():
        for line in sys.stdin:
            command = line.strip()
            if command == 'seed':
                with state_lock:
                    containers.update(controls)
                    containers['existing-own'] = labels()
                emit('seeded')
            elif command == 'release':
                gate.set()
                if scenario == 'pending':
                    server_box[0].slots.release()
                emit('released')
            elif command == 'snapshot':
                with state_lock:
                    emit('snapshot', containers=dict(containers),
                         launches=list(launches), removed=list(removed))
            elif command == 'exit':
                quit_event.set()
                return

    with tempfile.TemporaryDirectory() as tmp:
        env = configuration(Path(tmp))
        with patch.dict(os.environ, env, clear=True), \
                patch.object(service, 'make_service', make), \
                patch.object(subprocess, 'run', docker_run), \
                patch.object(signal, 'signal', install):
            threading.Thread(target=control, daemon=True).start()
            rc = service.main()
            emit('stopped', rc=rc)
            quit_event.wait(BOUND * 3)  # Observe daemon handlers even after main returns.


class Process:
    def __init__(self, scenario):
        self.events, self.history = queue.Queue(), []
        self.proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                      '--child', scenario], cwd=ROOT,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
        def read():
            for line in self.proc.stdout:
                try:
                    item = json.loads(line)
                except ValueError:
                    item = {'event': 'invalid-output', 'line': line}
                self.events.put(item)
        threading.Thread(target=read, daemon=True).start()

    def wait(self, kind, timeout=BOUND):
        deadline = time.monotonic() + timeout
        while True:
            for item in self.history:
                if item['event'] == kind:
                    return item
            try:
                self.history.append(self.events.get(timeout=max(0, deadline - time.monotonic())))
            except queue.Empty:
                raise AssertionError('missing event ' + kind + ': ' + repr(self.history))

    def send(self, value):
        self.proc.stdin.write(value + '\n')
        self.proc.stdin.flush()

    def close(self):
        self.send('exit')
        try:
            out, err = self.proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()  # This exact owned child, inside Docker only.
            out, err = self.proc.communicate(timeout=3)
        print('CHILD', json.dumps(self.history), err, flush=True)


class ShutdownRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        container_only()

    def scenario(self, mode):
        child_proc = Process(mode)
        self.addCleanup(child_proc.close)
        address = child_proc.wait('ready')['address']
        child_proc.wait('sweep')  # Startup sweep finished before adding controls.
        paths = ('/normal', '/egress', '/browser') if mode == 'admitted' else ('/normal', '/egress')
        for path in paths:
            status, value = http(address, path, browser=(path == '/browser'))
            self.assertEqual(status, 200)
            self.assertTrue(value['ok'], value)
        child_proc.send('seed')
        child_proc.wait('seeded')
        pool = concurrent.futures.ThreadPoolExecutor(1)
        self.addCleanup(lambda: pool.shutdown(wait=False))
        future = pool.submit(http, address, '/browser' if mode == 'pending' else '/admitted')
        child_proc.wait('browser_wait' if mode == 'pending' else 'admitted')
        start = time.monotonic()
        os.kill(child_proc.proc.pid, signal.SIGTERM)
        child_proc.wait('signal')
        # Hold the activated barrier past the BASE's two sweeps and 0.2s pause.
        # A correct implementation may either stop promptly or drain admission.
        try:
            child_proc.wait('stopped', timeout=1.5)
        except AssertionError:
            pass
        child_proc.send('release')
        child_proc.wait('released')
        stopped = child_proc.wait('stopped', timeout=BOUND)
        self.assertEqual(stopped['rc'], 0)
        self.assertLess(time.monotonic() - start, BOUND, 'shutdown unbounded')
        if mode == 'pending':
            try:
                future.result(timeout=BOUND)  # Prove waiting handler resumed or rejected.
            except (RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                pass  # Explicitly closing the pending connection is also rejection.
            except Exception as exc:
                self.fail('waiting handler did not complete: ' + type(exc).__name__)
        else:
            child_proc.wait('created_admitted')
        child_proc.send('snapshot')
        snap = child_proc.wait('snapshot')
        owned = [cid for cid, lab in snap['containers'].items()
                 if lab.get('abg.owner') == OWNER and lab.get('abg.instance') == INSTANCE
                 and lab.get('abg.role') == 'provider']
        self.assertFalse(owned, 'provider orphan after shutdown: ' + repr(owned))
        for cid in ('other-owner', 'other-instance', 'other-role', 'unlabeled', 'foreign-labeled'):
            self.assertIn(cid, snap['containers'], 'cleanup exceeded installation scope: ' + cid)
        self.assertIn('existing-own', snap['removed'])
        launches = snap['launches']
        self.assertGreaterEqual(len(launches), 3, 'normal/egress transport not activated')
        ids = {}
        for launch in launches:
            argv = launch['argv']
            labels = dict(argv[i + 1].split('=', 1) for i, v in enumerate(argv) if v == '--label')
            self.assertEqual({k: labels.get(k) for k in ('abg.owner', 'abg.instance', 'abg.role')},
                             {'abg.owner': OWNER, 'abg.instance': INSTANCE, 'abg.role': 'provider'})
            self.assertTrue(labels.get('abg.request'))
            ids.setdefault(launch['url'], set()).add(labels['abg.request'])
            self.assertEqual(argv[argv.index('--user') + 1], '1002:1002')
            self.assertTrue(any('/opt/abg/probe.py,readonly' in a for a in argv))
            self.assertLessEqual(launch['timeout'], 20)
            self.assertEqual(launch['timeout'], int(argv[argv.index('--budget-ms') + 1]) / 1000)
            if any(a.startswith('abg-patchright:') for a in argv):
                self.assertIn('--shm-size=1g', argv)
            self.assertNotIn(TOKEN, ' '.join(argv))
            self.assertNotIn('u:p@', ' '.join(argv))
            if launch['proxy']:
                self.assertEqual(launch['proxy'], 'http://u:p@proxy.invalid:8126')
                self.assertEqual(argv[argv.index('--env') + 1], 'ABG_PROXY')
            if mode == 'pending':
                self.assertFalse(launch['after_signal'], 'waiting handler launched after SIGTERM')
        self.assertTrue(all(len(values) == 1 for values in ids.values()))
        self.assertEqual(len(set.union(*ids.values())), len(ids))
        self.assertTrue(any(item['proxy'] for item in launches), 'egress env not exercised')

    def test_waiting_browser_cannot_launch_after_sigterm(self):
        self.scenario('pending')

    def test_admitted_launch_cannot_leave_late_orphan(self):
        self.scenario('admitted')

    def test_default_m11_profiles_stay_ordered_and_isolated(self):
        from gateway.httpapi import make_server
        from tests.m11_helpers import reply, serving, request
        seen = []
        profiles = {'a': 'http://a.invalid:9', 'b': 'http://b.invalid:9'}
        def factory(url, **kw):
            seen.append(tuple(kw['profiles']))
            kw['profiles'].clear()
            return lambda step, budget: reply()
        server = make_server(('127.0.0.1', 0), token=TOKEN,
                             profiles=profiles, fetcher_factory=factory)
        with serving(server) as address:
            for _ in range(3):
                status, body = request(address, token=TOKEN)
                self.assertEqual(status, 200)
                self.assertTrue(body['ok'])
        self.assertEqual(seen, [('a', 'b')] * 3)
        self.assertEqual(tuple(profiles), ('a', 'b'))

    def test_unicode_proxy_rejected_before_bind(self):
        from gateway.service import make_service
        from http.server import HTTPServer
        original = HTTPServer.server_bind
        for char in ('\u00a0', '\u0085'):
            with self.subTest(codepoint=hex(ord(char))), tempfile.TemporaryDirectory() as tmp:
                env = configuration(Path(tmp), 'http://proxy.invalid:8126/a' + char + 'b')
                calls = []
                def bind(server):
                    calls.append(True)
                    return original(server)
                server, rejected = None, False
                try:
                    with patch.object(HTTPServer, 'server_bind', bind):
                        try:
                            server = make_service(env)
                        except Exception:
                            rejected = True
                finally:
                    if server is not None:
                        server.server_close()
                self.assertTrue(rejected, 'Unicode whitespace/control proxy accepted')
                self.assertFalse(calls, 'invalid proxy reached bind')

    def test_prepare_cli_rejects_manifest_symlink(self):
        # Git boundary fixture is allowed: exercise real prepare CLI/filesystem.
        git_program = """#!/usr/local/bin/python3
import os, pathlib, sys
args = sys.argv[1:]
if args[:1] == ['-C']:
    args = args[2:]
sha = os.environ['PROBE_COMMIT']
if args == ['cat-file', '-t', sha]:
    print('commit')
elif args == ['rev-parse', '--verify', sha + '^{commit}']:
    print(sha)
elif args == ['archive', '--format=tar', sha]:
    sys.stdout.buffer.write(pathlib.Path(os.environ['PROBE_ARCHIVE']).read_bytes())
else:
    sys.exit(2)
"""
        with tempfile.TemporaryDirectory() as tmp:
            base, sha = Path(tmp), 'a' * 40
            repo, root, archive, binpath = (base / n for n in ('repo', 'delivery', 'archive.tar', 'bin'))
            repo.mkdir()
            binpath.mkdir()
            with tarfile.open(archive, 'w') as tar:
                for name, data, mode in [('data.txt', b'committed\n', 0o644),
                                         ('bin/tool', b'#!/bin/sh\n', 0o755)]:
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(data), mode
                    tar.addfile(info, io.BytesIO(data))
            git = binpath / 'git'
            git.write_text(git_program)
            git.chmod(0o700)
            env = dict(os.environ, PATH=str(binpath) + ':' + os.environ.get('PATH', ''),
                       PROBE_COMMIT=sha, PROBE_ARCHIVE=str(archive))
            cmd = [sys.executable, str(ROOT / 'scripts/abg-release'), 'prepare',
                   '--repo', str(repo), '--sha', sha, '--root', str(root)]
            def prepare():
                return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=8)
            self.assertEqual(prepare().returncode, 0, 'regular prepare failed')
            manifest = root / 'manifests' / (sha + '.sha256')
            before = manifest.read_bytes()
            inode = manifest.stat().st_ino
            self.assertEqual(prepare().returncode, 0, 'regular repeat failed')
            self.assertEqual((manifest.read_bytes(), manifest.stat().st_ino), (before, inode))
            victim = base / 'external-target'
            victim.write_bytes(before)
            metadata = victim.stat()
            manifest.unlink()
            manifest.symlink_to(victim)
            result = prepare()
            self.assertEqual(victim.read_bytes(), before)
            self.assertEqual(victim.stat().st_mtime_ns, metadata.st_mtime_ns)
            self.assertTrue(manifest.is_symlink())
            self.assertNotEqual(result.returncode, 0, 'prepare accepted manifest symlink')
            self.assertEqual(result.stderr.strip(), '{"error":"invalid_configuration"}')


if __name__ == '__main__':
    container_only()
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        unittest.main(verbosity=2)
