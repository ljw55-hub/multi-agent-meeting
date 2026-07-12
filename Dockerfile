ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG INSTALL_WHISPERX=false

WORKDIR /app

COPY requirements.txt .
COPY requirements-whisperx.txt .
RUN pip install --default-timeout=300 --retries 10 -i ${PIP_INDEX_URL} -r requirements.txt
RUN if [ "$INSTALL_WHISPERX" = "true" ]; then \
      pip install --default-timeout=300 --retries 10 -i ${PIP_INDEX_URL} -r requirements-whisperx.txt; \
    fi

COPY src ./src
COPY web ./web

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
