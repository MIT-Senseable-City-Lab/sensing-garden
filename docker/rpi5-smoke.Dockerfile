FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN test -x /usr/bin/python3 || ln -s "$(command -v python3)" /usr/bin/python3

RUN pip install --no-cache-dir poetry==2.1.3

WORKDIR /workspace

COPY pyproject.toml poetry.lock README.md /workspace/
COPY bugcam /workspace/bugcam
COPY tests /workspace/tests
COPY scripts /workspace/scripts
COPY docs /workspace/docs
COPY resources /workspace/resources

RUN poetry install --no-interaction --no-ansi

CMD ["poetry", "run", "pytest", "tests", "-q"]
