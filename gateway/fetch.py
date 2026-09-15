"""Docker-backed transport for gateway.engine.run."""
from __future__ import annotations

from bench.runner.execute import fetch_page
from gateway.models import PlanStep, ProviderReply


class BenchFetcher:
    def __init__(self, url, sentinel, *, entrances=None, profiles=None,
                 launcher=None, network=None):
        self.url = url
        self.sentinel = sentinel
        self.entrances = dict(entrances or {})
        self.profiles = dict(profiles or {})
        self.launcher = launcher
        self.network = network

    def __call__(self, step: PlanStep, budget_ms: int) -> ProviderReply:
        if step.egress_profile == 'direct':
            egress = None
        else:
            egress = (step.egress_profile, self.profiles.get(step.egress_profile))
        result, age = fetch_page(
            step.provider,
            url=self.url,
            sentinel=self.sentinel,
            budget_ms=budget_ms,
            launcher=self.launcher,
            egress=egress,
            entrance_url=self.entrances.get(step.provider),
            network=self.network,
        )
        return ProviderReply(result, age)


class ProductFetcher:
    """One content-only cold request, with per-instance route configuration."""

    def __init__(self, url, *, entrances=None, profiles=None,
                 launcher=None, network=None):
        self.url = url
        self.entrances = dict(entrances or {})
        self.profiles = dict(profiles or {})
        self.launcher = launcher
        self.network = network

    def __call__(self, step: PlanStep, budget_ms: int) -> ProviderReply:
        from bench.runner.execute import fetch_content
        egress = (None if step.egress_profile == 'direct' else
                  (step.egress_profile, self.profiles.get(step.egress_profile)))
        result, age = fetch_content(
            step.provider, url=self.url, budget_ms=budget_ms, launcher=self.launcher,
            egress=egress, entrance_url=self.entrances.get(step.provider),
            network=self.network,
        )
        return ProviderReply(result, age)
