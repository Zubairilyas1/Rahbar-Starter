# RAHBAR evaluation image: the Part B suite, the release gate (C2) and the coverage
# check (E). Runs as the eval Kubernetes Job (k8s/eval-job.yaml).
#
# Build context: the REPOSITORY ROOT (it copies eval/):
#   docker build -f eval/Dockerfile -t rahbar-eval:dev .
FROM python:3.12-slim

RUN apt-get -o Acquire::Retries=8 update && apt-get -o Acquire::Retries=8 upgrade -y && rm -rf /var/lib/apt/lists/*
RUN groupadd -r rahbar --gid=1000 \
    && useradd -r -g rahbar --uid=1000 --home-dir=/app --shell=/sbin/nologin rahbar

WORKDIR /app
RUN pip install --no-cache-dir --retries 10 --timeout 120 httpx==0.28.1 pyyaml==6.0.2

COPY eval/test_three_levels.py eval/release_gate.py eval/job.py eval/check_coverage.py \
     eval/gate_thresholds.yaml eval/golden.jsonl eval/human_labels.jsonl eval/golden_baseline.jsonl eval/live_queries.jsonl \
     /app/eval/

RUN chown -R rahbar:rahbar /app
USER rahbar
ENV PYTHONUNBUFFERED=1 RESULTS_DIR=/results

ENTRYPOINT ["python", "/app/eval/job.py"]
