#!/bin/bash
# Живой стенд M27: браузеры ходят к прокси с паролем через локальный релей
# без кредов внутри процесса пробы. Владеет постановщик.
# Запуск из корня клона: bash docs/specs/checks/m27_stand.sh <сценарий>
#   сценарии: relay | frame | sw | socks | auth | tls | refuse
# Печатает `ok` и выходит 0 или печатает `FAIL: ...` и выходит 1.
#
# Раскладка как в m26_stand.sh: сети обе --internal, one-shot в int, цель
# только в ext (два имени — A и B, разные сайты для Chromium), прокси p
# (gost) в обеих. Вторая цель (sw) живёт в сетевом пространстве p и видна
# прокси как localhost:8000 — так у service worker есть secure context.
# Код ветки монтируется поверх опубликованного образа 0.1.7.
# Креды стенда — тестовые, только для этого локального gost.
set -euo pipefail

scenario="${1:?scenario}"
IMG=ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:2e4e57dec5f4399f3cfcbad8a89d883c8f6c63aa265b6a026aaaf56b023246e0
PY=python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
GOST=gogost/gost:3.3.3@sha256:f266f957c6e4f8d433ed23202a5745fa4969d08f3f0ef034fb9357345e16ad67
SECRET='p@ss1'
ENC='p%40ss1'
WRONG='wr0ngpw'
# base64 от "u1:p@ss1" и "u1:wr0ngpw" — так пароль выглядит в Proxy-Authorization.
B64='dTE6cEBzczE='
B64_WRONG='dTE6d3Iwbmdwdw=='
id="m27-$$-$RANDOM"
work=$(mktemp -d)
chmod 0755 "$work"

cleanup() {
    docker rm -f "$id-target" "$id-sw" "$id-p" "$id-run" >/dev/null 2>&1 || :
    docker network rm "$id-int" "$id-ext" >/dev/null 2>&1 || :
    rm -rf "$work"
}
trap cleanup EXIT

fail() { echo "FAIL: $*"; exit 1; }

A="$id-a"
B="$id-b"
docker network create --internal "$id-int" >/dev/null
docker network create --internal "$id-ext" >/dev/null
docker run -d --name "$id-target" --network "$id-ext" --network-alias "$A" --network-alias "$B" \
    --user 1002:1002 -v "$PWD/docs/specs/checks/m27_target.py:/t.py:ro" "$PY" python3 -u /t.py >/dev/null
gost_args=(-L "http://u1:$ENC@:8080" -L "socks5://u1:$ENC@:1080")
gost_mounts=()
if [ "$scenario" = tls ]; then
    # CA и сертификат прокси на имя $id-p; one-shot доверяет CA через SSL_CERT_FILE.
    mkdir -p "$work/tls"
    chmod 0755 "$work/tls"
    docker run --rm --user 1002:1002 --network none -v "$work/tls":/c --entrypoint sh "$IMG" -c "
        cd /c && openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.pem -days 2 -subj /CN=m27-ca -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign 2>/dev/null &&
        openssl req -newkey rsa:2048 -nodes -keyout key.pem -out p.csr -subj /CN=$id-p 2>/dev/null &&
        printf 'subjectAltName=DNS:%s\nauthorityKeyIdentifier=keyid,issuer\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' $id-p > ext.cnf &&
        openssl x509 -req -in p.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out cert.pem -days 2 -extfile ext.cnf 2>/dev/null &&
        chmod 0644 ca.pem cert.pem key.pem" || fail "tls: не выпустили сертификат"
    gost_args+=(-L "http+tls://u1:$ENC@:8443?certFile=/c/cert.pem&keyFile=/c/key.pem")
    gost_mounts=(-v "$work/tls":/c:ro)
fi
docker run -d --name "$id-p" --network "$id-int" --user 1002:1002 "${gost_mounts[@]}" "$GOST" \
    "${gost_args[@]}" >/dev/null
docker network connect "$id-ext" "$id-p"
docker run -d --name "$id-sw" --network "container:$id-p" --user 1002:1002 \
    -v "$PWD/docs/specs/checks/m27_target.py:/t.py:ro" "$PY" python3 -u /t.py >/dev/null
for _ in $(seq 1 50); do
    if docker logs "$id-p" 2>&1 | grep -q '1080/tcp'; then
        break
    fi
    sleep 0.2
done

T="http://$A:8000"
P_AUTH="http://u1:$ENC@$id-p:8080"
S_AUTH="socks5://u1:$ENC@$id-p:1080"

# oneshot <имя> <ABG_PROXY|-> <аргументы one-shot...>
# Прокси уходит в контейнер по ИМЕНИ (-e ABG_PROXY), не в argv.
oneshot() {
    local name="$1" proxy="$2"
    shift 2
    local envs=()
    if [ "$proxy" != - ]; then export ABG_PROXY="$proxy"; envs+=(-e ABG_PROXY); else unset ABG_PROXY; fi
    if [ -n "${CA_FILE:-}" ]; then envs+=(-e SSL_CERT_FILE=/ca/ca.pem -v "$CA_FILE":/ca/ca.pem:ro); fi
    : > "$work/$name.top"
    docker run --name "$id-run" --rm --network "$id-int" --user 1002:1002 --shm-size=1g \
        "${envs[@]}" \
        -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro \
        -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro \
        "$IMG" "$@" > "$work/$name.json" 2> "$work/$name.err" &
    local pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        docker top "$id-run" -o pid,args >> "$work/$name.top" 2>/dev/null || :
        sleep 0.2
    done
    local rc=0
    wait "$pid" || rc=$?
    echo "$rc" > "$work/$name.rc"
    unset ABG_PROXY
    for f in json err top; do
        if grep -qF -e "$SECRET" -e "$ENC" -e "$WRONG" -e "$B64" -e "$B64_WRONG" "$work/$name.$f"; then
            fail "$name: пароль прокси в $f"
        fi
    done
}

# probe <имя> <ABG_PROXY> <провайдер> <url> — проба напрямую, как её зовёт one-shot.
probe() {
    local name="$1"
    export ABG_PROXY="$2"
    docker run --init --rm --network "$id-int" --user 1002:1002 --shm-size=1g \
        -e ABG_PROXY -e ABG_PROVIDER="$3" \
        -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro \
        --entrypoint xvfb-run "$IMG" -a -s "-screen 0 1920x1080x24" \
        python3 /opt/abg/probe.py "$4" --content-only --include-content --budget-ms 30000 \
        > "$work/$name.json" 2> "$work/$name.err" || :
    unset ABG_PROXY
    for f in json err; do
        if grep -qF -e "$SECRET" -e "$ENC" -e "$WRONG" -e "$B64" -e "$B64_WRONG" "$work/$name.$f"; then
            fail "$name: пароль прокси в $f"
        fi
    done
}

probe_err() {
    local got
    got=$(jq -r '.err' "$work/$1.json") || fail "$1: stdout пробы не JSON: $(head -c 300 "$work/$1.json")"
    [ "$got" = "$2" ] || fail "$1: err «$got», ждали «$2»"
}

rc_is() { [ "$(cat "$work/$1.rc")" = "$2" ] || fail "$1: rc=$(cat "$work/$1.rc"), ждали $2; stderr: $(head -c 300 "$work/$1.err")"; }

# steps <имя> <jq-массив [[provider, egress_profile, status, error_type], ...]>
steps() {
    local got
    got=$(jq -c '[.attempts[] | [.provider, .egress_profile, .status, .error_type]]' "$work/$1.json") \
        || fail "$1: stdout не JSON: $(head -c 300 "$work/$1.json")"
    [ "$got" = "$2" ] || fail "$1: attempts $got, ждали $2"
}

# content <имя> <провайдер> <текст> — успех, провайдер и текст в content.
content() {
    jq -e --arg p "$2" --arg t "$3" '.ok and .provider == $p and (.content | contains($t))' \
        "$work/$1.json" >/dev/null || fail "$1: $(head -c 400 "$work/$1.json")"
}

# relay_only <имя> — Chrome запущен с релеем на loopback и ни разу не видел адрес p.
relay_only() {
    grep -qE -- '--proxy-server=http://127\.0\.0\.1:[0-9]+( |$)' "$work/$1.top" \
        || fail "$1: в процессах нет Chrome с --proxy-server=http://127.0.0.1:<порт>"
    if grep -qF -- "--proxy-server=http://$id-p" "$work/$1.top" \
        || grep -qF -- "--proxy-server=socks5://$id-p" "$work/$1.top"; then
        fail "$1: Chrome запущен прямо на прокси p"
    fi
}

# proxy_sessions <хост:порт> [user] — число сессий к цели в логе gost.
proxy_sessions() {
    docker logs "$id-p" > "$work/gost.log" 2>&1
    grep '^{' "$work/gost.log" | jq -s --arg h "$1" --arg u "${2:-}" \
        '[.[] | select(.host == $h and (.cmd != null or .msg != null)
                 and ($u == "" or .user == $u)) | .sid] | unique | length'
}

# hits <контейнер> <путь> — число запросов цели по пути.
hits() { docker logs "$1" 2>&1 | grep -c "^TARGET [^ ]* $2 " || :; }

case "$scenario" in
relay)
    oneshot js "$P_AUTH" "$T/js"
    rc_is js 0
    content js patchright "m26 rendered by script"
    steps js '[["curl_cffi","explicit",200,"content_missing"],["patchright","explicit",200,"none"]]'
    relay_only js
    n=$(proxy_sessions "$A:8000" u1)
    [ "$n" -ge 2 ] || fail "relay: сессий u1 к цели в логе прокси $n, ждали >= 2"
    oneshot deny "$P_AUTH" "$T/deny"
    rc_is deny 1
    steps deny '[["curl_cffi","explicit",403,"http_403"],["patchright","explicit",403,"http_403"],["scrapling","explicit",403,"http_403"]]'
    relay_only deny
    ;;
frame)
    oneshot frame "$P_AUTH" "$T/frame?b=$B" --expected-text "m27 iframe text"
    rc_is frame 0
    content frame patchright "m27 iframe text"
    steps frame '[["curl_cffi","explicit",200,"content_missing"],["patchright","explicit",200,"none"]]'
    relay_only frame
    [ "$(hits "$id-target" /inner)" -ge 1 ] || fail "frame: iframe не запрашивался"
    n=$(proxy_sessions "$B:8000" u1)
    [ "$n" -ge 1 ] || fail "frame: в логе прокси нет сессии u1 к хосту B ($n)"
    ;;
sw)
    oneshot sw "$P_AUTH" "http://localhost:8000/sw" --expected-text "m27 service worker text"
    rc_is sw 0
    content sw patchright "m27 service worker text"
    relay_only sw
    jq -e '.attempts[-1] | .provider == "patchright" and .egress_profile == "explicit" and .status == 200 and .error_type == "none"' \
        "$work/sw.json" >/dev/null || fail "sw: последняя ступень $(jq -c '.attempts' "$work/sw.json")"
    [ "$(hits "$id-sw" /sw-backend)" -ge 1 ] || fail "sw: воркер не ходил в /sw-backend"
    [ "$(hits "$id-sw" /via-sw)" -eq 0 ] || fail "sw: /via-sw ушёл в сеть мимо воркера"
    ;;
socks)
    for scheme in socks5 socks5h; do
        oneshot "$scheme-js" "$scheme://u1:$ENC@$id-p:1080" "$T/js"
        rc_is "$scheme-js" 0
        content "$scheme-js" patchright "m26 rendered by script"
        steps "$scheme-js" '[["curl_cffi","explicit",200,"content_missing"],["patchright","explicit",200,"none"]]'
        relay_only "$scheme-js"
    done
    before=$(proxy_sessions "$A:8000" u1)
    oneshot socks-deny "$S_AUTH" "$T/deny"
    rc_is socks-deny 1
    steps socks-deny '[["curl_cffi","explicit",403,"http_403"],["patchright","explicit",403,"http_403"],["scrapling","explicit",403,"http_403"]]'
    relay_only socks-deny
    after=$(proxy_sessions "$A:8000" u1)
    [ "$((after - before))" -ge 3 ] || fail "socks: сессий u1 к цели $before -> $after, ждали прирост >= 3"
    ;;
auth)
    oneshot a401 "$P_AUTH" "$T/authpage?b=$B" --expected-text "m27 auth page"
    rc_is a401 0
    content a401 patchright "m27 auth page"
    content a401 patchright "auth required"
    steps a401 '[["curl_cffi","explicit",200,"content_missing"],["patchright","explicit",200,"none"]]'
    relay_only a401
    total=$(hits "$id-target" /auth401)
    clean=$(docker logs "$id-target" 2>&1 | grep -c '^TARGET [^ ]* /auth401 authz=0$' || :)
    [ "$total" -ge 2 ] && [ "$total" = "$clean" ] \
        || fail "auth: запросов /auth401 $total, без Authorization $clean"
    # Главный документ с 401 Basic: страница читается (CancelAuth), как на BASE.
    for provider in patchright scrapling; do
        probe "p-$provider-401" "$P_AUTH" "$provider" "$T/auth401"
        jq -e '.status == 401 and .err == "" and (.text | contains("auth required"))' \
            "$work/p-$provider-401.json" >/dev/null \
            || fail "auth: $provider на 401 Basic: $(jq -c '{status,err}' "$work/p-$provider-401.json")"
    done
    clean=$(docker logs "$id-target" 2>&1 | grep -c '^TARGET [^ ]* /auth401 authz=0$' || :)
    [ "$(hits "$id-target" /auth401)" = "$clean" ] || fail "auth: Authorization ушёл сайту"
    # Неверный пароль у http-прокси: curl_cffi видит 407 и лестница сдаётся
    # на нём (поведение до M27); у SOCKS5 curl_cffi падает, и браузеры
    # получают отказ релея как provider_error.
    oneshot wrong_http "http://u1:$WRONG@$id-p:8080" "$T/ok"
    rc_is wrong_http 1
    steps wrong_http '[["curl_cffi","explicit",407,"content_mismatch"]]'
    oneshot wrong_socks "socks5://u1:$WRONG@$id-p:1080" "$T/ok"
    rc_is wrong_socks 1
    steps wrong_socks '[["curl_cffi","explicit",null,"provider_error"]]'
    # До браузеров лестница с неверным паролем не доходит — их отказ
    # проверяется пробой напрямую, причина сверяется по тексту err.
    for provider in patchright scrapling; do
        probe "p-$provider-http" "http://u1:$WRONG@$id-p:8080" "$provider" "$T/ok"
        probe_err "p-$provider-http" "ProxyRelayError: upstream proxy rejected credentials (HTTP 407)"
        probe "p-$provider-socks" "socks5h://u1:$WRONG@$id-p:1080" "$provider" "$T/ok"
        probe_err "p-$provider-socks" "ProxyRelayError: upstream proxy rejected credentials (SOCKS5)"
    done
    [ "$(hits "$id-target" /ok)" -eq 0 ] || fail "auth: с неверным паролем цель получила запрос"
    ;;
tls)
    CA_FILE="$work/tls/ca.pem"
    oneshot tls "https://u1:$ENC@$id-p:8443" "$T/js"
    rc_is tls 0
    content tls patchright "m26 rendered by script"
    steps tls '[["curl_cffi","explicit",200,"content_missing"],["patchright","explicit",200,"none"]]'
    relay_only tls
    # CONNECT поверх TLS до прокси: настоящий _ProxyRelay пробы, сырой
    # туннель к цели и HTTP-запрос внутри него (https-цели Chromium ходят так же).
    export ABG_PROXY="https://u1:$ENC@$id-p:8443"
    docker run --rm --network "$id-int" --user 1002:1002 -e ABG_PROXY -e T_HOST="$A" \
        -e SSL_CERT_FILE=/ca/ca.pem -v "$CA_FILE":/ca/ca.pem:ro \
        -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro \
        --entrypoint python3 "$IMG" -c '
import os, socket, sys
sys.path.insert(0, "/opt/abg")
import probe
relay = probe._ProxyRelay(os.environ["ABG_PROXY"])
port = int(relay.start().rsplit(":", 1)[1])
host = os.environ["T_HOST"]
s = socket.create_connection(("127.0.0.1", port), 10)
s.sendall(f"CONNECT {host}:8000 HTTP/1.1\r\nHost: {host}:8000\r\n\r\n".encode())
head = s.recv(4096)
s.sendall(f"GET /ok HTTP/1.1\r\nHost: {host}:8000\r\nConnection: close\r\n\r\n".encode())
body = b""
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    body += chunk
relay.close()
print(head.split(b"\r\n")[0].decode(), b"m26 marker text" in body)
' > "$work/tunnel.out" 2> "$work/tunnel.err" || :
    unset ABG_PROXY
    [ "$(cat "$work/tunnel.out")" = "HTTP/1.1 200 Connection established True" ] \
        || fail "tls: туннель через https-прокси: $(head -c 300 "$work/tunnel.out") $(head -c 300 "$work/tunnel.err")"
    CA_FILE=
    # Без доверия к CA (SSL_CERT_FILE не задан) релей отказывает по TLS.
    probe p-tls-untrusted "https://u1:$ENC@$id-p:8443" patchright "$T/js"
    probe_err p-tls-untrusted "ProxyRelayError: upstream proxy TLS failed"
    ;;
refuse)
    before=$(proxy_sessions "$A:8000")
    oneshot argv_creds - "$T/ok" --proxy "http://u1:argvpw@$id-p:8080"
    rc_is argv_creds 2
    [ "$(cat "$work/argv_creds.err")" = '{"error": "proxy_credentials_in_argv"}' ] \
        || fail "argv_creds: stderr $(head -c 300 "$work/argv_creds.err")"
    [ ! -s "$work/argv_creds.json" ] || fail "argv_creds: stdout не пуст"
    after=$(proxy_sessions "$A:8000")
    [ "$before" = "$after" ] || fail "refuse: отказ всё-таки ходил через прокси ($before -> $after)"
    ;;
*)
    fail "неизвестный сценарий $scenario"
    ;;
esac
echo ok
