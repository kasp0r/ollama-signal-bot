FROM python:3.11-slim

# Run as a non-root user for defense-in-depth.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./

USER appuser

CMD ["python", "main.py"]