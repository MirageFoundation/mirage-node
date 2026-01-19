# Multi-stage Dockerfile for Mirage production deployment
# Stage 1: Build frontend, install dependencies
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/usr/local/go/bin:$PATH
ENV PIP_ROOT_USER_ACTION=ignore

# Install build dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get update && apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*
## Keep npm up to date to avoid update notices
RUN npm i -g npm@latest --no-audit --no-fund

WORKDIR /opt/mirage

# Copy dependency files first for better layer caching
COPY web/backend/requirements.txt /opt/mirage/web/backend/requirements.txt
COPY web/frontend/package.json web/frontend/package-lock.json /opt/mirage/web/frontend/

# Install Python dependencies
RUN pip3 install --break-system-packages --root-user-action=ignore --no-cache-dir -r /opt/mirage/web/backend/requirements.txt

# Install frontend dependencies
WORKDIR /opt/mirage/web/frontend
RUN npm ci --no-audit --no-fund --legacy-peer-deps

# One-time workaround dependency (keep cached unless package.json/lock changes)
RUN npm install --no-audit --no-fund --no-save --legacy-peer-deps @babel/plugin-transform-private-property-in-object

# Copy frontend sources only (avoid invalidating cache on unrelated changes)
COPY web/frontend/ /opt/mirage/web/frontend/

# Build frontend (version comes from build args provided by deploy script)
ARG GIT_BRANCH
ARG GIT_HASH
ENV BROWSERSLIST_IGNORE_OLD_DATA=true
RUN REACT_APP_VERSION="${GIT_BRANCH:-?} (${GIT_HASH:-?})" REACT_APP_API_BASE=/api npm run build

# Copy runtime files after frontend build so backend/go changes don't force a React rebuild
WORKDIR /opt/mirage
COPY blockchain/bin/miraged /opt/mirage/blockchain/bin/miraged
COPY blockchain/bin/orchestrator /opt/mirage/blockchain/bin/orchestrator
COPY scripts/ /opt/mirage/scripts/
COPY web/backend/ /opt/mirage/web/backend/
COPY indexer/ /opt/mirage/indexer/
COPY shared/ /opt/mirage/shared/
COPY referrals/ /opt/mirage/referrals/
COPY deploy/ /opt/mirage/deploy/

## Note: We trust upstream build step to produce /opt/mirage/blockchain/bin/miraged

# Stage 2: Minimal runtime image
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/usr/local/bin:/usr/bin:/bin
ENV PYTHONPATH=/opt/mirage
ENV BACKEND_HOST=127.0.0.1
ENV BACKEND_PORT=5000
ENV TERM=xterm-256color

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    postgresql \
    postgresql-client \
    postgresql-common \
    tmux \
    nano \
    micro \
    tree \
    curl \
    ca-certificates \
    coreutils \
    jq \
    procps \
    dnsutils \
    cronolog \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

# Add shell aliases
RUN echo "alias m='micro'" >> /etc/bash.bashrc

# Install Caddy (fail-fast)
RUN apt-get update && apt-get install -y caddy && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/dist-packages /usr/local/lib/python3.12/dist-packages

# Copy only runtime files (not source code)
WORKDIR /opt/mirage

# Copy compiled binaries (not Go source)
COPY --from=builder /opt/mirage/blockchain/bin/miraged /opt/mirage/blockchain/bin/miraged
COPY --from=builder /opt/mirage/blockchain/bin/orchestrator /opt/mirage/blockchain/bin/orchestrator
RUN chmod +x /opt/mirage/blockchain/bin/miraged /opt/mirage/blockchain/bin/orchestrator

# Copy built frontend (not source)
COPY --from=builder /opt/mirage/web/frontend/build /opt/mirage/web/frontend/build

# Copy Python runtime scripts and modules
COPY --from=builder /opt/mirage/scripts /opt/mirage/scripts
COPY --from=builder /opt/mirage/web/backend /opt/mirage/web/backend
COPY --from=builder /opt/mirage/indexer /opt/mirage/indexer
COPY --from=builder /opt/mirage/shared /opt/mirage/shared
COPY --from=builder /opt/mirage/referrals /opt/mirage/referrals

# Note: backend settings.yaml is already included in web/backend copy above

# Copy deployment files (new entrypoint and init)
COPY --from=builder /opt/mirage/deploy/entrypoint.sh /opt/mirage/deploy/entrypoint.sh
COPY --from=builder /opt/mirage/deploy/init.sh /opt/mirage/deploy/init.sh
COPY --from=builder /opt/mirage/deploy/templates /opt/mirage/deploy/templates

# Deploy migrations and env sync (run automatically on startup)
COPY --from=builder /opt/mirage/deploy/__init__.py /opt/mirage/deploy/__init__.py
COPY --from=builder /opt/mirage/deploy/migrations /opt/mirage/deploy/migrations

# Template renderer
COPY --from=builder /opt/mirage/deploy/render_template.py /opt/mirage/deploy/render_template.py

# Copy deployment script for consensus key derivation
COPY --from=builder /opt/mirage/deploy/derive_consensus_key.py /opt/mirage/deploy/derive_consensus_key.py

# Domain/TLS helper scripts
COPY --from=builder /opt/mirage/deploy/letsencrypt_register.sh /opt/mirage/deploy/letsencrypt_register.sh
COPY --from=builder /opt/mirage/deploy/enable_validator_mode.sh /opt/mirage/deploy/enable_validator_mode.sh

# IBC relayer setup
COPY --from=builder /opt/mirage/deploy/setup_hermes.sh /opt/mirage/deploy/setup_hermes.sh

# Set working directory
WORKDIR /opt/mirage

# Expose ports:
# - 80, 443: Caddy (HTTP/HTTPS frontend)
# - 26656: P2P (node-to-node communication)
# - 26657: RPC (optional, for external queries)
EXPOSE 80 443 26656 26657

# Set entrypoint
ENTRYPOINT ["/opt/mirage/deploy/entrypoint.sh"]

