FROM node:20-slim
RUN useradd -u 10001 -m runner || true
USER 10001:10001
WORKDIR /work
