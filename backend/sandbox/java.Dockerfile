FROM eclipse-temurin:17-jdk-jammy
RUN useradd -u 10001 -m runner
USER 10001:10001
WORKDIR /work
