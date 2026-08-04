FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8080
ENV HOST=0.0.0.0
EXPOSE 8080

CMD gunicorn -b 0.0.0.0:${PORT} -w 2 --timeout 300 server:app
