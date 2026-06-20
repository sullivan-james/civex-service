# --- Stage 1: build the React/Vite frontend ---
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY civex-hub/frontend/package*.json ./
RUN npm ci
COPY civex-hub/frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.12-slim

# Install openssh-server for SSH transport support
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/run/sshd

# Install civex (parent package) with the PostgreSQL driver.
# Installed non-editable; only its importable code is needed.
COPY src/ /civex-service/src/
COPY pyproject.toml /civex-service/
RUN pip install --no-cache-dir "/civex-service[postgres]"

# Install civexhub as an editable install so the path calculation in
# server/app.py (Path(__file__).parent × 4) resolves to /civexhub/.
COPY civex-hub/src/ /civexhub/src/
COPY civex-hub/pyproject.toml /civexhub/
RUN pip install --no-cache-dir -e /civexhub

# Configure sshd: AuthorizedKeysCommand uses civexhub-keys to serve keys from the DB
COPY civex-hub/sshd_config_append.txt /tmp/sshd_config_append.txt
RUN cat /tmp/sshd_config_append.txt >> /etc/ssh/sshd_config && \
    rm /tmp/sshd_config_append.txt

# Place the built frontend where app.py expects it.
COPY --from=frontend /frontend/dist /civexhub/frontend/dist

COPY civex-hub/start.sh /usr/local/bin/start.sh
RUN sed -i 's/\r//' /usr/local/bin/start.sh && chmod +x /usr/local/bin/start.sh

EXPOSE 8001 22
CMD ["/usr/local/bin/start.sh"]
