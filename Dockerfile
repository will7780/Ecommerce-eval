FROM node:20-alpine AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.pypi.md LICENSE ./
COPY src/ ./src/
COPY examples/ ./examples/
COPY --from=web-build /build/src/commerce_eval/static/ ./src/commerce_eval/static/
RUN pip install --no-cache-dir .
RUN mkdir -p /data
EXPOSE 8770
CMD ["sh", "-c", "commerce-eval --database /data/platform.db demo --seed-only && commerce-eval --database /data/platform.db serve --host 0.0.0.0 --port 8770 --allow-unsafe-remote"]
