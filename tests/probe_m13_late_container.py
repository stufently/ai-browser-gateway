#!/usr/bin/env python3
"""M13: a Docker client timeout must not leave its daemon's late container.

Run in Docker 1002:1002, --network none, without a Docker socket:
    python3 -m unittest -v tests.probe_m13_late_container

Only subprocess.run is replaced. Real launcher, tempfiles, clocks and threads.
The fake understands Docker names, labels, ps/inspect and forced removal, not
private launcher helpers. Delays model daemon work; Events establish ordering.
The 36s fixture watchdog allows the existing 30s cleanup budget plus headroom;
it is not a production SLA. This finite probe cannot prove absence of a create
at an arbitrarily distant time or correctness against every Docker failure.
"""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BOUND = 36
TIMEOUT = .04
ENV = {'PATH': '/usr/bin', 'ABG_PROXY': 'http://user:pass@proxy.invalid:8126'}
SHARED = {'abg.owner': 'ai-browser-gateway', 'abg.instance': 'm13-probe',
          'abg.role': 'provider', 'abg.request': 'same-request'}


def container_only():
    if not Path('/.dockerenv').exists() or (os.getuid(), os.getgid()) != (1002, 1002):
        raise RuntimeError('probe requires Docker user 1002:1002')


def options(argv, *keys):
    values = []
    for i, token in enumerate(argv):
        if token in keys:
            values.append(argv[i + 1])
        else:
            for key in keys:
                if token.startswith(key + '='):
                    values.append(token[len(key) + 1:])
    return values


def metadata(argv, fallback):
    names = options(argv, '--name')
    return dict(name=names[-1] if names else fallback,
                labels=dict(item.partition('=')[::2]
                            for item in options(argv, '--label', '-l')))


def command(provider='curl'):
    from bench.providers.registry import build_argv, by_name
    return build_argv(by_name(provider), url='http://target.invalid/page',
                      sentinel='marker', network='none', proxy_env='ABG_PROXY',
                      probe_bind=ROOT / 'bench/providers/docker/probe.py',
                      include_content=True, budget_ms=40) + ['--mode', 'cold']


class Daemon:
    """Stateful subprocess boundary; all containers here are Python records."""
    def __init__(self, mode, delay):
        self.mode, self.delay = mode, delay
        self.lock = threading.RLock()
        self.sibling_ready = threading.Event()
        self.sibling_release = threading.Event()
        self.unwound = threading.Event()
        self.created = threading.Event()
        self.stop = threading.Event()
        self.returned = threading.Event()
        self.containers, self.launches, self.removed = {}, [], []
        self.events, self.calls = [], []
        self.count = 0
        self.expired = None
        self.cidfile = None
        self.target = None
        self.return_snapshot = None
        self.start = time.monotonic()

    def event(self, kind, **data):
        self.events.append(dict(event=kind, at=round(time.monotonic()-self.start, 6), **data))

    def create(self):
        with self.lock:
            self.containers['target-id'] = self.target
            self.event('daemon_created', after_return=self.returned.is_set())
        self.created.set()

    def late_create(self):
        # A cleanup subprocess, or the caller catching the exception, proves
        # fake docker run has ALREADY raised. No scheduling guess around raise.
        if not self.unwound.wait(BOUND):
            return
        if not self.stop.wait(self.delay):
            self.create()

    def result(self, argv, kw, rc=0, out='', err=''):
        if not (kw.get('text') or kw.get('universal_newlines') or kw.get('encoding')):
            out, err = out.encode(), err.encode()
        return subprocess.CompletedProcess(argv, rc, out, err)

    def run(self, argv, **kw):
        if argv[0] != 'docker':
            raise AssertionError('unexpected external command: ' + repr(argv))
        timeout = kw.get('timeout')
        assert isinstance(timeout, (int, float)) and math.isfinite(timeout) and 0 < timeout <= BOUND + 4, \
            'Docker subprocess must have a finite timeout within the fixture watchdog'
        assert kw.get('stdin') == subprocess.DEVNULL and not kw.get('shell'), \
            'Docker subprocess changed stdin/shell safety'
        with self.lock:
            self.count += 1
            if len(self.calls) < 12:
                self.calls.append(list(argv))
        operation = argv[1:]
        if operation[:1] == ['container']:
            operation = operation[1:]
        verb, args = operation[0], operation[1:]
        if verb == 'run':
            with self.lock:
                number = len(self.launches)
                self.launches.append((list(argv), dict(kw)))
                meta = metadata(argv, 'auto-' + str(number))
                if number == 0:
                    self.containers['sibling-id'] = meta
                    paths = options(argv, '--cidfile')
                    if paths:
                        Path(paths[-1]).write_text('sibling-id\n')
                    self.event('sibling_created')
                else:
                    assert number == 1, 'unexpected provider relaunch'
                    self.target = meta
                    paths = options(argv, '--cidfile')
                    self.cidfile = Path(paths[-1]) if paths else None
                    if self.mode == 'empty' and self.cidfile:
                        self.cidfile.write_text('')
                    # Near-matching identities catch substring name matches,
                    # label-existence filters and installation/request sweeps.
                    foreign = {k: (v if k in SHARED else v + '-foreign')
                               for k, v in meta['labels'].items()}
                    self.containers['foreign-id'] = dict(
                        name=meta['name'] + '-foreign', labels=foreign)
                    self.containers['unlabeled-id'] = dict(name='unrelated', labels={})
                    if self.mode == 'ready':
                        self.create()
                        if self.cidfile:
                            self.cidfile.write_text('target-id\n')
            if number == 0:
                self.sibling_ready.set()
                assert self.sibling_release.wait(BOUND + 5), 'sibling barrier not released'
                with self.lock:
                    self.containers.pop('sibling-id', None)  # normal --rm exit
                    self.event('sibling_completed')
                return self.result(argv, kw, out='normal sibling', err='sibling stderr')
            # Deliberately no cidfile write for a create after the client died.
            self.stop.wait(timeout)
            self.expired = subprocess.TimeoutExpired(argv, timeout,
                                                      output=b'partial', stderr=b'partial error')
            with self.lock:
                self.event('client_timeout', cidfile=(self.cidfile.read_text()
                           if self.cidfile and self.cidfile.exists() else None))
            raise self.expired
        self.unwound.set()
        with self.lock:
            if verb in ('ps', 'ls'):
                filters = options(args, '--filter', '-f')
                groups = {}
                for item in filters:
                    key, _, value = item.partition('=')
                    groups.setdefault(key, []).append(value)
                def matches(cid, meta):
                    for key, values in groups.items():
                        if key == 'name':
                            yes = any(re.search(v, '/' + meta['name']) for v in values)
                        elif key == 'label':
                            yes = any((meta['labels'].get(v.partition('=')[0]) == v.partition('=')[2]
                                       if '=' in v else v in meta['labels']) for v in values)
                        elif key == 'id':
                            yes = any(cid.startswith(v) for v in values)
                        else:
                            raise AssertionError('unsupported Docker filter: ' + key)
                        if not yes:
                            return False
                    return True
                found = [cid for cid, meta in self.containers.items() if matches(cid, meta)]
                if self.count <= 12 or found:
                    self.event('list', filters=filters, found=found)
                return self.result(argv, kw, out='\n'.join(found) + ('\n' if found else ''))
            if verb in ('rm', 'inspect'):
                identifiers = [a for a in args if not a.startswith('-')]
                found = [cid for cid, meta in self.containers.items()
                         if cid in identifiers or meta['name'] in identifiers]
                if verb == 'rm':
                    assert '--force' in args or '-f' in args, 'running container requires forced rm'
                    for cid in found:
                        self.containers.pop(cid)
                        self.removed.append(cid)
                    self.event('remove', requested=identifiers, removed=found)
                    return self.result(argv, kw, rc=0 if len(found) == len(identifiers) else 1,
                                       out='\n'.join(found), err='' if found else 'No such container')
                objects = [dict(Id=cid, Name='/' + self.containers[cid]['name'],
                                Config={'Labels': self.containers[cid]['labels']},
                                State={'Running': True}) for cid in found]
                formats = options(args, '--format', '-f')
                out = ('\n'.join(found) if formats else json.dumps(objects))
                return self.result(argv, kw, rc=0 if found else 1, out=out,
                                   err='' if found else 'No such container')
        raise AssertionError('unsupported Docker operation: ' + repr(argv))


def scenario(mode, delay):
    container_only()
    from bench.runner.execute import DockerLauncher
    from gateway.service import LabeledLauncher
    case = unittest.TestCase()
    fake = Daemon(mode, delay)
    argv = command()
    original = list(argv)
    launcher = LabeledLauncher('m13-probe', 'same-request', inner=DockerLauncher())
    answers, sibling = [], []

    def call():
        try:
            answers.append(launcher.run(argv, TIMEOUT, env=dict(ENV)))
        except BaseException as exc:
            answers.append(exc)
        finally:
            with fake.lock:
                fake.return_snapshot = list(fake.containers)
                fake.event('launcher_returned', live=fake.return_snapshot)
                fake.returned.set()
            fake.unwound.set()

    def normal():
        try:
            sibling.append(launcher.run(argv, BOUND + 4, env=dict(ENV)))
        except BaseException as exc:
            sibling.append(exc)

    # Same launcher object, same request labels, same provider argv: the
    # identity must be per invocation, not per instance/request/provider.
    worker = threading.Thread(target=call, daemon=True)
    other = threading.Thread(target=normal, daemon=True)
    daemon = threading.Thread(target=fake.late_create, daemon=True)
    with patch.object(subprocess, 'run', fake.run):
        try:
            other.start()
            case.assertTrue(fake.sibling_ready.wait(2), 'normal sibling launch not reached: ' + repr(sibling))
            if mode in ('missing', 'empty'):
                daemon.start()
            worker.start()
            completed = fake.returned.wait(BOUND)
            if mode in ('missing', 'empty'):
                case.assertTrue(fake.created.wait(2), 'late daemon create not reached')
            with fake.lock:
                evidence = dict(mode=mode, delay=delay, completed=completed,
                                events=fake.events, calls=fake.calls, call_count=fake.count,
                                live=list(fake.containers), removed=fake.removed,
                                returned_live=fake.return_snapshot)
                print('OBSERVED ' + json.dumps(evidence), flush=True)
            case.assertTrue(completed, 'cleanup exceeded fixture watchdog (possible infinite wait)')
            case.assertIsInstance(answers[0], subprocess.TimeoutExpired,
                                  'launcher must preserve TimeoutExpired: ' + repr(answers))
            case.assertIs(answers[0], fake.expired, 'original TimeoutExpired was replaced')
            case.assertEqual((answers[0].output, answers[0].stderr), (b'partial', b'partial error'))
            case.assertNotIn('target-id', fake.containers, 'late container survived launcher return')
            case.assertNotIn('target-id', fake.return_snapshot, 'container alive at launcher return')
            if mode != 'never':
                case.assertTrue(fake.created.is_set(), 'container creation branch not activated')
                case.assertIn('target-id', fake.removed, 'target was not removed through Docker')
                created = next(e for e in fake.events if e['event'] == 'daemon_created')
                case.assertFalse(created['after_return'], 'launcher returned before daemon creation')
            for cid in ('sibling-id', 'foreign-id', 'unlabeled-id'):
                case.assertIn(cid, fake.containers, 'cleanup crossed invocation scope: ' + cid)
                case.assertNotIn(cid, fake.removed, 'foreign container was touched: ' + cid)
            if mode in ('missing', 'empty'):
                first, second = (metadata(call[0], '') for call in fake.launches)
                case.assertTrue((second['name'] and second['name'] != first['name']) or any(
                    key not in SHARED and first['labels'].get(key) != value
                    for key, value in second['labels'].items()),
                    'launcher did not add a distinct per-invocation Docker identity')
            case.assertEqual(argv, original, 'caller argv mutated')
            for sent, kwargs in fake.launches:
                case.assertEqual(kwargs['env'], ENV)
                case.assertEqual(kwargs['timeout'], BOUND + 4 if sent == fake.launches[0][0] else TIMEOUT)
                case.assertEqual(sent[sent.index('abg-curl:m2'):], original[original.index('abg-curl:m2'):])
            fake.sibling_release.set()
            other.join(2)
            case.assertEqual(sibling, [(0, 'normal sibling', 'sibling stderr')])
        finally:
            fake.stop.set()
            fake.sibling_release.set()
            other.join(2)
            if daemon.ident is not None:
                daemon.join(2)
            worker.join(.1)


class LateContainerProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        container_only()

    def child(self, mode, delay=0):
        cmd = [sys.executable, str(Path(__file__).resolve()), '--child', mode, str(delay)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=BOUND + 8,
                                    stdin=subprocess.DEVNULL, cwd=ROOT)
        except subprocess.TimeoutExpired as exc:
            self.fail('fixture child watchdog expired: ' + repr(exc.output))
        print(result.stdout, end='', flush=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_late_create_without_cidfile(self):
        self.child('missing', .15)

    def test_late_create_with_empty_cidfile(self):
        self.child('empty', .65)

    def test_cidfile_already_written(self):
        self.child('ready')

    def test_daemon_never_creates_container(self):
        self.child('never')

    def test_normal_exit_and_forwarding(self):
        from bench.runner.execute import DockerLauncher
        for provider in ('curl', 'patchright'):
            for rc in (0, 7):
                for env in (None, ENV):
                    with self.subTest(provider=provider, rc=rc, env=env):
                        original = command(provider)
                        argv = list(original)
                        calls = []
                        def run(sent, **kw):
                            calls.append((list(sent), kw))
                            return subprocess.CompletedProcess(sent, rc, 'stdout-Ω', 'stderr-β')
                        with patch.object(subprocess, 'run', run):
                            got = DockerLauncher().run(argv, .125, env=env)
                        self.assertEqual(got, (rc, 'stdout-Ω', 'stderr-β'))
                        self.assertEqual(argv, original)
                        self.assertEqual(len(calls), 1, 'normal exit unexpectedly triggered cleanup')
                        sent, kw = calls[0]
                        self.assertEqual(kw['timeout'], .125)
                        self.assertEqual(kw['stdin'], subprocess.DEVNULL)
                        self.assertTrue(kw['capture_output'])
                        self.assertTrue(kw['text'])
                        self.assertEqual(kw['errors'], 'replace')
                        self.assertFalse(kw.get('shell'))
                        if env is None:
                            self.assertNotIn('env', kw)
                        else:
                            self.assertEqual(kw['env'], ENV)
                        # Extra identity/cidfile switches may appear anywhere
                        # before the image; all provider arguments stay intact.
                        image = 'abg-' + provider + ':m2'
                        self.assertEqual(sent[sent.index(image):], original[original.index(image):])
                        self.assertEqual(options(sent, '--user'), ['1002:1002'])
                        self.assertEqual(options(sent, '--network'), ['none'])
                        self.assertEqual(options(sent, '--env'), ['ABG_PROXY'])
                        self.assertEqual(options(sent, '--mount'), options(original, '--mount'))
                        self.assertIn('--rm', sent)
                        if provider == 'patchright':
                            self.assertIn('--shm-size=1g', sent)

    def test_non_run_commands_are_unchanged(self):
        from bench.runner.execute import DockerLauncher
        for argv in (['docker', 'version'], ['provider-cli', 'run', '--flag']):
            for fail in (False, True):
                with self.subTest(argv=argv, fail=fail):
                    expired = subprocess.TimeoutExpired(argv, .125)
                    calls = []
                    def run(sent, **kw):
                        calls.append((list(sent), kw))
                        if fail:
                            raise expired
                        return subprocess.CompletedProcess(sent, 9, 'out', 'err')
                    with patch.object(subprocess, 'run', run):
                        if fail:
                            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                                DockerLauncher().run(argv, .125, env=ENV)
                            self.assertIs(caught.exception, expired)
                        else:
                            self.assertEqual(DockerLauncher().run(argv, .125, env=ENV), (9, 'out', 'err'))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0][0], argv)
                    self.assertEqual(calls[0][1]['env'], ENV)
                    self.assertEqual(calls[0][1]['timeout'], .125)
                    self.assertEqual(calls[0][1]['stdin'], subprocess.DEVNULL)


if __name__ == '__main__':
    container_only()
    if len(sys.argv) == 4 and sys.argv[1] == '--child':
        scenario(sys.argv[2], float(sys.argv[3]))
    else:
        unittest.main(verbosity=2)
