import unittest
from bench.runner.environment import collect


class EnvironmentTests(unittest.TestCase):
    def test_missing_is_unknown(self):
        result = collect(reader=lambda key: None)
        self.assertEqual(result, dict.fromkeys(('date', 'kernel', 'docker_version', 'egress_ip', 'asn'), 'unknown'))

    def test_reader_values_and_independent_failures(self):
        seen = []
        def reader(key):
            seen.append(key)
            if key == 'egress_ip':
                raise OSError('offline')
            return ' observed-' + key + ' '
        result = collect(reader=reader)
        self.assertEqual(len(seen), 5)
        self.assertEqual(result['egress_ip'], 'unknown')
        self.assertEqual(result['asn'], 'observed-asn')
        self.assertEqual(result['kernel'], 'observed-kernel')

    def test_empty_unusable_values(self):
        for value in ('', ' \n', None, {}, []):
            with self.subTest(value=value):
                self.assertEqual(set(collect(reader=lambda key: value).values()), {'unknown'})
