#!/bin/bash
# Живой стенд M29: пароль прокси не попадает в окружение процессов браузера.
# Владеет постановщик.
# Запуск из корня клона: bash docs/specs/checks/m29_stand.sh <провайдер>
#   провайдеры: patchright | scrapling
# Печатает `ok` и выходит 0 или печатает `FAIL: ...` и выходит 1.
#
# Раскладка как в m27_stand.sh: обе сети --internal, проба в int, цель
# только в ext, прокси p (gost, http с паролем) в обеих. Проба зовётся
# напрямую (xvfb-run python3 probe.py), код ветки монтируется поверх
# опубликованного образа 0.1.8. Пока проба жива, сканер внутри контейнера
# раз в 0,3 с читает /proc/*/environ и пишет по строке на процесс:
# pid, начало cmdline, LEAK|clean. Секрет сканер берёт из своего окружения,
# в argv его нет. Судятся только процессы браузера: драйвер (node) и
# Chrome; сама проба, xvfb-run и Xvfb получили ABG_PROXY от docker и вне
# скоупа вехи. Креды стенда — тестовые, только для этого локального gost.
set -euo pipefail

provider="${1:?provider}"
case "$provider" in patchright|scrapling) ;; *) echo "FAIL: неизвестный провайдер $provider"; exit 1 ;; esac
IMG=ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:59031eef8b63c73cc6892178d37e2cea83e7b67db27268be76db361db180dfa5
PY=python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
GOST=gogost/gost:3.3.3@sha256:f266f957c6e4f8d433ed23202a5745fa4969d08f3f0ef034fb9357345e16ad67
SECRET='p@ss1'
ENC='p%40ss1'
B64='dTE6cEBzczE='
id="m29-$$-$RANDOM"
work=$(mktemp -d)
chmod 0755 "$work"

cleanup() {
    docker rm -f "$id-target" "$id-p" "$id-run" >/dev/null 2>&1 || :
    docker network rm "$id-int" "$id-ext" >/dev/null 2>&1 || :
    rm -rf "$work"
}
trap cleanup EXIT

fail() { echo "FAIL: $*"; exit 1; }

A="$id-a"
docker network create --internal "$id-int" >/dev/null
docker network create --internal "$id-ext" >/dev/null
docker run -d --name "$id-target" --network "$id-ext" --network-alias "$A" \
    --user 1002:1002 -v "$PWD/docs/specs/checks/m27_target.py:/t.py:ro" "$PY" python3 -u /t.py >/dev/null
docker run -d --name "$id-p" --network "$id-int" --user 1002:1002 "$GOST" \
    -L "http://u1:$ENC@:8080" >/dev/null
docker network connect "$id-ext" "$id-p"
for _ in $(seq 1 50); do
    if docker logs "$id-p" 2>&1 | grep -q '8080/tcp'; then
        break
    fi
    sleep 0.2
done

SCAN='
import os
me, s, s2 = os.getpid(), os.environ["S"].encode(), os.environ["S2"].encode()
for name in os.listdir("/proc"):
    if not name.isdigit() or int(name) == me:
        continue
    try:
        with open(f"/proc/{name}/cmdline", "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")[:160]
        with open(f"/proc/{name}/environ", "rb") as f:
            env = f.read()
    except OSError:
        continue
    print(name, cmd.replace("\t", " "), "LEAK" if s in env or s2 in env else "clean", sep="\t")
'

# Браузер живёт около секунды; если сканер не застал Chrome или драйвер,
# прогон повторяется, до трёх раз.
run_once() {
export ABG_PROXY="http://u1:$ENC@$id-p:8080"
docker run --name "$id-run" --init --rm --network "$id-int" --user 1002:1002 --shm-size=1g \
    -e ABG_PROXY -e ABG_PROVIDER="$provider" \
    -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro \
    --entrypoint xvfb-run "$IMG" -a -s "-screen 0 1920x1080x24" \
    python3 /opt/abg/probe.py "http://$A:8000/js" --content-only --include-content --budget-ms 30000 \
    > "$work/probe.json" 2> "$work/probe.err" &
pid=$!
unset ABG_PROXY
while kill -0 "$pid" 2>/dev/null; do
    docker exec -e S="$SECRET" -e S2="$ENC" "$id-run" python3 -c "$SCAN" >> "$work/scan.tsv" 2>/dev/null || :
    sleep 0.3
done
wait "$pid" || :

for f in probe.json probe.err scan.tsv; do
    if grep -qF -e "$SECRET" -e "$ENC" -e "$B64" "$work/$f"; then
        fail "пароль прокси в $f"
    fi
done
jq -e '.status == 200 and (.text | contains("m26 rendered by script"))' "$work/probe.json" >/dev/null \
    || fail "проба не прочитала страницу через прокси: $(head -c 400 "$work/probe.json") $(tail -c 300 "$work/probe.err")"
awk -F'\t' '$2 ~ /(chrome|chromium|headless_shell)/' "$work/scan.tsv" > "$work/chrome.tsv"
awk -F'\t' '$2 ~ /(^|\/)node /' "$work/scan.tsv" > "$work/driver.tsv"
}

: > "$work/scan.tsv"
for _ in 1 2 3; do
    run_once
    if [ -s "$work/chrome.tsv" ] && [ -s "$work/driver.tsv" ]; then
        break
    fi
done

# Процессы браузера: Chrome (chrome/chromium/headless_shell) и драйвер (node).
[ -s "$work/chrome.tsv" ] || fail "сканер не увидел ни одного процесса Chrome"
[ -s "$work/driver.tsv" ] || fail "сканер не увидел процесса драйвера (node)"
if grep -q $'\tLEAK$' "$work/chrome.tsv" "$work/driver.tsv"; then
    fail "пароль прокси в окружении процессов браузера: $(grep -h $'\tLEAK$' "$work/chrome.tsv" "$work/driver.tsv" | cut -f1,2 | sort -u -k2 | head -5 | tr '\n' ';')"
fi
echo ok
