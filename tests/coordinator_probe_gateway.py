#!/usr/bin/env python3
"""Зонд постановщика для вехи M7: гоняет ЯДРО ШЛЮЗА по восьми сценариям.

Зонд написан постановщиком до начала вехи и опирается ТОЛЬКО на публичный
контракт из `docs/specs/m7-gateway-core.md`. Он не импортирует тесты
исполнителя: тест и код пишет один и тот же агент, и одно заблуждение попадает
в оба. Запускается из корня клона, ничего не пишет на диск, сети не трогает.
"""
from __future__ import annotations

import sys

from bench.escalate import Step
from bench.models import ChallengeType, FailureReason, FetchResult
from gateway.engine import run
from gateway.models import GatewayRequest, ProviderReply
from gateway.plan import plan_steps

FAILS: list[str] = []


def check(condition: bool, label: str, detail: object = "") -> None:
    if not condition:
        FAILS.append(f"{label}: {detail!r}")


def result(*, provider: str, status: int | None, html: str,
           error: FailureReason = FailureReason.none,
           challenge: ChallengeType = ChallengeType.none) -> FetchResult:
    return FetchResult(
        provider=provider, provider_version="probe", requested_url="https://example.invalid/p",
        final_url="https://example.invalid/p", status=status, html=html, text=html,
        elapsed_ms=1, startup_ms=0, cpu_ms=1, peak_rss_mb=1.0, bytes_received=len(html),
        redirects=0, error_type=error, challenge=challenge,
    )


class Fetcher:
    """Отдаёт заранее заготовленный ответ по имени провайдера и двигает часы."""

    def __init__(self, replies: dict[str, ProviderReply], cost_ms: int = 10) -> None:
        self.replies = replies
        self.cost_ms = cost_ms
        self.calls: list[tuple[str, str]] = []
        self.now = 0

    def __call__(self, step, budget_ms: int) -> ProviderReply:
        self.calls.append((step.provider, step.egress_profile))
        self.now += self.cost_ms
        try:
            return self.replies[step.provider]
        except KeyError:
            raise AssertionError(f"зонд не готовил ответа для {step.provider!r}") from None

    def clock(self) -> int:
        return self.now


SENTINEL = "ABG_PROBE_OK"
OK_HTML = f"<html>{SENTINEL}</html>"
EMPTY_HTML = "<html><body></body></html>"
DENIED_HTML = "<html>Just a moment...</html>"


def scenario_1_http_wins() -> None:
    fetcher = Fetcher({"curl": ProviderReply(result(provider="curl", status=200, html=OK_HTML))})
    out = run(GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL),
              fetcher, clock=fetcher.clock)
    check(out.ok is True, "1 успех", out)
    check(out.provider == "curl", "1 кто принёс", out.provider)
    check(len(out.attempts) == 1, "1 одна попытка", fetcher.calls)
    check(out.error_type is FailureReason.none, "1 без ошибки", out.error_type)


def scenario_2_browser_on_content_missing() -> None:
    fetcher = Fetcher({
        "curl": ProviderReply(result(provider="curl", status=200, html=EMPTY_HTML)),
        "patchright": ProviderReply(result(provider="patchright", status=200, html=OK_HTML)),
    })
    out = run(GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL),
              fetcher, clock=fetcher.clock)
    check(out.ok is True, "2 успех", out)
    check(out.provider == "patchright", "2 кто принёс", out.provider)
    check([name for name, _ in fetcher.calls] == ["curl", "patchright"], "2 порядок", fetcher.calls)
    check(out.attempts[0].next_step is Step.browser, "2 решение после HTTP", out.attempts[0])


def scenario_3_no_browser_on_403() -> None:
    fetcher = Fetcher({"curl": ProviderReply(result(
        provider="curl", status=403, html=DENIED_HTML, challenge=ChallengeType.access_denied))})
    out = run(GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL),
              fetcher, clock=fetcher.clock)
    check(out.ok is False, "3 отказ", out)
    check("patchright" not in [name for name, _ in fetcher.calls], "3 браузер НЕ звали", fetcher.calls)
    check(out.step is Step.change_egress, "3 куда дальше", out.step)
    check(out.error_type is FailureReason.http_403, "3 причина", out.error_type)


def scenario_4_egress_then_human() -> None:
    fetcher = Fetcher({"curl": ProviderReply(result(
        provider="curl", status=403, html=DENIED_HTML, challenge=ChallengeType.access_denied))})
    out = run(GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL,
                             egress_profiles=("gold",)), fetcher, clock=fetcher.clock)
    check(fetcher.calls == [("curl", "direct"), ("curl", "gold")], "4 вторая попытка через прокси", fetcher.calls)
    check(out.ok is False, "4 отказ", out)
    check(out.step is Step.human, "4 после смены egress — человек", out.step)


def scenario_5_no_entrance_when_age_zero() -> None:
    steps = plan_steps(GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL))
    names = [step.provider for step in steps]
    check("rss" not in names and "wayback" not in names, "5 входов нет при max_age_hours=0", names)
    check(names[0] == "curl", "5 первым идёт HTTP", names)


def scenario_6_entrance_first_when_stale_allowed() -> None:
    fetcher = Fetcher({"rss": ProviderReply(
        result(provider="rss", status=200, html=OK_HTML), age_hours=0.02)})
    request = GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL, max_age_hours=24.0)
    names = [step.provider for step in plan_steps(request)]
    check(names[0] in ("rss", "wayback"), "6 вход первым", names)
    out = run(request, fetcher, clock=fetcher.clock)
    check(out.ok is True and out.provider == "rss", "6 вход принёс содержимое", out)
    check(out.age_hours == 0.02, "6 возраст доехал до ответа", out.age_hours)


def scenario_7_stale_entrance_rejected() -> None:
    fetcher = Fetcher({
        "rss": ProviderReply(result(provider="rss", status=200, html=OK_HTML), age_hours=5.0),
        "wayback": ProviderReply(result(provider="wayback", status=200, html=OK_HTML), age_hours=9.0),
        "curl": ProviderReply(result(provider="curl", status=200, html=OK_HTML)),
    })
    out = run(GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL, max_age_hours=1.0),
              fetcher, clock=fetcher.clock)
    check(out.ok is True, "7 успех", out)
    check(out.provider == "curl", "7 протухший вход отвергнут", out.provider)
    check(out.attempts[0].success is False, "7 первая попытка неуспешна", out.attempts[0])


def scenario_8_budget_stops_the_ladder() -> None:
    fetcher = Fetcher({
        "curl": ProviderReply(result(provider="curl", status=200, html=EMPTY_HTML)),
        "patchright": ProviderReply(result(provider="patchright", status=200, html=OK_HTML)),
    }, cost_ms=600)
    out = run(GatewayRequest(url="https://example.invalid/p", sentinel=SENTINEL, budget_ms=500),
              fetcher, clock=fetcher.clock)
    check(len(fetcher.calls) == 1, "8 вторая попытка не запускалась", fetcher.calls)
    check(out.ok is False, "8 отказ", out)
    check(out.error_type is FailureReason.timeout, "8 причина — бюджет", out.error_type)
    check(out.step is Step.retry_later, "8 куда дальше", out.step)


def scenario_9_empty_sentinel_is_a_call_defect() -> None:
    fetcher = Fetcher({})
    try:
        run(GatewayRequest(url="https://example.invalid/p", sentinel=""), fetcher, clock=fetcher.clock)
    except ValueError:
        return
    except Exception as exc:  # noqa: BLE001 — нужен именно тип исключения
        FAILS.append(f"9 пустой sentinel: {type(exc).__name__}, ждали ValueError")
        return
    FAILS.append("9 пустой sentinel: исключения не было вовсе")


def main() -> int:
    for scenario in (
        scenario_1_http_wins,
        scenario_2_browser_on_content_missing,
        scenario_3_no_browser_on_403,
        scenario_4_egress_then_human,
        scenario_5_no_entrance_when_age_zero,
        scenario_6_entrance_first_when_stale_allowed,
        scenario_7_stale_entrance_rejected,
        scenario_8_budget_stops_the_ladder,
        scenario_9_empty_sentinel_is_a_call_defect,
    ):
        try:
            scenario()
        except Exception as exc:  # noqa: BLE001 — падение сценария не должно скрывать остальные
            FAILS.append(f"{scenario.__name__}: {type(exc).__name__}: {exc}")
    if FAILS:
        print("ЗОНД КРАСНЫЙ:")
        for line in FAILS:
            print(" -", line)
        return 1
    print("ЗОНД ЗЕЛЁНЫЙ: девять сценариев лестницы прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
