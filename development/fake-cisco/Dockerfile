FROM python:3.12-slim

RUN pip install --no-cache-dir paramiko==3.5.0

WORKDIR /app
COPY server.py .

RUN mkdir -p /var/fake-cisco /output

EXPOSE 22

CMD ["python", "server.py"]
