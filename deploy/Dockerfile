FROM python:3.14.7-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
COPY --from=docker:29.8.0-cli@sha256:eccaacfeed644c7de222ff047483568cb988dde95476fbaaf10ea2d04921bb66 \
    /usr/local/bin/docker /usr/local/bin/docker
USER 1002:1002
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1
WORKDIR /tmp
CMD ["python3", "-m", "gateway.service"]
