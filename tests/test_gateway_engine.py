"""Behavioral gateway contract, using the real evaluator and escalation rule."""

import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from bench.escalate import Step, next_step
from bench.models import ChallengeType, FailureReason
from gateway.engine import run
from gateway.models import Attempt, GatewayRequest
from tests.gateway_helpers import FakeFetcher, SENTINEL, URL, reply


class EngineTests(unittest.TestCase):
    def run_fake(self, fetcher, **options):
        return run(GatewayRequest(URL, SENTINEL, **options), fetcher,
                   clock=fetcher.clock)

    def test_http_success_preserves_payload_and_trace(self):
        fetcher = FakeFetcher(reply(html="<p>GATEWAY_OK</p>", text="body", age=3))
        out = self.run_fake(fetcher)
        self.assertTrue(out.ok)
        self.assertEqual(fetcher.routes, [("curl", "direct")])
        self.assertEqual((out.url, out.final_url, out.provider, out.html, out.text,
                          out.age_hours, out.error_type, out.step, out.elapsed_ms),
                         (URL, URL + "/final", "curl", "<p>GATEWAY_OK</p>", "body",
                          3, FailureReason.none, Step.stop, 10))
        self.assertEqual(out.attempts, (Attempt(
            "curl", "direct", True, FailureReason.none, ChallengeType.none,
            200, 7, 3, Step.stop),))
        self.assertEqual(fetcher.calls[0][1], 30_000)

    def test_contracts_are_frozen_and_slotted(self):
        out = self.run_fake(FakeFetcher(reply()))
        objects = (GatewayRequest(URL, SENTINEL), out, out.attempts[0], reply())
        for obj in objects:
            with self.subTest(type=type(obj).__name__):
                self.assertFalse(hasattr(obj, "__dict__"))
                field = next(iter(obj.__dataclass_fields__))
                with self.assertRaises(FrozenInstanceError):
                    setattr(obj, field, None)

    def test_browser_fills_missing_content(self):
        fetcher = FakeFetcher(reply(html="shell"), reply("patchright"))
        out = self.run_fake(fetcher)
        self.assertEqual(fetcher.routes, [("curl", "direct"), ("patchright", "direct")])
        self.assertTrue(out.ok)
        self.assertEqual(out.provider, "patchright")
        self.assertEqual(out.attempts[0].next_step, Step.browser)

    def test_javascript_required_uses_browser(self):
        fetcher = FakeFetcher(reply(reason=FailureReason.javascript_required),
                              reply("patchright"))
        out = self.run_fake(fetcher)
        self.assertEqual(out.provider, "patchright")
        self.assertTrue(out.ok)

    def test_disabled_browser_returns_unfulfilled_decision(self):
        fetcher = FakeFetcher(reply(html="shell"))
        out = self.run_fake(fetcher, allow_browser=False, egress_profiles=("gold",))
        self.assertEqual(out.step, Step.browser)
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.content_missing)
        self.assertEqual(fetcher.routes, [("curl", "direct")])

    def test_browser_is_not_retried_or_followed_by_unrequested_egress(self):
        fetcher = FakeFetcher(reply(html="shell"), reply("patchright", html="shell"))
        out = self.run_fake(fetcher, egress_profiles=("gold",))
        self.assertEqual(out.step, Step.browser)
        self.assertEqual(len(out.attempts), 2)
        self.assertFalse(out.ok)

    def test_blocked_http_changes_egress_without_browser(self):
        fetcher = FakeFetcher(reply(status=403), reply())
        out = self.run_fake(fetcher, egress_profiles=("gold", "silver"))
        self.assertEqual(fetcher.routes, [("curl", "direct"), ("curl", "gold")])
        self.assertTrue(out.ok)
        self.assertEqual(out.attempts[0].next_step, Step.change_egress)

    def test_second_block_needs_human_without_trying_another_profile(self):
        fetcher = FakeFetcher(reply(status=403), reply(status=429), reply())
        out = self.run_fake(fetcher, egress_profiles=("gold", "silver"))
        self.assertEqual(out.step, Step.human)
        self.assertEqual(fetcher.routes, [("curl", "direct"), ("curl", "gold")])
        self.assertEqual(out.error_type, FailureReason.http_429)
        self.assertEqual(out.attempts[-1].next_step, Step.human)

    def test_blocked_http_without_egress_stops(self):
        for status in (403, 429):
            with self.subTest(status=status):
                fetcher = FakeFetcher(reply(status=status))
                out = self.run_fake(fetcher)
                self.assertEqual(out.step, Step.change_egress)
                self.assertFalse(out.ok)
                self.assertEqual(fetcher.routes, [("curl", "direct")])

    def test_challenged_missing_content_does_not_render(self):
        for reason in (FailureReason.content_missing, FailureReason.javascript_required,
                       FailureReason.challenge_suspected):
            with self.subTest(reason=reason):
                fetcher = FakeFetcher(reply(reason=reason, challenge=ChallengeType.suspected),
                                      reply())
                out = self.run_fake(fetcher, egress_profiles=("gold",))
                self.assertTrue(out.ok)
                self.assertEqual(fetcher.routes, [("curl", "direct"), ("curl", "gold")])

    def test_browser_block_can_change_egress(self):
        fetcher = FakeFetcher(reply(html="shell"), reply("patchright", status=403), reply())
        out = self.run_fake(fetcher, egress_profiles=("gold",))
        self.assertTrue(out.ok)
        self.assertEqual(fetcher.routes,
                         [("curl", "direct"), ("patchright", "direct"), ("curl", "gold")])

    def test_cursor_does_not_return_to_skipped_browser_after_egress(self):
        fetcher = FakeFetcher(reply(status=403), reply(html="shell"))
        out = self.run_fake(fetcher, egress_profiles=("gold", "silver"))
        self.assertEqual(out.step, Step.browser)
        self.assertEqual(fetcher.routes, [("curl", "direct"), ("curl", "gold")])

    def test_duplicate_direct_profile_cannot_retry_same_route(self):
        fetcher = FakeFetcher(reply(status=403), reply())
        out = self.run_fake(fetcher, egress_profiles=("direct", "gold", "gold"))
        self.assertEqual(fetcher.routes, [("curl", "direct"), ("curl", "gold")])
        self.assertTrue(out.ok)

    def test_terminal_reasons_are_not_retried(self):
        cases = (
            (FailureReason.timeout, Step.retry_later),
            (FailureReason.connection_error, Step.retry_later),
            (FailureReason.dns_error, Step.retry_later),
            (FailureReason.tls_error, Step.retry_later),
            (FailureReason.http_5xx, Step.retry_later),
            (FailureReason.content_mismatch, Step.give_up),
            (FailureReason.interactive_challenge, Step.human),
            (FailureReason.provider_error, Step.investigate),
            (FailureReason.environment_error, Step.investigate),
        )
        for reason, decision in cases:
            with self.subTest(reason=reason):
                fetcher = FakeFetcher(reply(reason=reason))
                out = self.run_fake(fetcher, egress_profiles=("gold",))
                self.assertFalse(out.ok)
                self.assertEqual((out.error_type, out.step), (reason, decision))
                self.assertEqual(len(out.attempts), 1)
                self.assertIsNone(out.provider)
                self.assertEqual((out.html, out.text, out.age_hours), ("", "", None))

    def test_fresh_entrance_is_accepted_without_escalation(self):
        fetcher = FakeFetcher(reply("rss", age=0.2))
        with patch("gateway.engine.next_step", side_effect=AssertionError("entrance escalated")):
            out = self.run_fake(fetcher, max_age_hours=1)
        self.assertTrue(out.ok)
        self.assertEqual((out.provider, out.age_hours), ("rss", 0.2))
        self.assertIsNone(out.attempts[0].next_step)
        self.assertEqual(out.step, Step.stop)

    def test_entrance_age_equal_to_limit_is_accepted(self):
        fetcher = FakeFetcher(reply("rss", age=1), reply("wayback", age=0.5), reply())
        out = self.run_fake(fetcher, max_age_hours=1)
        self.assertEqual(out.provider, "rss")
        self.assertEqual(len(out.attempts), 1)

    def test_stale_and_unknown_entrances_fall_through_to_http(self):
        fetcher = FakeFetcher(reply("rss", age=1.01), reply("wayback"), reply())
        out = self.run_fake(fetcher, max_age_hours=1)
        self.assertEqual(out.provider, "curl")
        self.assertEqual(fetcher.routes, [("rss", "direct"), ("wayback", "direct"),
                                         ("curl", "direct")])
        for attempt in out.attempts[:2]:
            self.assertFalse(attempt.success)
            self.assertEqual(attempt.error_type, FailureReason.content_mismatch)
            self.assertIsNone(attempt.next_step)

    def test_failed_entrance_keeps_evaluated_reason_and_tries_next_entrance(self):
        fetcher = FakeFetcher(reply("rss", status=403, age=0), reply("wayback", age=0.1))
        with patch("gateway.engine.next_step", side_effect=AssertionError("entrance escalated")):
            out = self.run_fake(fetcher, max_age_hours=1)
        self.assertEqual(out.provider, "wayback")
        self.assertEqual(out.attempts[0].error_type, FailureReason.http_403)
        self.assertFalse(out.attempts[0].success)
        self.assertEqual(out.age_hours, 0.1)

    def test_entrance_failures_do_not_change_egress_state(self):
        fetcher = FakeFetcher(reply("rss", reason=FailureReason.interactive_challenge),
                              reply("wayback", reason=FailureReason.timeout),
                              reply(status=403), reply())
        with patch("gateway.engine.next_step", wraps=next_step) as decide:
            out = self.run_fake(fetcher, max_age_hours=1, egress_profiles=("gold",))
        self.assertTrue(out.ok)
        self.assertEqual([call.kwargs["egress_changed"] for call in decide.call_args_list],
                         [False, True])
        self.assertEqual([attempt.next_step for attempt in out.attempts],
                         [None, None, Step.change_egress, Step.stop])

    def test_remaining_budget_and_outcome_use_clock_not_provider_metrics(self):
        fetcher = FakeFetcher(reply(html="shell", elapsed_ms=12345),
                              reply("patchright", elapsed_ms=54321), costs=[11, 13])
        out = self.run_fake(fetcher, budget_ms=100)
        self.assertEqual([budget for _, budget in fetcher.calls], [100, 89])
        self.assertEqual(out.elapsed_ms, 24)
        self.assertEqual([attempt.elapsed_ms for attempt in out.attempts], [12345, 54321])

    def test_budget_at_zero_prevents_next_attempt(self):
        fetcher = FakeFetcher(reply(html="shell"), reply("patchright"), costs=[100, 10])
        out = self.run_fake(fetcher, budget_ms=100)
        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual((out.error_type, out.step), (FailureReason.timeout, Step.retry_later))
        self.assertFalse(out.ok)
        self.assertEqual(out.elapsed_ms, 100)
        self.assertEqual(len(out.attempts), 1)
        self.assertEqual(out.attempts[0].next_step, Step.browser)

    def test_overrun_prevents_next_entrance(self):
        fetcher = FakeFetcher(reply("rss", age=2), costs=[101])
        out = self.run_fake(fetcher, max_age_hours=1, budget_ms=100)
        self.assertEqual(out.error_type, FailureReason.timeout)
        self.assertEqual(out.step, Step.retry_later)
        self.assertEqual(len(out.attempts), 1)
        self.assertEqual(out.attempts[0].error_type, FailureReason.content_mismatch)
        self.assertEqual(out.elapsed_ms, 101)

    def test_budget_can_expire_before_first_fetch(self):
        times = iter((500, 600, 603))
        fetcher = FakeFetcher()
        out = run(GatewayRequest(URL, SENTINEL, budget_ms=100), fetcher,
                  clock=lambda: next(times))
        self.assertEqual(out.error_type, FailureReason.timeout)
        self.assertEqual(out.step, Step.retry_later)
        self.assertEqual(out.attempts, ())
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(out.elapsed_ms, 103)
        self.assertEqual(out.final_url, URL)

    def test_success_returned_by_fetcher_is_accepted_even_if_it_overruns(self):
        fetcher = FakeFetcher(reply(), costs=[101])
        out = self.run_fake(fetcher, budget_ms=100)
        self.assertTrue(out.ok)
        self.assertEqual(out.elapsed_ms, 101)

    def test_invalid_requests_fail_before_clock_or_fetch(self):
        valid = GatewayRequest(URL, SENTINEL)
        requests = [replace(valid, sentinel=""), replace(valid, url=""),
                    replace(valid, budget_ms=0), replace(valid, budget_ms=-1)]
        for request in requests:
            with self.subTest(request=request):
                fetcher = FakeFetcher()
                with self.assertRaises(ValueError):
                    run(request, fetcher, clock=lambda: self.fail("clock called"))
                self.assertEqual(fetcher.calls, [])

    def test_failure_with_stop_is_assertion_error(self):
        with patch("gateway.engine.next_step", return_value=Step.stop):
            with self.assertRaisesRegex(AssertionError, ".+"):
                self.run_fake(FakeFetcher(reply(html="shell")))

    def test_fetcher_exception_is_not_silently_classified(self):
        def broken(step, budget_ms):
            raise RuntimeError("adapter defect")
        with self.assertRaisesRegex(RuntimeError, "adapter defect"):
            run(GatewayRequest(URL, SENTINEL), broken)

    def test_default_clock_returns_elapsed_milliseconds(self):
        with patch("gateway.engine.time.monotonic_ns", side_effect=(
                500_000_000, 503_000_000, 511_000_000)):
            fetcher = FakeFetcher(reply())
            out = run(GatewayRequest(URL, SENTINEL, budget_ms=100), fetcher)
        self.assertEqual(out.elapsed_ms, 11)
        self.assertEqual(fetcher.calls[0][1], 97)


if __name__ == "__main__":
    unittest.main()
