FROM python:3.12-slim

# Don't write .pyc files, don't buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Run as a non-root user (security best practice — equivalent to your
# `f1app` service account from the old setup)
RUN useradd --system --no-create-home --shell /usr/sbin/nologin apiuser \
    && chown -R apiuser:apiuser /app
USER apiuser

EXPOSE 8000

# uvicorn replaces gunicorn as the WSGI/ASGI server. For FastAPI (async),
# uvicorn is the standard. 4 workers ~= your old gunicorn `--workers 3`.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
