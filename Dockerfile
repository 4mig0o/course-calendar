FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["sh", "-c", "python server.py --host 0.0.0.0 --port ${PORT:-8787}"]
