# RAHBAR indexer image. The only writer to Chroma (section 4.2); runs to completion
# as a Kubernetes Job/CronJob, then exits.
#
# Build context: the REPOSITORY ROOT, not indexer/ -- this image bakes in the corpus
# (see docs/ARCHITECTURE.md, "Corpus delivery to the indexer image"):
#
#   docker build -f indexer/Dockerfile -t rahbar-indexer:<tag> .
#
# `corpus/raw/` is gitignored and only exists locally after `python corpus/fetch.py`.
# `make images` runs `mkdir -p corpus/raw` first so this COPY never fails even on a
# machine that has not fetched anything yet (the image then simply has no real
# documents, which is fine for CI: CI always indexes /app/fixtures instead).
FROM python:3.12-slim

# System packages for OCR (pytesseract + pdf2image need the actual binaries, not just
# the Python wheels): pytesseract shells out to `tesseract`; pdf2image shells out to
# poppler's `pdftoppm`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r rahbar --gid=1000 \
    && useradd -r -g rahbar --uid=1000 --home-dir=/app --shell=/sbin/nologin rahbar

WORKDIR /app

COPY indexer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY indexer/pipeline/ /app/pipeline/

# Real deployment corpus (baked in at build time; see note above).
RUN mkdir -p /corpus
COPY corpus/raw/ /corpus/

# CI's e2e-eval job indexes this tiny, always-committed fixture corpus instead of the
# real one, by overriding CORPUS_DIR=/app/fixtures -- no network call to the live
# university site from CI.
COPY eval/fixtures/ /app/fixtures/

RUN mkdir -p /tmp && chown -R rahbar:rahbar /app /corpus /tmp
USER rahbar

ENTRYPOINT ["python", "-m", "pipeline.run"]
