"""Registry and the container wire protocol; no external commands."""
import dataclasses
import unittest

from bench.providers.registry import PROVIDERS, Provider, build_argv, by_name, parse_output


class RegistryTests(unittest.TestCase):
    def test_registry_contract(self):
        self.assertEqual({p.name for p in PROVIDERS}, {
            'curl', 'curl_cffi', 'primp', 'playwright', 'patchright', 'camoufox', 'pydoll', 'wayback', 'rss'})
        self.assertEqual(len(PROVIDERS), 9)
        for p in PROVIDERS:
            self.assertIsInstance(p.argv_extra, tuple)
            self.assertIsInstance(p.needs_network, bool)
            self.assertTrue(p.image)
            self.assertIn(p.kind, ('http', 'browser', 'entrance'))
            self.assertIn(p.tier, range(4))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            by_name('curl').tier = 9
        with self.assertRaises(KeyError):
            by_name('missing')

    def test_nonroot_and_no_mount(self):
        argv = build_argv(by_name('curl'), url='https://example.invalid/a b', sentinel='S;$(x)')
        self.assertIn('--user', argv)
        self.assertEqual(argv[argv.index('--user') + 1], '1002:1002')
        self.assertEqual(argv[:2], ['docker', 'run'])
        self.assertIn('--rm', argv)
        self.assertNotIn('-v', argv)
        self.assertNotIn('--network', argv)
        self.assertEqual(argv[-2:], ['https://example.invalid/a b', 'S;$(x)'])

    def test_browser_shm_and_explicit_network(self):
        argv = build_argv(by_name('playwright'), url='u', sentinel='s', network='host')
        self.assertIn('--shm-size=1g', argv)
        self.assertEqual(argv[argv.index('--network') + 1], 'host')
        self.assertNotIn('--shm-size=1g', build_argv(by_name('curl'), url='u', sentinel='s'))

    def test_docker_extra_options_precede_image(self):
        p = Provider('x', 'image', 0, 'http', True, ('--env', 'A=B'))
        argv = build_argv(p, url='u', sentinel='s')
        self.assertEqual(argv[-5:], ['--env', 'A=B', 'image', 'u', 's'])

    def test_last_json_line(self):
        got = parse_output(by_name('curl'), 'log\n{"ok": false}\n{"ok": true}\ntrailer\n')
        self.assertEqual(got, {'ok': True})

    def test_proxy_env_is_name_only_never_the_value(self):
        argv = build_argv(
            by_name('curl'), url='https://example.invalid/', sentinel='S',
            proxy_env='ABG_PROXY',
        )
        self.assertIn('--env', argv)
        self.assertEqual(argv[argv.index('--env') + 1], 'ABG_PROXY')
        self.assertNotIn('ABG_PROXY=', argv[argv.index('--env') + 1])
        self.assertFalse(any(part.startswith('ABG_PROXY=') for part in argv))
        self.assertNotIn('http://user:pass@proxy.invalid:8080', argv)
        self.assertFalse(any('@' in part for part in argv))
        env_index = argv.index('--env')
        image_index = argv.index(by_name('curl').image)
        self.assertLess(env_index, image_index)

    def test_without_proxy_env_there_is_no_env_flag(self):
        argv = build_argv(by_name('curl'), url='https://example.invalid/', sentinel='S')
        self.assertNotIn('--env', argv)
        self.assertNotIn('ABG_PROXY', argv)

    def test_invalid_output_has_excerpt(self):
        for output in ('', 'plain error', '{broken', '{"ok": true}\n{broken', '[]'):
            with self.subTest(output=output), self.assertRaises(ValueError) as ctx:
                parse_output(by_name('curl'), output)
            self.assertIn(output[:200], str(ctx.exception))
        output = 'x' * 201
        with self.assertRaises(ValueError) as ctx:
            parse_output(by_name('curl'), output)
        self.assertIn(output[:200], str(ctx.exception))
        self.assertNotIn(output, str(ctx.exception))
