# --- Stage 1: build the React/Vite frontend ---
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY civex-hub/frontend/package*.json ./
RUN npm ci
COPY civex-hub/frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.12-slim

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

# Place the built frontend where app.py expects it.
COPY --from=frontend /frontend/dist /civexhub/frontend/dist

EXPOSE 8001
CMD ["civexhub", "serve", "--host", "0.0.0.0", "--port", "8001"]
