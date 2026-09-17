"""Product policy regressions: priority, finite ladder and shared deadline."""
import unittest
from dataclasses import replace

from bench.escalate import Step
from bench.models import ChallengeType as C, FailureReason as F, FetchResult
from gateway.models import PlanStep, ProviderReply
from gateway.product import ProductRequest, accept_page, plan_product, run_product


def page(**changes):
    values = dict(provider='curl_cffi', provider_version='test', requested_url='https://a.test',
                  final_url='https://a.test/final', status=200, html='<p>actual</p>',
                  text='actual', elapsed_ms=1, startup_ms=0, cpu_ms=0,
                  peak_rss_mb=0.0, bytes_received=13, redirects=0,
                  error_type=F.none, challenge=C.none)
    values.update(changes)
    return FetchResult(**values)


class ProductTests(unittest.TestCase):
    def test_http_only_plan_preserves_egress_order_and_deduplicates(self):
        request = ProductRequest('https://a.test', allow_browser=False,
                                 egress_profiles=('silver', 'gold', 'silver'))
        self.assertEqual(plan_product(request), (
            PlanStep('curl_cffi', 'direct', 'http'),
            PlanStep('curl_cffi', 'silver', 'egress'),
            PlanStep('curl_cffi', 'gold', 'egress'),
        ))

    def test_product_plan_never_uses_curl(self):
        for allow_browser in (False, True):
            for max_age_hours in (0, 1):
                for profiles in ((), ('p', 'q')):
                    with self.subTest(browser=allow_browser, age=max_age_hours,
                                      profiles=profiles):
                        request = ProductRequest('https://a.test',
                                                 allow_browser=allow_browser,
                                                 max_age_hours=max_age_hours,
                                                 egress_profiles=profiles)
                        self.assertNotIn('curl', [step.provider for step in plan_product(request)])

    def test_status_and_challenge_precede_body_match(self):
        cases = [(dict(error_type=F.timeout, status=403), F.timeout),
                 (dict(status=403, challenge=C.interactive), F.http_403),
                 (dict(status=429), F.http_429), (dict(status=503), F.http_5xx),
                 (dict(status=302), F.content_mismatch),
                 (dict(status=True), F.provider_error),
                 (dict(challenge=C.interactive), F.interactive_challenge),
                 (dict(challenge=C.javascript_required), F.javascript_required)]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                self.assertEqual(accept_page(page(**changes), 'actual'), (False, reason))

    def test_expectation_does_not_replace_visible_text(self):
        self.assertEqual(accept_page(page(text='  '), 'actual'), (False, F.content_missing))
        self.assertEqual(accept_page(page(text='x', html=''), None), (True, F.none))
        self.assertEqual(accept_page(page(), 'ACTUAL'), (False, F.content_missing))
        for challenge, reason in [(C.suspected, F.challenge_suspected),
                                  (C.captcha, F.interactive_challenge)]:
            self.assertEqual(accept_page(page(challenge=challenge)), (False, reason))
            self.assertEqual(accept_page(page(challenge=challenge), 'actual'), (True, F.none))

    def test_403_browser_chain_preserves_trace(self):
        replies = [page(status=403), page(text=''), page(provider='scrapling', challenge=C.captcha)]
        calls = []
        def fetch(step, budget):
            calls.append(step.provider)
            return ProviderReply(replies[len(calls) - 1])
        result = run_product(ProductRequest('https://a.test', expected_text='actual'), fetch)
        self.assertTrue(result.ok)
        self.assertEqual(calls, ['curl_cffi', 'patchright', 'scrapling'])
        self.assertEqual([a.error_type for a in result.attempts],
                         [F.http_403, F.content_missing, F.none])
        self.assertEqual([a.next_step for a in result.attempts], [Step.browser, Step.browser, Step.stop])
        self.assertEqual(result.attempts[-1].challenge, C.captcha)

    def test_rate_limit_skips_browsers_and_unavailable_profiles(self):
        calls = []
        def fetch(step, budget):
            calls.append((step.provider, step.egress_profile))
            reason = F.not_measured if step.egress_profile == 'absent' else F.none
            return ProviderReply(page(status=429, error_type=reason))
        result = run_product(ProductRequest('https://a.test', egress_profiles=('absent', 'absent', 'p', 'q')), fetch)
        self.assertEqual(calls, [('curl_cffi', 'direct'), ('curl_cffi', 'absent'), ('curl_cffi', 'p')])
        self.assertEqual((result.ok, result.step, result.error_type), (False, Step.human, F.http_429))
        self.assertIsNone(result.attempts[1].next_step)
        self.assertEqual((result.html, result.text), ('', ''))

    def test_entrance_age_is_finite_nonnegative(self):
        for age in (None, float('nan'), float('inf'), -1, 3, True):
            calls = []
            def fetch(step, budget):
                calls.append(step.provider)
                return ProviderReply(page(provider=step.provider), age)
            result = run_product(ProductRequest('https://a.test', max_age_hours=2), fetch)
            self.assertEqual(calls, ['rss', 'wayback', 'curl_cffi'])
            self.assertEqual(result.attempts[0].error_type, F.content_mismatch)
            self.assertIsNone(result.attempts[0].next_step)

    def test_budget_remainder_and_late_success(self):
        now = [0]
        budgets = []
        def fetch(step, budget):
            budgets.append(budget)
            now[0] += 6
            return ProviderReply(page(text='' if len(budgets) == 1 else 'actual'))
        result = run_product(ProductRequest('https://a.test', budget_ms=10), fetch, clock=lambda: now[0])
        self.assertEqual(budgets, [10, 4])
        self.assertEqual((result.ok, result.error_type, result.step), (False, F.timeout, Step.retry_later))
        self.assertFalse(result.attempts[-1].success)
        self.assertEqual(result.attempts[-1].error_type, F.timeout)

    def test_only_http_and_egress_budgets_are_capped(self):
        now = [0]
        calls = []
        def fetch(step, budget):
            calls.append((step.purpose, budget))
            now[0] += 1000
            return ProviderReply(page(provider=step.provider, error_type=F.not_measured))
        result = run_product(ProductRequest('https://a.test', max_age_hours=1,
                                            egress_profiles=('gold',), budget_ms=120000),
                             fetch, clock=lambda: now[0])
        self.assertEqual(calls, [('entrance', 120000), ('entrance', 119000),
                                 ('http', 15000), ('browser', 117000),
                                 ('browser', 116000), ('egress', 15000)])
        self.assertEqual(len(result.attempts), 6)

    def test_http_and_egress_use_smaller_remaining_budget(self):
        now = [0]
        calls = []
        def fetch(step, budget):
            calls.append((step.purpose, budget))
            now[0] += 1000
            return ProviderReply(page(status=429 if step.purpose == 'http' else 200))
        result = run_product(ProductRequest('https://a.test', budget_ms=14000,
                                            egress_profiles=('gold',)),
                             fetch, clock=lambda: now[0])
        self.assertEqual(calls, [('http', 14000), ('egress', 13000)])
        self.assertTrue(result.ok)

    def test_http_timeout_leaves_budget_for_patchright(self):
        now = [0]
        calls = []
        def fetch(step, budget):
            calls.append((step.provider, step.egress_profile, budget))
            now[0] += 15000 if step.purpose == 'http' else 1000
            reason = F.timeout if step.purpose == 'http' else F.none
            return ProviderReply(page(provider=step.provider, error_type=reason))
        result = run_product(ProductRequest('https://a.test', budget_ms=120000),
                             fetch, clock=lambda: now[0])
        self.assertEqual(calls, [('curl_cffi', 'direct', 15000),
                                 ('patchright', 'direct', 105000)])
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, 'patchright')
        self.assertEqual([a.error_type for a in result.attempts], [F.timeout, F.none])
        self.assertEqual([a.next_step for a in result.attempts], [Step.browser, Step.stop])

    def test_http_timeout_without_browser_uses_first_egress(self):
        calls = []
        def fetch(step, budget):
            calls.append((step.provider, step.egress_profile))
            reason = F.timeout if step.purpose == 'http' else F.none
            return ProviderReply(page(error_type=reason))
        result = run_product(ProductRequest('https://a.test', allow_browser=False,
                                            egress_profiles=('silver', 'gold')),
                             fetch, clock=lambda: 0)
        self.assertEqual(calls, [('curl_cffi', 'direct'), ('curl_cffi', 'silver')])
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts[0].next_step, Step.change_egress)

    def test_egress_timeout_tries_next_profile_then_retries_later(self):
        calls = []
        def fetch(step, budget):
            calls.append(step.egress_profile)
            reason = F.none if step.purpose == 'http' else F.timeout
            return ProviderReply(page(status=429, error_type=reason))
        result = run_product(ProductRequest('https://a.test', egress_profiles=('silver', 'gold')),
                             fetch, clock=lambda: 0)
        self.assertEqual(calls, ['direct', 'silver', 'gold'])
        self.assertEqual([a.next_step for a in result.attempts],
                         [Step.change_egress, Step.change_egress, Step.retry_later])
        self.assertEqual((result.ok, result.error_type, result.step),
                         (False, F.timeout, Step.retry_later))

    def test_http_timeout_without_following_step_retries_later(self):
        result = run_product(ProductRequest('https://a.test', allow_browser=False),
                             lambda step, budget: ProviderReply(page(error_type=F.timeout)),
                             clock=lambda: 0)
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual((result.ok, result.error_type, result.step),
                         (False, F.timeout, Step.retry_later))

    def test_other_http_errors_keep_terminal_decisions(self):
        for reason, decision in ((F.connection_error, Step.retry_later),
                                 (F.dns_error, Step.retry_later),
                                 (F.tls_error, Step.retry_later),
                                 (F.http_5xx, Step.retry_later),
                                 (F.provider_error, Step.investigate)):
            with self.subTest(reason=reason):
                result = run_product(ProductRequest('https://a.test', egress_profiles=('gold',)),
                                     lambda step, budget: ProviderReply(page(error_type=reason)),
                                     clock=lambda: 0)
                self.assertEqual(len(result.attempts), 1)
                self.assertEqual((result.ok, result.error_type, result.step),
                                 (False, reason, decision))

    def test_entrance_timeout_continues_but_browser_timeout_is_terminal(self):
        calls = []
        def fetch(step, budget):
            calls.append(step.provider)
            reason = F.http_403 if step.purpose == 'http' else F.timeout
            return ProviderReply(page(provider=step.provider, error_type=reason))
        result = run_product(ProductRequest('https://a.test', max_age_hours=1,
                                            egress_profiles=('gold',)), fetch, clock=lambda: 0)
        self.assertEqual(calls, ['rss', 'wayback', 'curl_cffi', 'patchright'])
        self.assertEqual([a.next_step for a in result.attempts],
                         [None, None, Step.browser, Step.retry_later])
        self.assertEqual((result.ok, result.error_type, result.step),
                         (False, F.timeout, Step.retry_later))

    def test_late_http_and_egress_replies_do_not_escalate(self):
        for purpose in ('http', 'egress'):
            for reason in (F.none, F.timeout):
                with self.subTest(purpose=purpose, reason=reason):
                    now = [0]
                    calls = []
                    def fetch(step, budget):
                        calls.append(step.egress_profile)
                        if step.purpose == purpose:
                            now[0] = 30000
                            return ProviderReply(page(error_type=reason))
                        return ProviderReply(page(status=429))
                    result = run_product(ProductRequest('https://a.test', budget_ms=30000,
                                                        egress_profiles=('silver', 'gold')),
                                         fetch, clock=lambda: now[0])
                    self.assertEqual(calls, ['direct'] if purpose == 'http' else ['direct', 'silver'])
                    self.assertEqual((result.ok, result.error_type, result.step),
                                     (False, F.timeout, Step.retry_later))
                    self.assertFalse(result.attempts[-1].success)
                    self.assertEqual(result.attempts[-1].next_step, Step.retry_later)

    def test_invalid_request_never_calls_clock_or_fetcher(self):
        invalid = [dict(url=v) for v in (None, 0, True, [], {}, ' https://a.test',
                   'https://a.test:0', 'https://a.test:70000', 'https://a.test:abc',
                   'https://u:p@a.test', 'https://a.test/\x7f')]
        invalid += [dict(budget_ms=True), dict(budget_ms=180001), dict(max_age_hours=float('nan')),
                    dict(allow_browser=1), dict(expected_text=' '), dict(egress_profiles=['p']),
                    dict(egress_profiles=('direct',))]
        def forbidden(*args):
            self.fail('validation must precede IO and clock')
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                run_product(replace(ProductRequest('https://a.test'), **change), forbidden, clock=forbidden)

    def test_fetcher_exception_propagates(self):
        def fetch(*args):
            raise RuntimeError('broken adapter')
        with self.assertRaisesRegex(RuntimeError, 'broken adapter'):
            run_product(ProductRequest('https://a.test'), fetch)
