FROM python:3.11-slim

# Run as a non-root user for defense-in-depth.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py webui.py ./

# Runtime config directory (mounted as a volume), writable by the app user.
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

CMD ["python", "main.py"]
