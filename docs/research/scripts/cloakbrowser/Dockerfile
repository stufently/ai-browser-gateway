# Evaluation image for docs/research/11-cloakbrowser.md. Build from the repo root:
#   docker build -f docs/research/scripts/cloakbrowser/Dockerfile -t abg-cloakbrowser:eval .
# Without a license key the wrapper downloads the free binary (Chromium 146).
# The binary is under CloakHQ's proprietary license: do not push this image.
FROM python:3.14-slim-bookworm

ENV HOME=/opt/home \
    CLOAKBROWSER_CACHE_DIR=/opt/cloak \
    CLOAKBROWSER_AUTO_UPDATE=false

RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb xauth tini \
 && mkdir -p /tmp/.X11-unix /opt/home /opt/cloak \
 && chmod 1777 /tmp/.X11-unix \
 && chmod 0777 /opt/home \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "cloakbrowser==0.5.12" \
 && playwright install-deps chromium \
 && python3 -c "from cloakbrowser import ensure_binary; print(ensure_binary())" \
 && rm -f /opt/cloak/.welcome_shown \
 && chmod -R a+rwX /opt/home /opt/cloak \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/abg
COPY bench/providers/docker/probe.py docs/research/scripts/cloakbrowser/eval_probe.py /opt/abg/
RUN chmod a+rX /opt/abg/*.py
ENV ABG_PROVIDER=cloakbrowser
ENTRYPOINT ["/usr/bin/tini","-g","--","xvfb-run","-a","-s","-screen 0 1920x1080x24","python3","/opt/abg/eval_probe.py"]
