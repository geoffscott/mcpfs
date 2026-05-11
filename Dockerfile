# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip build && python -m build --wheel


FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

# Patch system packages, then strip apt to keep the image small.
RUN apt-get update \
 && apt-get -y upgrade \
 && apt-get -y --no-install-recommends install ca-certificates tini \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Run as a non-root, non-login user with no shell.
RUN groupadd --system --gid 10001 mcpfs \
 && useradd  --system --uid 10001 --gid mcpfs \
             --home-dir /nonexistent --no-create-home \
             --shell /usr/sbin/nologin mcpfs

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["mcpfs"]
