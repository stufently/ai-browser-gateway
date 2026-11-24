#!/bin/bash
# Живой стенд M26: лестница one-shot через прокси. Владеет постановщик.
# Запуск из корня клона: bash docs/specs/checks/m26_stand.sh <сценарий>
#   сценарии: http | browser | deny | socks | compat | refuse
# Печатает `ok` и выходит 0 или печатает `FAIL: ...` и выходит 1.
#
# Сети обе --internal: one-shot сидит в сети int и до цели напрямую не
# достаёт (ни маршрута, ни DNS-имени), цель /ok|/deny|/js сидит только в ext,
# прокси (gost) — в обеих. Любой ответ цели one-shot'у — улика, что ступень
# шла через прокси. /gate сидит в int и отдаёт 200 только второму прокси (q).
# Код ветки монтируется поверх опубликованного образа 0.1.6, как в M25.
# Креды стенда — тестовые, только для этого локального gost.
set -euo pipefail

scenario="${1:?scenario}"
IMG=ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e
PY=python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
GOST=gogost/gost:3.3.3@sha256:f266f957c6e4f8d433ed23202a5745fa4969d08f3f0ef034fb9357345e16ad67
SECRET='p@ss1'
ENC='p%40ss1'
id="m26-$$-$RANDOM"
work=$(mktemp -d)

cleanup() {
    docker rm -f "$id-target" "$id-gate" "$id-p" "$id-q" "$id-run" >/dev/null 2>&1 || :
    docker network rm "$id-int" "$id-ext" >/dev/null 2>&1 || :
    rm -rf "$work"
}
trap cleanup EXIT

fail() { echo "FAIL: $*"; exit 1; }

docker network create --internal "$id-int" >/dev/null
docker network create --internal "$id-ext" >/dev/null
docker run -d --name "$id-target" --network "$id-ext" --user 1002:1002 \
    -v "$PWD/docs/specs/checks/m26_target.py:/t.py:ro" "$PY" python3 -u /t.py >/dev/null
docker run -d --name "$id-gate" --network "$id-int" --user 1002:1002 -e ALLOW_HOST="$id-q" \
    -v "$PWD/docs/specs/checks/m26_target.py:/t.py:ro" "$PY" python3 -u /t.py >/dev/null
docker run -d --name "$id-p" --network "$id-int" --user 1002:1002 "$GOST" \
    -L "http://u1:$ENC@:8080" -L "socks5://u1:$ENC@:1080" -L "http://:8081" -L "socks5://:1081" >/dev/null
docker run -d --name "$id-q" --network "$id-int" --user 1002:1002 "$GOST" -L "http://:8081" >/dev/null
docker network connect "$id-ext" "$id-p"
docker network connect "$id-ext" "$id-q"
for _ in $(seq 1 50); do
    if docker logs "$id-p" 2>&1 | grep -q '1081/tcp' && docker logs "$id-q" 2>&1 | grep -q '8081/tcp'; then
        break
    fi
    sleep 0.2
done

T="http://$id-target:8000"
G="http://$id-gate:8000"
P_AUTH="http://u1:$ENC@$id-p:8080"
P_OPEN="http://$id-p:8081"
Q_OPEN="http://$id-q:8081"

# oneshot <имя> <ABG_PROXY|-> <ABG_EGRESS_PROXY|-> <аргументы one-shot...>
# Значения прокси уходят в контейнер по ИМЕНИ (-e NAME), не в argv.
oneshot() {
    local name="$1" proxy="$2" egress="$3"
    shift 3
    local envs=()
    if [ "$proxy" != - ]; then export ABG_PROXY="$proxy"; envs+=(-e ABG_PROXY); else unset ABG_PROXY; fi
    if [ "$egress" != - ]; then export ABG_EGRESS_PROXY="$egress"; envs+=(-e ABG_EGRESS_PROXY); else unset ABG_EGRESS_PROXY; fi
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
    unset ABG_PROXY ABG_EGRESS_PROXY
    for f in json err top; do
        if grep -qF -e "$SECRET" -e "$ENC" "$work/$name.$f"; then
            fail "$name: пароль прокси в $f"
        fi
    done
}

rc_is() { [ "$(cat "$work/$1.rc")" = "$2" ] || fail "$1: rc=$(cat "$work/$1.rc"), ждали $2; stderr: $(head -c 300 "$work/$1.err")"; }

# steps <имя> <jq-массив [[provider, egress_profile, status, error_type], ...]>
steps() {
    local got
    got=$(jq -c '[.attempts[] | [.provider, .egress_profile, .status, .error_type]]' "$work/$1.json") \
        || fail "$1: stdout не JSON: $(head -c 300 "$work/$1.json")"
    [ "$got" = "$2" ] || fail "$1: attempts $got, ждали $2"
}

# proxy_sessions <контейнер-прокси> <хост:порт> [user] — число сессий к цели в логе gost.
proxy_sessions() {
    docker logs "$1" > "$work/gost.log" 2>&1
    grep '^{' "$work/gost.log" | jq -s --arg h "$2" --arg u "${3:-}" \
        '[.[] | select(.host == $h and (.cmd != null or .msg != null)
                 and ($u == "" or .user == $u)) | .sid] | unique | length'
}

case "$scenario" in
http)
    oneshot control - - "$T/ok"
    rc_is control 1
    steps control '[["curl_cffi","direct",null,"provider_error"]]'
    oneshot explicit "$P_AUTH" - "$T/ok"
    rc_is explicit 0
    jq -e '.ok and .provider == "curl_cffi" and (.content | contains("m26 marker text"))' \
        "$work/explicit.json" >/dev/null || fail "explicit: $(head -c 300 "$work/explicit.json")"
    steps explicit '[["curl_cffi","explicit",200,"none"]]'
    n=$(proxy_sessions "$id-p" "$id-target:8000" u1)
    [ "$n" -ge 1 ] || fail "http: в логе прокси нет сессии u1 к цели ($n)"
    ;;
browser)
    oneshot js "$P_AUTH" - "$T/js"
    rc_is js 0
    jq -e '.ok and .provider == "patchright" and (.content | contains("m26 rendered by script"))' \
        "$work/js.json" >/dev/null || fail "js: $(head -c 300 "$work/js.json")"
    steps js '[["curl_cffi","explicit",200,"content_missing"],["patchright","explicit",200,"none"]]'
    n=$(proxy_sessions "$id-p" "$id-target:8000" u1)
    [ "$n" -ge 2 ] || fail "browser: сессий u1 к цели в логе прокси $n, ждали >= 2"
    grep -qF -- "--proxy-server=http://$id-p:8080" "$work/js.top" \
        || fail "browser: в процессах контейнера не видно Chrome с --proxy-server"
    ;;
deny)
    oneshot deny "$P_AUTH" - "$T/deny"
    rc_is deny 1
    steps deny '[["curl_cffi","explicit",403,"http_403"],["patchright","explicit",403,"http_403"],["scrapling","explicit",403,"http_403"]]'
    jq -e '.error_type == "http_403" and .step == "human"' "$work/deny.json" >/dev/null \
        || fail "deny: $(head -c 300 "$work/deny.json")"
    n=$(proxy_sessions "$id-p" "$id-target:8000" u1)
    [ "$n" -ge 3 ] || fail "deny: сессий u1 к цели в логе прокси $n, ждали >= 3"
    grep -qF -- "--proxy-server=http://$id-p:8080" "$work/deny.top" \
        || fail "deny: в процессах контейнера не видно Chrome с --proxy-server"
    ;;
socks)
    for scheme in socks5h socks5; do
        oneshot "$scheme" "$scheme://$id-p:1081" - "$T/deny"
        rc_is "$scheme" 1
        steps "$scheme" '[["curl_cffi","explicit",403,"http_403"],["patchright","explicit",403,"http_403"],["scrapling","explicit",403,"http_403"]]'
    done
    ;;
compat)
    oneshot egress_only - "$Q_OPEN" "$G/gate"
    rc_is egress_only 0
    steps egress_only '[["curl_cffi","direct",403,"http_403"],["patchright","direct",403,"http_403"],["scrapling","direct",403,"http_403"],["curl_cffi","proxy",200,"none"]]'
    # 403 от /gate одинаков напрямую и через p: источник каждого запроса
    # этого прогона сверяется по журналу gate (адреса p и q в сети int).
    # Без явного прокси (egress_only выше) q берёт /gate, как до M26.
    p_ip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$id-int\").IPAddress}}" "$id-p")
    q_ip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$id-int\").IPAddress}}" "$id-q")
    [ -n "$p_ip" ] && [ -n "$q_ip" ] || fail "compat: нет адресов прокси в сети int"
    seen=$(docker logs "$id-gate" 2>&1 | grep -c '^TARGET ' || :)
    oneshot both "$P_AUTH" "$Q_OPEN" "$G/gate"
    rc_is both 1
    steps both '[["curl_cffi","explicit",403,"http_403"],["patchright","explicit",403,"http_403"],["scrapling","explicit",403,"http_403"]]'
    docker logs "$id-gate" 2>&1 | grep '^TARGET ' | tail -n +"$((seen + 1))" | grep ' /gate' | cut -d' ' -f2 > "$work/gate.src"
    from_p=$(grep -cxF "$p_ip" "$work/gate.src" || :)
    from_q=$(grep -cxF "$q_ip" "$work/gate.src" || :)
    other=$(grep -cvxF -e "$p_ip" -e "$q_ip" "$work/gate.src" || :)
    # Явный прокси отключает запасную попытку: через q к цели не ходит никто.
    [ "$from_p" -ge 3 ] && [ "$from_q" -eq 0 ] && [ "$other" -eq 0 ] \
        || fail "compat: источники /gate p=$from_p q=$from_q прочие=$other, ждали p>=3 q=0 прочие=0"
    oneshot same "$Q_OPEN" "$Q_OPEN" "$T/deny"
    rc_is same 1
    steps same '[["curl_cffi","explicit",403,"http_403"],["patchright","explicit",403,"http_403"],["scrapling","explicit",403,"http_403"]]'
    ;;
refuse)
    before=$(proxy_sessions "$id-p" "$id-target:8000")
    oneshot socks_auth "socks5://u1:$ENC@$id-p:1080" - "$T/ok"
    rc_is socks_auth 2
    [ "$(cat "$work/socks_auth.err")" = '{"error": "proxy_unsupported"}' ] \
        || fail "socks_auth: stderr $(head -c 300 "$work/socks_auth.err")"
    [ ! -s "$work/socks_auth.json" ] || fail "socks_auth: stdout не пуст"
    oneshot argv_creds - - "$T/ok" --proxy "http://u1:argvpw@$id-p:8080"
    rc_is argv_creds 2
    [ "$(cat "$work/argv_creds.err")" = '{"error": "proxy_credentials_in_argv"}' ] \
        || fail "argv_creds: stderr $(head -c 300 "$work/argv_creds.err")"
    after=$(proxy_sessions "$id-p" "$id-target:8000")
    [ "$before" = "$after" ] || fail "refuse: отказ всё-таки ходил через прокси ($before -> $after)"
    oneshot socks_auth_http "socks5://u1:$ENC@$id-p:1080" - "$T/ok" --no-browser
    rc_is socks_auth_http 0
    steps socks_auth_http '[["curl_cffi","explicit",200,"none"]]'
    oneshot argv_open "http://u1:wrong@$id-p:8080" - "$T/ok" --proxy "$P_OPEN"
    rc_is argv_open 0
    steps argv_open '[["curl_cffi","explicit",200,"none"]]'
    ;;
*)
    fail "неизвестный сценарий $scenario"
    ;;
esac
echo ok
