"""Local HTTP fixtures shared by the M11 author tests."""
from contextlib import contextmanager
from http.client import HTTPConnection
import json
from threading import Thread
from bench.models import FetchResult, FailureReason as F, ChallengeType as C
from gateway.models import ProviderReply

URL = 'https://example.invalid/page'
TOKEN = 'test-only-token'


def reply(provider='curl', status=200, text='page', html='<p>page</p>'):
    return ProviderReply(FetchResult(provider, 'test', URL, URL, status, html,
                                    text, 0, 0, 0, 0, 0, 0, F.none, C.none))


@contextmanager
def serving(server):
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def request(addr, payload=None, *, method='POST', path='/v1/fetch', token=TOKEN):
    conn = HTTPConnection(*addr, timeout=8)
    try:
        conn.request(method, path, json.dumps(payload or {'url': URL}),
                     {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        res = conn.getresponse()
        return res.status, json.loads(res.read())
    finally:
        conn.close()
