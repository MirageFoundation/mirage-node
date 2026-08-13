# Multi-stage Dockerfile for Mirage production deployment
# Stage 0: Build Caddy with rate-limit plugin
FROM caddy:builder AS caddy-builder

RUN xcaddy build \
    --output /usr/bin/caddy \
    --with github.com/mholt/caddy-ratelimit \
    --with github.com/WeidiDeng/caddy-cloudflare-ip

# Stage 1: Build frontend, install dependencies
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/usr/local/go/bin:$PATH
ENV PIP_ROOT_USER_ACTION=ignore

# Switch to the Azure-hosted Ubuntu mirror — the default archive.ubuntu.com
# round-robin frequently serves out-of-sync indexes (size/hash mismatch) which
# kill builds. Azure's mirror is consistent. Also enable apt retries.
RUN sed -i 's@//archive.ubuntu.com@//azure.archive.ubuntu.com@g; s@//security.ubuntu.com@//azure.archive.ubuntu.com@g' /etc/apt/sources.list.d/ubuntu.sources \
 && echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries \
 && echo 'Acquire::http::Timeout "30";' >> /etc/apt/apt.conf.d/80-retries \
 && echo 'Acquire::https::Timeout "30";' >> /etc/apt/apt.conf.d/80-retries

# Install build dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 from NodeSource. Verify the install actually pulled
# v20.x (npm is bundled), so a silent fallback to Ubuntu's nodejs (which on
# 24.04 ships without npm) fails the build instead of breaking later steps.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update \
 && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && node --version | grep -q '^v20\.' \
 && npm --version
## Refresh npm, but pin to the 11.x line: npm@latest is now 12.x, which dropped
## Node 20 (requires node >=22.22) and hard-fails EBADENGINE on our Node 20 base.
## npm 11 supports node ^20.17, so this stays current without bumping Node.
RUN npm i -g npm@11 --no-audit --no-fund

WORKDIR /opt/mirage

# Copy dependency files first for better layer caching
COPY web/backend/requirements.txt /opt/mirage/web/backend/requirements.txt
COPY web/frontend/package.json web/frontend/package-lock.json /opt/mirage/web/frontend/

# Install Python dependencies
RUN pip3 install --break-system-packages --root-user-action=ignore --no-cache-dir -r /opt/mirage/web/backend/requirements.txt

# Install frontend dependencies
WORKDIR /opt/mirage/web/frontend
RUN npm ci --no-audit --no-fund --legacy-peer-deps

# Copy frontend sources only (avoid invalidating cache on unrelated changes)
COPY web/frontend/ /opt/mirage/web/frontend/

# FAQ markdown is embedded into the frontend at build time: vite.config.js
# reads ../../docs/FAQ.md (resolves to /opt/mirage/docs/FAQ.md). It must exist
# before `npm run build` or the React build fails with ENOENT.
COPY docs/FAQ.md /opt/mirage/docs/FAQ.md

# Verify vendored PoW assets match the locked argon2-browser package
RUN npm run check:pow-assets

# Build frontend (version comes from build args provided by deploy script)
ARG GIT_BRANCH
ARG GIT_HASH
ENV BROWSERSLIST_IGNORE_OLD_DATA=true
RUN VITE_APP_VERSION="${GIT_BRANCH:-?} (${GIT_HASH:-?})" VITE_API_BASE=/api npm run build
RUN npm run check:bundle-policy

# Copy runtime files after frontend build so backend/go changes don't force a React rebuild
WORKDIR /opt/mirage
COPY blockchain/bin/miraged /opt/mirage/blockchain/bin/miraged
COPY blockchain/bin/compact-db /opt/mirage/blockchain/bin/compact-db
# Proto sources, not Go source: test_blockchain_params compares them against
# shared/datatypes.py, and the suites only run inside this container.
COPY blockchain/proto/ /opt/mirage/blockchain/proto/
COPY scripts/ /opt/mirage/scripts/
COPY web/backend/ /opt/mirage/web/backend/
COPY indexer/ /opt/mirage/indexer/
COPY shared/ /opt/mirage/shared/
COPY tests/ /opt/mirage/tests/
COPY deploy/ /opt/mirage/deploy/

## Note: We trust upstream build step to produce /opt/mirage/blockchain/bin/miraged

# Stage 2: Minimal runtime image
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/opt/mirage/blockchain/bin:/usr/local/bin:/usr/bin:/bin
ENV PYTHONPATH=/opt/mirage
ENV BACKEND_HOST=127.0.0.1
ENV BACKEND_PORT=5000
ENV TERM=xterm-256color
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# Switch to the Azure-hosted Ubuntu mirror (consistent indexes, no mirror-sync
# size/hash mismatches like archive.ubuntu.com regularly serves). Also enable
# apt retries.
RUN sed -i 's@//archive.ubuntu.com@//azure.archive.ubuntu.com@g; s@//security.ubuntu.com@//azure.archive.ubuntu.com@g' /etc/apt/sources.list.d/ubuntu.sources \
 && echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries \
 && echo 'Acquire::http::Timeout "30";' >> /etc/apt/apt.conf.d/80-retries \
 && echo 'Acquire::https::Timeout "30";' >> /etc/apt/apt.conf.d/80-retries

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    postgresql \
    postgresql-client \
    postgresql-common \
    tmux \
    micro \
    tree \
    curl \
    ca-certificates \
    coreutils \
    jq \
    procps \
    dnsutils \
    cronolog \
    htop \
    less \
    netcat-openbsd \
    iputils-ping \
    openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

# Add shell aliases
RUN echo "alias m='micro'" >> /etc/bash.bashrc

# Install Caddy (for deps), then overwrite with custom binary that has rate-limit plugin
RUN apt-get update && apt-get install -y caddy && rm -rf /var/lib/apt/lists/*
COPY --from=caddy-builder /usr/bin/caddy /usr/bin/caddy

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/dist-packages /usr/local/lib/python3.12/dist-packages

# Copy only runtime files (not source code)
WORKDIR /opt/mirage

# Copy compiled binaries (not Go source)
COPY --from=builder /opt/mirage/blockchain/bin/miraged /opt/mirage/blockchain/bin/miraged
COPY --from=builder /opt/mirage/blockchain/bin/compact-db /opt/mirage/blockchain/bin/compact-db
COPY --from=builder /opt/mirage/blockchain/proto /opt/mirage/blockchain/proto
RUN chmod +x /opt/mirage/blockchain/bin/miraged /opt/mirage/blockchain/bin/compact-db

# Copy built frontend, plus the source the suites diff against (error copy,
# quest payout transport). Those checks are release gates and cannot skip.
COPY --from=builder /opt/mirage/web/frontend/build /opt/mirage/web/frontend/build
COPY --from=builder /opt/mirage/web/frontend/src /opt/mirage/web/frontend/src

# Copy Python runtime scripts and modules
COPY --from=builder /opt/mirage/scripts /opt/mirage/scripts
COPY --from=builder /opt/mirage/web/backend /opt/mirage/web/backend
COPY --from=builder /opt/mirage/indexer /opt/mirage/indexer
COPY --from=builder /opt/mirage/shared /opt/mirage/shared
COPY --from=builder /opt/mirage/tests /opt/mirage/tests

# Note: backend settings.yaml is already included in web/backend copy above

# Copy the entire deploy/ tree from the builder. We previously cherry-picked
# individual files, which silently dropped any deploy/ file added later
# (run_miraged_supervised.sh on May 27, create_validator.sh, etc.) — those
# would land on disk but never make it into the image, and entrypoint.sh
# would crash on a missing path. Bulk-copying deploy/ removes the trap; the
# few workstation-only scripts (deploy.sh, harden_server.sh, etc.) are
# inert in the running container and worth the noise.
COPY --from=builder /opt/mirage/deploy /opt/mirage/deploy

# Set working directory
WORKDIR /opt/mirage

# Expose ports:
# - 80, 443: Caddy (HTTP/HTTPS frontend)
# - 26656: P2P (node-to-node communication)
# - 26657: RPC (optional, for external queries)
EXPOSE 80 443 26656 26657

# Set entrypoint
ENTRYPOINT ["/opt/mirage/deploy/entrypoint.sh"]

