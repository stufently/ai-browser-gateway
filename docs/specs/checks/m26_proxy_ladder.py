"""Чекер M26: вся лестница one-shot через один прокси (без сети и браузера).

Владеет постановщик; исполнитель его не правит. Запуск из корня клона:
  python3 docs/specs/checks/m26_proxy_ladder.py      ->  печатает `ok`

Подменяется только процесс пробы (subprocess.Popen в gateway.oneshot), как в
tests/test_oneshot.py. Каждый отказ сверяется с ПРИЧИНОЙ (текст ошибки в
stderr) и с парой «тот же вход без нарушения проходит».
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gateway import oneshot  # noqa: E402
from tests.probe_m9_transport import _probe_payload  # noqa: E402

URL = "https://example.invalid/"
HTML = "<html><head><title>Example</title></head><body><h1>Hello</h1></body></html>"
SECRET = "s3cr@t"
EXPLICIT = "http://user1:s3cr%40t@proxy.invalid:8080"
EGRESS = "http://egress.invalid:3128"
SESSION = {"ua": "Mozilla/5.0 M26", "cookies": [{"name": "cf_clearance", "value": "v",
                                                  "domain": "example.invalid", "path": "/"}]}
FAILURES = []


def check(label, actual, expected):
    if actual != expected:
        FAILURES.append(f"{label}: ожидалось {expected!r}, получено {actual!r}")


class Spawns:
    """Popen stand-in: answers by provider, records env and argv of every probe."""

    def __init__(self, statuses=None, session_from=None):
        self.statuses = statuses or {}
        self.session_from = session_from
        self.calls = []

    def __call__(self, command, env=None, **kwargs):
        provider = env["ABG_PROVIDER"]
        self.calls.append((list(command), dict(env)))
        status = self.statuses.get(provider, 403)
        if provider == "curl_cffi" and "ABG_SESSION" in env:
            status = 200
        payload = _probe_payload(status=status, final_url=URL, html=HTML, text="Hello")
        if provider == self.session_from and env.get("ABG_SESSION_EXPORT") == "1":
            payload["session"] = SESSION
        proc = Mock(pid=4242, returncode=0)
        proc.communicate.return_value = (json.dumps(payload), "")
        return proc


def invoke(args, environ, spawns):
    base = {k: v for k, v in os.environ.items()
            if k not in ("ABG_PROXY", "ABG_EGRESS_PROXY", "ABG_SESSION_DIR")}
    out, err = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, {**base, **environ}, clear=True), patch.object(
            oneshot.subprocess, "Popen", side_effect=spawns), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = oneshot.main(args)
    return rc, out.getvalue(), err.getvalue()


def routes(out):
    try:
        return [(a["provider"], a["egress_profile"]) for a in json.loads(out)["attempts"]]
    except (ValueError, KeyError, TypeError):
        return f"not JSON: {out[:200]!r}"


def no_secret(label, rc_out_err, spawns):
    rc, out, err = rc_out_err
    blob = out + err + json.dumps([command for command, _ in spawns.calls])
    for needle in (SECRET, "s3cr%40t"):
        if needle in blob:
            FAILURES.append(f"{label}: пароль прокси в stdout/stderr/argv")


def ladder():
    s = Spawns()
    res = invoke([URL], {"ABG_PROXY": EXPLICIT}, s)
    check("explicit: rc", res[0], 1)
    check("explicit: маршруты", routes(res[1]),
          [("curl_cffi", "explicit"), ("patchright", "explicit"), ("scrapling", "explicit")])
    check("explicit: ABG_PROXY ступеней", [env.get("ABG_PROXY") for _, env in s.calls], [EXPLICIT] * 3)
    check("explicit: ABG_EGRESS_PROXY не уходит в пробу",
          [("ABG_EGRESS_PROXY" in env) for _, env in s.calls], [False] * 3)
    no_secret("explicit", res, s)

    s = Spawns()
    res = invoke([URL], {"ABG_PROXY": EXPLICIT, "ABG_EGRESS_PROXY": EGRESS}, s)
    check("explicit+egress: маршруты", routes(res[1]),
          [("curl_cffi", "explicit"), ("patchright", "explicit"), ("scrapling", "explicit"),
           ("curl_cffi", "proxy")])
    check("explicit+egress: ABG_PROXY ступеней", [env.get("ABG_PROXY") for _, env in s.calls],
          [EXPLICIT] * 3 + [EGRESS])

    s = Spawns()
    res = invoke([URL], {"ABG_PROXY": EGRESS, "ABG_EGRESS_PROXY": EGRESS}, s)
    check("одинаковые: запасная ступень не дублируется", routes(res[1]),
          [("curl_cffi", "explicit"), ("patchright", "explicit"), ("scrapling", "explicit")])

    s = Spawns()
    res = invoke([URL], {"ABG_EGRESS_PROXY": EGRESS}, s)
    check("только egress: прежняя лестница", routes(res[1]),
          [("curl_cffi", "direct"), ("patchright", "direct"), ("scrapling", "direct"),
           ("curl_cffi", "proxy")])
    check("только egress: ABG_PROXY ступеней", [env.get("ABG_PROXY") for _, env in s.calls],
          [None, None, None, EGRESS])

    for blank in ("", "   "):
        s = Spawns()
        res = invoke([URL], {"ABG_PROXY": blank}, s)
        check(f"ABG_PROXY={blank!r}: прямая лестница", routes(res[1]),
              [("curl_cffi", "direct"), ("patchright", "direct"), ("scrapling", "direct")])

    s = Spawns()
    res = invoke([URL], {"ABG_PROXY": "SOCKS5://s.invalid:1080",
                         "PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK": "1"}, s)
    check("явный socks5 уходит в пробы как socks5h", [env.get("ABG_PROXY") for _, env in s.calls],
          ["socks5h://s.invalid:1080"] * 3)
    check("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK не уходит в пробу",
          [("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK" in env) for _, env in s.calls],
          [False] * 3)

    s = Spawns()
    invoke([URL], {"ABG_EGRESS_PROXY": "socks5://e.invalid:1080"}, s)
    check("ABG_EGRESS_PROXY socks5 не переписывается", [env.get("ABG_PROXY") for _, env in s.calls],
          [None, None, None, "socks5://e.invalid:1080"])

    s = Spawns()
    res = invoke([URL], {"ABG_PROXY": "socks5://e.invalid:1080",
                         "ABG_EGRESS_PROXY": "socks5://e.invalid:1080"}, s)
    check("одинаковые socks5: сравнение до замены схемы", routes(res[1]),
          [("curl_cffi", "explicit"), ("patchright", "explicit"), ("scrapling", "explicit")])

    s = Spawns()
    flag = "http://flag.invalid:8080"
    res = invoke([URL, "--proxy", flag], {"ABG_PROXY": EXPLICIT}, s)
    check("--proxy сильнее ABG_PROXY", [env.get("ABG_PROXY") for _, env in s.calls], [flag] * 3)
    check("--proxy: маршруты", routes(res[1]),
          [("curl_cffi", "explicit"), ("patchright", "explicit"), ("scrapling", "explicit")])


def refusals():
    cases = [
        ("--proxy с паролем", [URL, "--proxy", "http://u:pw@flag.invalid:8080"], {},
         '{"error": "proxy_credentials_in_argv"}'),
        ("--proxy с одним логином", [URL, "--proxy", "http://u@flag.invalid:8080"], {},
         '{"error": "proxy_credentials_in_argv"}'),
        ("socks5 с паролем и браузерами", [URL], {"ABG_PROXY": "socks5://u:pw@s.invalid:1080"},
         '{"error": "proxy_unsupported"}'),
        ("socks5h с паролем и браузерами", [URL], {"ABG_PROXY": "socks5h://u:pw@s.invalid:1080"},
         '{"error": "proxy_unsupported"}'),
        ("ABG_PROXY ftp", [URL], {"ABG_PROXY": "ftp://p.invalid"}, '{"error": "invalid_request"}'),
        ("ABG_PROXY без схемы", [URL], {"ABG_PROXY": "p.invalid:8080"}, '{"error": "invalid_request"}'),
        ("ABG_PROXY битый порт", [URL], {"ABG_PROXY": "http://p.invalid:port"},
         '{"error": "invalid_request"}'),
        ("--proxy пустой", [URL, "--proxy", ""], {}, '{"error": "invalid_request"}'),
    ]
    for label, args, environ, error in cases:
        s = Spawns()
        rc, out, err = invoke(args, environ, s)
        check(f"{label}: rc/stdout/stderr", (rc, out, err), (2, "", error + "\n"))
        check(f"{label}: проб не запускали", len(s.calls), 0)
        for needle in ("pw", SECRET):
            if needle in err:
                FAILURES.append(f"{label}: пароль в stderr")
    passing = [
        ("--proxy без кредов", [URL, "--proxy", "http://flag.invalid:8080"], {}, 3),
        ("socks5 с паролем без браузеров", [URL, "--no-browser"],
         {"ABG_PROXY": "socks5://u:pw@s.invalid:1080"}, 1),
        ("socks5 без пароля с браузерами", [URL], {"ABG_PROXY": "socks5://s.invalid:1080"}, 3),
        ("https-прокси", [URL], {"ABG_PROXY": "https://u:pw@h.invalid:8443"}, 3),
    ]
    for label, args, environ, count in passing:
        s = Spawns()
        rc, out, err = invoke(args, environ, s)
        check(f"{label}: rc", (rc, err), (1, ""))
        check(f"{label}: все ступени через прокси", routes(out),
              [("curl_cffi", "explicit"), ("patchright", "explicit"),
               ("scrapling", "explicit")][:count])


def scope(identity):
    return "proxy-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def sessions():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "s"
        root.mkdir(mode=0o700)
        env = {"ABG_SESSION_DIR": str(root)}
        s = Spawns(statuses={"patchright": 200}, session_from="patchright")
        res = invoke([URL], {**env, "ABG_PROXY": EXPLICIT}, s)
        check("сессия: прогон через браузер", (res[0], routes(res[1])),
              (0, [("curl_cffi", "explicit"), ("patchright", "explicit")]))
        expected_dir = root / scope("http|proxy.invalid|8080|user1")
        check("сессия: файл в каталоге прокси", (expected_dir / "example.invalid.json").is_file(), True)
        check("сессия: прямой каталог не тронут", (root / "example.invalid.json").exists(), False)
        names = " ".join(str(p.relative_to(root)) for p in root.rglob("*"))
        for needle in ("s3cr", "user1", "proxy.invalid"):
            if needle in names:
                FAILURES.append(f"сессия: {needle!r} в именах файлов каталога сессий")

        def replayed(environ):
            s = Spawns()
            invoke([URL], {**env, **environ}, s)
            return "ABG_SESSION" in s.calls[0][1]

        check("сессия: тот же прокси переигрывает", replayed({"ABG_PROXY": EXPLICIT}), True)
        check("сессия: прямой маршрут не берёт сессию прокси", replayed({}), False)
        check("сессия: другой пароль — тот же выход",
              replayed({"ABG_PROXY": "http://user1:other@proxy.invalid:8080"}), True)
        check("сессия: другой логин — другой выход",
              replayed({"ABG_PROXY": "http://user2:s3cr%40t@proxy.invalid:8080"}), False)
        check("сессия: другой порт — другой выход",
              replayed({"ABG_PROXY": "http://user1:s3cr%40t@proxy.invalid:8081"}), False)

        s = Spawns()
        invoke([URL], {**env, "ABG_PROXY": "socks5://s.invalid:1080", "ABG_SESSION_DIR": str(root)},
               Spawns(statuses={"patchright": 200}, session_from="patchright"))
        check("сессия: scope по URL после замены socks5 -> socks5h",
              (root / scope("socks5h|s.invalid|1080|") / "example.invalid.json").is_file(), True)

        shared = Path(tmp) / "shared"
        shared.mkdir()
        shared.chmod(0o777)
        s = Spawns(statuses={"patchright": 200}, session_from="patchright")
        invoke([URL], {"ABG_SESSION_DIR": str(shared), "ABG_PROXY": EXPLICIT}, s)
        check("сессия: общий (0777) корень не используется", list(shared.rglob("*")), [])
        shared.chmod(0o700)
        s = Spawns(statuses={"patchright": 200}, session_from="patchright")
        invoke([URL], {"ABG_SESSION_DIR": str(shared), "ABG_PROXY": EXPLICIT}, s)
        check("сессия: тот же корень 0700 используется",
              (shared / scope("http|proxy.invalid|8080|user1") / "example.invalid.json").is_file(), True)

    fallback_never_touches_sessions()


def fallback_never_touches_sessions():
    from gateway.fetch import ProductFetcher
    from gateway.models import PlanStep
    import bench.runner.execute as execute

    class Store:
        def __init__(self):
            self.used = []

        def get(self, host):
            self.used.append("get")
            return dict(SESSION)

        def put(self, host, value):
            self.used.append("put")

        def drop(self, host, value=None):
            self.used.append("drop")

    calls = []

    def fetch_content(provider, **kwargs):
        calls.append(kwargs)
        return Mock(), None

    for step, wanted in ((PlanStep("curl_cffi", "proxy", "egress"), ({}, [])),
                         (PlanStep("curl_cffi", "explicit", "http"), ({"session"}, ["get"]))):
        store, calls[:] = Store(), []
        fetcher = ProductFetcher(URL, profiles={"explicit": EXPLICIT, "proxy": EGRESS},
                                 sessions=store, route="explicit")
        with patch.object(execute, "fetch_content", fetch_content):
            try:
                fetcher(step, 1000)
            except Exception:
                pass  # The Mock result may not satisfy the replay check; only the call matters.
        keys = set(calls[0]) & {"session", "on_session"} if calls else "no call"
        check(f"ProductFetcher {step.egress_profile}: сессия в вызове", keys, wanted[0] or set())
        check(f"ProductFetcher {step.egress_profile}: обращения к хранилищу", store.used[:1], wanted[1])


def load_probe():
    path = ROOT / "bench" / "providers" / "docker" / "probe.py"
    spec = importlib.util.spec_from_file_location("m26_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def probe_side():
    probe = load_probe()
    check("playwright_proxy socks5h -> socks5",
          probe.playwright_proxy("socks5h://h.invalid:1080"), {"server": "socks5://h.invalid:1080"})
    check("playwright_proxy http не меняется",
          probe.playwright_proxy("http://u:p%40ss@h.invalid:8080"),
          {"server": "http://h.invalid:8080", "username": "u", "password": "p@ss"})

    seen = []

    class FakeResponse:
        status_code, url, content, history, headers = 200, URL, b"<html>ok</html>", [], {}

    requests = types.SimpleNamespace(get=lambda url, **kw: seen.append(kw.get("proxy")) or FakeResponse(),
                                     Session=None)
    fake = types.ModuleType("curl_cffi")
    fake.requests = requests
    with patch.dict(sys.modules, {"curl_cffi": fake, "curl_cffi.requests": requests}):
        for given, sent in (("socks5://h.invalid:1080", "socks5://h.invalid:1080"),
                            ("socks5h://h.invalid:1080", "socks5h://h.invalid:1080"),
                            ("http://h.invalid:8080", "http://h.invalid:8080")):
            seen.clear()
            with patch.dict(os.environ, {"ABG_PROXY": given}):
                probe.CurlCffiAdapter().navigate(URL)
            check(f"curl_cffi proxy для {given} как есть", seen, [sent])

    with patch.dict(os.environ, {"ABG_PROXY": "http://u:p%40ss@h.invalid:8080"}):
        text = probe.redact("launch failed: password='p@ss' raw=p%40ss url=http://u:p%40ss@h.invalid:8080/")
        for needle in ("p@ss", "p%40ss"):
            if needle in text:
                FAILURES.append(f"redact оставил {needle!r}: {text!r}")
        check("redact без пароля не трогает текст", probe.redact("connection refused"),
              "connection refused")

        class Broken:
            version = "x"

            def start(self):
                raise RuntimeError("proxy auth failed for password p@ss")

            def close(self):
                pass

        payload = probe.run_probe("patchright", URL, None, mode="cold", content_only=True,
                                  adapter_factory=lambda name: Broken())
        if "p@ss" in json.dumps(payload):
            FAILURES.append("run_probe: пароль прокси в payload")
        check("run_probe: ошибка сохранила смысл", "proxy auth failed" in (payload.get("err") or ""), True)


def main():
    for part in (ladder, refusals, sessions, probe_side):
        try:
            part()
        except Exception as exc:  # A crash is a failed check, not a pass.
            FAILURES.append(f"{part.__name__}: исключение {type(exc).__name__}: {exc}")
    if FAILURES:
        print("\n".join(FAILURES))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
