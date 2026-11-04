FROM python:3.12-slim
WORKDIR /work
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir -r requirements.txt
COPY scripts scripts
COPY config config
CMD ["bash", "scripts/run_all.sh"]
