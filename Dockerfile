FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY zodyak_western_calculation_api ./zodyak_western_calculation_api

RUN pip install --no-cache-dir .

EXPOSE 5010

CMD ["sh", "-c", "gunicorn zodyak_western_calculation_api.app:app --bind 0.0.0.0:${PORT:-5010}"]
