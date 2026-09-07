"""Success is a sentinel, never HTTP 200."""

from __future__ import annotations

import unittest

from bench.models import ChallengeType, FailureReason, FetchResult, evaluate


def _result(**kwargs) -> FetchResult:
    data = dict(
        provider="curl",
        provider_version="8",
        requested_url="http://stand/static",
        final_url="http://stand/static",
        status=200,
        html="",
        text="",
        elapsed_ms=10,
        startup_ms=0,
        cpu_ms=1,
        peak_rss_mb=1.5,
        bytes_received=100,
        redirects=0,
        error_type=FailureReason.none,
        challenge=ChallengeType.none,
    )
    data.update(kwargs)
    return FetchResult(**data)


class EvaluateTests(unittest.TestCase):
    def test_sentinel_in_html_is_success(self) -> None:
        result = _result(html="<p>ABG_TEST_STATIC_OK</p>", text="other")
        ok, reason = evaluate(result, "ABG_TEST_STATIC_OK")
        self.assertTrue(ok)
        self.assertEqual(reason, FailureReason.none)

    def test_sentinel_in_text_only_is_success(self) -> None:
        result = _result(html="<p>nope</p>", text="ABG_TEST_STATIC_OK")
        ok, reason = evaluate(result, "ABG_TEST_STATIC_OK")
        self.assertTrue(ok)
        self.assertEqual(reason, FailureReason.none)

    def test_http_200_without_sentinel_is_not_success(self) -> None:
        result = _result(
            status=200,
            html="<html><body>Just a moment... cloudflare challenge</body></html>",
            text="Just a moment...",
        )
        ok, reason = evaluate(result, "ABG_TEST_STATIC_OK")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.content_missing)

    def test_existing_error_type_is_propagated(self) -> None:
        result = _result(
            status=200,
            html="ABG_TEST_STATIC_OK",
            error_type=FailureReason.timeout,
        )
        ok, reason = evaluate(result, "ABG_TEST_STATIC_OK")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.timeout)

    def test_status_403_without_sentinel(self) -> None:
        ok, reason = evaluate(_result(status=403, html="denied"), "ABG_TEST_STATIC_OK")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.http_403)

    def test_status_429_without_sentinel(self) -> None:
        ok, reason = evaluate(_result(status=429, html="wait"), "ABG_TEST_STATIC_OK")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.http_429)

    def test_status_5xx_without_sentinel(self) -> None:
        ok, reason = evaluate(_result(status=503, html="down"), "ABG_TEST_STATIC_OK")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.http_5xx)

    def test_other_status_is_content_mismatch(self) -> None:
        ok, reason = evaluate(_result(status=404, html="nope"), "ABG_TEST_STATIC_OK")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.content_mismatch)

    def test_empty_sentinel_is_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            evaluate(_result(html="x"), "")
        self.assertIn("empty sentinel", str(ctx.exception))

    def test_status_403_with_sentinel_is_http_403(self) -> None:
        result = _result(status=403, html="<p>SENT</p>", text="SENT")
        ok, reason = evaluate(result, "SENT")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.http_403)

    def test_status_429_with_sentinel_is_http_429(self) -> None:
        result = _result(status=429, html="<p>SENT</p>", text="SENT")
        ok, reason = evaluate(result, "SENT")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.http_429)

    def test_other_4xx_with_sentinel_is_content_mismatch(self) -> None:
        result = _result(status=404, html="<p>SENT</p>", text="SENT")
        ok, reason = evaluate(result, "SENT")
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.content_mismatch)

    def test_status_500_is_http_5xx(self) -> None:
        result = _result(status=500, html="<p>SENT</p>", text="SENT")
        ok, reason = evaluate(result, "SENT")
        self.assertEqual(reason, FailureReason.http_5xx)
        self.assertFalse(ok)

    def test_environment_error_is_a_failure_reason(self) -> None:
        self.assertEqual(FailureReason.environment_error, "environment_error")
        self.assertIn(FailureReason.environment_error, FailureReason)

    def test_status_599_is_http_5xx(self) -> None:
        result = _result(status=599, html="<p>SENT</p>", text="SENT")
        ok, reason = evaluate(result, "SENT")
        self.assertEqual(reason, FailureReason.http_5xx)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
