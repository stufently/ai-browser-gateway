"""Protocol stubs, not benchmark results. Zero metrics mean no measurement."""
import json


def payload(**changes):
    value = dict(ok=True, status=200, final_url='https://example.invalid/', bytes=0,
                 sentinel=True, challenge='none', title='', startup_ms=0,
                 elapsed_ms=0, peak_rss_mb=0.0, cpu_ms=0, err=None)
    value.update(changes)
    return value


class FakeLauncher:
    def __init__(self, *results):
        self.results = iter(results)
        self.calls = []

    def run(self, argv, timeout):
        self.calls.append((argv, timeout))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def output(**changes):
    return (0, json.dumps(payload(**changes)), '')


def observed_record(provider='curl', cell='target:x', mode='cold'):
    """Measure local hashing for aggregation tests, never claim provider timings."""
    import hashlib
    import resource
    import time
    from bench.providers.registry import by_name
    from bench.runner.matrix import PlanItem
    from bench.runner.execute import execute_plan
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    blob = hashlib.sha256(b'local report fixture; not a network benchmark').digest()
    for _ in range(2000):
        blob = hashlib.sha256(blob).digest()
    measured = dict(elapsed_ms=(time.perf_counter_ns() - started) // 1_000_000,
                    cpu_ms=(time.process_time_ns() - cpu) // 1_000_000,
                    peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                    bytes=len(blob))
    return execute_plan([PlanItem(provider, cell, mode, 0)], launcher=FakeLauncher(output(**measured)),
                        cells={cell: {'url': 'https://example.invalid/', 'sentinel': 'S'}},
                        env={'kernel': 'local-test-observation'})[0]
