FROM python:3.11-slim
# 실행 + 정적 분석(ruff, radon)을 같은 이미지에서 한다. 빌드 때만 네트워크가 필요하고 런타임은 --network none.
RUN pip install --no-cache-dir ruff==0.6.9 radon==6.0.1 \
 && useradd -u 10001 -m runner
USER 10001:10001
WORKDIR /work
