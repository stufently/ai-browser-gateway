#!/usr/bin/env bash
# Стенд M28: /health и healthcheck compose против настоящего docker-сокета хоста.
# Использование: bash docs/specs/checks/m28_stand.sh <present|absent>  ->  `ok`
# Рантайм-образ сервиса (python 3.14.7 + docker CLI 29.8.0, собран из
# deploy/Dockerfile) берётся по ID: тег меняется с каждым релизом. Контейнер
# стенда без сети, только чтение клона; из docker он лишь читает список образов.
set -euo pipefail
scenario=${1:?usage: m28_stand.sh present|absent}
runtime=sha256:157e819f2a17b815a673ba2f2f7afcf68ea5b81134ed9b74edba6bf7bfb0de9c
root=$(cd "$(dirname "$0")/../../.." && pwd)
gid=$(stat -c %g /var/run/docker.sock)
exec docker run --rm --network none --user 1002:1002 --group-add "$gid" \
  --read-only --tmpfs /tmp -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work -e M28_SCENARIO="$scenario" \
  -v "$root":/work:ro -v /var/run/docker.sock:/var/run/docker.sock -w /work \
  "$runtime" python3 docs/specs/checks/m28_stand.py
