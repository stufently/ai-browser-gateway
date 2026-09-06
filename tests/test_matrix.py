import unittest
from bench.providers.registry import by_name
from bench.runner.matrix import build_plan


class MatrixTests(unittest.TestCase):
    def test_http_has_no_warm(self):
        plan = build_plan([by_name('curl'), by_name('playwright')], ['target:x'], cold=2, warm=3)
        self.assertNotIn(('curl', 'warm'), {(p.provider, p.mode) for p in plan})
        self.assertEqual(len(plan), 7)
        self.assertEqual(sum(p.mode == 'warm' for p in plan), 3)

    def test_ids_and_order_are_reproducible(self):
        providers = [by_name('curl'), by_name('camoufox')]
        cells = ['scenario:static', 'target:x']
        plan = build_plan(iter(providers), iter(cells), cold=2, warm=1)
        self.assertEqual(plan, build_plan(providers, cells, cold=2, warm=1))
        self.assertEqual(len({p.run_id for p in plan}), len(plan))
        for p in plan:
            self.assertEqual(p.run_id, f'{p.provider}:{p.cell}:{p.mode}:{p.index}')
        self.assertEqual([p.index for p in plan[:2]], [0, 1])

    def test_empty_counts_and_entrance(self):
        self.assertEqual(build_plan([by_name('curl')], ['target:x'], cold=0, warm=3), [])
        self.assertEqual(build_plan([], ['x'], cold=1, warm=1), [])
        self.assertEqual(build_plan([by_name('curl')], [], cold=1, warm=1), [])
        plan = build_plan([by_name('wayback')], ['target:x'], cold=1, warm=3)
        self.assertEqual([p.mode for p in plan], ['cold'])

    def test_negative_counts_and_duplicates_rejected(self):
        for cold, warm in ((-1, 0), (0, -1), (True, 1), (1.5, 0)):
            with self.subTest(cold=cold, warm=warm), self.assertRaises(ValueError):
                build_plan([by_name('curl')], ['x'], cold=cold, warm=warm)
        with self.assertRaises(ValueError):
            build_plan([by_name('curl')] * 2, ['x'], cold=1, warm=0)
        with self.assertRaises(ValueError):
            build_plan([by_name('curl')], ['x', 'x'], cold=1, warm=0)
