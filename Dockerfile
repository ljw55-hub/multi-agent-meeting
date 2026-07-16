ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG WHISPERX_CONSTRAINTS=constraints-whisperx-cpu.txt
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG WHISPERX_CONSTRAINTS=constraints-whisperx-cpu.txt
ARG INSTALL_WHISPERX=false

WORKDIR /app

COPY requirements.txt .
COPY requirements-whisperx.txt .
RUN pip install --default-timeout=300 --retries 10 -i ${PIP_INDEX_URL} -r requirements.txt

COPY constraints-whisperx-cpu.txt .
COPY constraints-whisperx-gpu.txt .
RUN if [ "$INSTALL_WHISPERX" = "true" ]; then \
      pip install --default-timeout=300 --retries 10 \
        --index-url ${PYTORCH_INDEX_URL} \
        -r ${WHISPERX_CONSTRAINTS} && \
      pip install --default-timeout=300 --retries 10 \
        -i ${PIP_INDEX_URL} \
        --extra-index-url ${PYTORCH_INDEX_URL} \
        -c ${WHISPERX_CONSTRAINTS} \
        -r requirements-whisperx.txt; \
    fi

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY src ./src
COPY web ./web

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
