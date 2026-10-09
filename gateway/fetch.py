"""Docker-backed transport for gateway.engine.run."""
from __future__ import annotations

from urllib.parse import urlsplit

from bench.models import ChallengeType, FailureReason
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
    """One content-only cold request, with per-instance route configuration.

    With a session store, the direct HTTP step replays the cookies and UA a
    browser left for this host, and a direct browser that passes leaves its
    own. A replay that does not pass is dropped, unless a newer session took
    its place. Cookies are bound to the address that solved them, so egress
    steps never use or leave one; plain http never does either, since the
    stored cookies carry no Secure flag.
    """

    def __init__(self, url, *, entrances=None, profiles=None,
                 launcher=None, network=None, sessions=None):
        self.url = url
        self.entrances = dict(entrances or {})
        self.profiles = dict(profiles or {})
        self.launcher = launcher
        self.network = network
        self.sessions = sessions
        self.host = urlsplit(url).hostname

    def __call__(self, step: PlanStep, budget_ms: int) -> ProviderReply:
        from bench.runner.execute import fetch_content
        egress = (None if step.egress_profile == 'direct' else
                  (step.egress_profile, self.profiles.get(step.egress_profile)))
        options = {}
        replay = None
        if (self.sessions is not None and egress is None and self.host
                and urlsplit(self.url).scheme == 'https'):
            if step.purpose == 'http':
                replay = self.sessions.get(self.host)
                if replay is not None:
                    options['session'] = replay
            elif step.purpose == 'browser':
                options['on_session'] = lambda value: self.sessions.put(self.host, value)
        result, age = fetch_content(
            step.provider, url=self.url, budget_ms=budget_ms, launcher=self.launcher,
            egress=egress, entrance_url=self.entrances.get(step.provider),
            network=self.network, **options,
        )
        if replay is not None and not (
                result.error_type == FailureReason.none and type(result.status) is int
                and 200 <= result.status < 300 and result.challenge == ChallengeType.none
                and urlsplit(result.final_url).hostname == self.host):
            self.sessions.drop(self.host, replay)
        return ProviderReply(result, age)
