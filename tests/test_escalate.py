"""Escalation table from the phase-1 measurements."""

from __future__ import annotations

import unittest

from bench.escalate import Step, next_step
from bench.models import ChallengeType, FailureReason


class NextStepTests(unittest.TestCase):
    def test_success_stops_regardless_of_challenge(self):
        self.assertIs(
            next_step(FailureReason.none, ChallengeType.suspected, egress_changed=False),
            Step.stop,
        )

    def test_content_missing_without_challenge_goes_to_browser(self):
        self.assertIs(
            next_step(FailureReason.content_missing, ChallengeType.none, egress_changed=False),
            Step.browser,
        )

    def test_content_missing_with_challenge_changes_egress(self):
        self.assertIs(
            next_step(
                FailureReason.content_missing,
                ChallengeType.suspected,
                egress_changed=False,
            ),
            Step.change_egress,
        )

    def test_javascript_required_without_challenge_goes_to_browser(self):
        self.assertIs(
            next_step(
                FailureReason.javascript_required,
                ChallengeType.none,
                egress_changed=False,
            ),
            Step.browser,
        )

    def test_http_403_and_429_change_egress(self):
        self.assertIs(
            next_step(FailureReason.http_403, ChallengeType.none, egress_changed=False),
            Step.change_egress,
        )
        self.assertIs(
            next_step(FailureReason.http_429, ChallengeType.captcha, egress_changed=False),
            Step.change_egress,
        )

    def test_network_and_5xx_retry_later(self):
        for reason in (
            FailureReason.timeout,
            FailureReason.connection_error,
            FailureReason.dns_error,
            FailureReason.tls_error,
            FailureReason.http_5xx,
        ):
            with self.subTest(reason=reason):
                self.assertIs(
                    next_step(reason, ChallengeType.none, egress_changed=False),
                    Step.retry_later,
                )

    def test_content_mismatch_gives_up(self):
        self.assertIs(
            next_step(
                FailureReason.content_mismatch,
                ChallengeType.none,
                egress_changed=False,
            ),
            Step.give_up,
        )

    def test_interactive_challenge_needs_human(self):
        self.assertIs(
            next_step(
                FailureReason.interactive_challenge,
                ChallengeType.interactive,
                egress_changed=False,
            ),
            Step.human,
        )

    def test_provider_error_is_investigate(self):
        self.assertIs(
            next_step(
                FailureReason.provider_error,
                ChallengeType.none,
                egress_changed=False,
            ),
            Step.investigate,
        )

    def test_changed_egress_becomes_human(self):
        self.assertIs(
            next_step(
                FailureReason.content_missing,
                ChallengeType.suspected,
                egress_changed=True,
            ),
            Step.human,
        )

    def test_changed_egress_does_not_rewrite_browser(self):
        self.assertIs(
            next_step(
                FailureReason.content_missing,
                ChallengeType.none,
                egress_changed=True,
            ),
            Step.browser,
        )

    def test_challenge_suspected_changes_egress(self):
        self.assertIs(
            next_step(
                FailureReason.challenge_suspected,
                ChallengeType.suspected,
                egress_changed=False,
            ),
            Step.change_egress,
        )

    def test_javascript_required_with_challenge_changes_egress(self):
        self.assertIs(
            next_step(
                FailureReason.javascript_required,
                ChallengeType.suspected,
                egress_changed=False,
            ),
            Step.change_egress,
        )

    def test_changed_egress_http_403_becomes_human(self):
        self.assertIs(
            next_step(
                FailureReason.http_403,
                ChallengeType.none,
                egress_changed=True,
            ),
            Step.human,
        )

    def test_changed_egress_http_429_with_challenge_becomes_human(self):
        self.assertIs(
            next_step(
                FailureReason.http_429,
                ChallengeType.suspected,
                egress_changed=True,
            ),
            Step.human,
        )

    def test_changed_egress_timeout_stays_retry_later(self):
        self.assertIs(
            next_step(
                FailureReason.timeout,
                ChallengeType.none,
                egress_changed=True,
            ),
            Step.retry_later,
        )


if __name__ == "__main__":
    unittest.main()
