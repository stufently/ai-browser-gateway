"""The menu preserves price order and explicit caller permissions."""

import unittest

from gateway.models import GatewayRequest, PlanStep
from gateway.plan import plan_steps
from tests.gateway_helpers import SENTINEL, URL


class PlanTests(unittest.TestCase):
    def test_defaults_exclude_entrances_and_include_browser(self):
        self.assertEqual(plan_steps(GatewayRequest(URL, SENTINEL)), (
            PlanStep("curl", "direct", "http"),
            PlanStep("patchright", "direct", "browser"),
        ))

    def test_complete_menu_preserves_declared_egress_order(self):
        request = GatewayRequest(URL, SENTINEL, max_age_hours=1,
                                 egress_profiles=("z", "a"))
        self.assertEqual(plan_steps(request), (
            PlanStep("rss", "direct", "entrance"),
            PlanStep("wayback", "direct", "entrance"),
            PlanStep("curl", "direct", "http"),
            PlanStep("patchright", "direct", "browser"),
            PlanStep("curl", "z", "egress"),
            PlanStep("curl", "a", "egress"),
        ))

    def test_disabling_browser_keeps_egress(self):
        self.assertEqual(plan_steps(GatewayRequest(
            URL, SENTINEL, allow_browser=False, egress_profiles=("gold",))), (
                PlanStep("curl", "direct", "http"),
                PlanStep("curl", "gold", "egress"),
            ))

    def test_nonpositive_freshness_never_opts_in(self):
        for age in (0, -1):
            with self.subTest(age=age):
                self.assertEqual(plan_steps(GatewayRequest(
                    URL, SENTINEL, max_age_hours=age, allow_browser=False)),
                    (PlanStep("curl", "direct", "http"),))


if __name__ == "__main__":
    unittest.main()
