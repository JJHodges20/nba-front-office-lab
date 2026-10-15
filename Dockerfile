# The NBA Front Office Lab: one image for the HTTP API and the workbench (decision 0019).
# Built and run by `docker compose up --build`: see compose.yaml and the README.
#
# The image holds the code, its settings and its documents. Your data - the database, your
# contract file, the accounts, the documents' index - is the data/ folder Compose mounts,
# never part of the image (.dockerignore keeps it, and your .env, out).

FROM python:3.14.6-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FOL_HOME=/app

WORKDIR /app

# The dependencies first, pinned as the test suite ran them, so that a change to the lab's
# own code reuses this layer.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

COPY configs ./configs
COPY docs ./docs
COPY apps ./apps
COPY .streamlit ./.streamlit

# Not root: the mounted data folder is the one place the lab writes.
RUN useradd --create-home --uid 1000 lab \
    && mkdir -p /app/data \
    && chown lab:lab /app/data
USER lab

EXPOSE 8000 8501
CMD ["fol", "info"]
