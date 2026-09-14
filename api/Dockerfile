FROM python:3.12-slim

# Python não deve gravar .pyc nem bufferizar a saída: sem buffer, os logs
# aparecem no `docker compose logs` no instante em que acontecem.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
