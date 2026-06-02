# Stage 1: Build the NSE sidecar (Node.js)
FROM node:20-alpine AS sidecar

WORKDIR /sidecar
COPY sidecar/package.json sidecar/package-lock.json ./
RUN npm install           # all deps needed for tsc build

COPY sidecar/tsconfig.json ./
COPY sidecar/src/ ./src/
RUN npx tsc --version && npx tsc
RUN mkdir -p build/graphql-schema && find src -name "*.graphql" -print0 | xargs -0 -I{} cp {} build/graphql-schema/

# Strip dev deps after build for a leaner runtime image
RUN npm prune --production

# Stage 2: Python backend + sidecar runtime
FROM python:3.13-slim

# Node.js runtime for the sidecar
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built sidecar
COPY --from=sidecar /sidecar/build /app/sidecar/build
COPY --from=sidecar /sidecar/node_modules /app/sidecar/node_modules
COPY --from=sidecar /sidecar/package.json /app/sidecar/

# Install Python deps
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy app source
COPY backend/ /app/backend/
COPY tradingagents/ /app/tradingagents/
COPY cli/ /app/cli/
COPY pyproject.toml /app/

# Install tradingagents package (deps already in requirements.txt)
RUN pip install --no-cache-dir . --no-deps

# Entrypoint
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

ENV NSE_SIDECAR_URL=http://localhost:3000
ENV SIDECAR_PORT=3000
EXPOSE 10000

CMD ["/app/entrypoint.sh"]
