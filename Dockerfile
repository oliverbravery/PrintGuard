# syntax=docker/dockerfile:1.4
FROM --platform=$BUILDPLATFORM python:3.11-slim-bookworm AS base

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential python3-dev libffi-dev \
      libjpeg-dev zlib1g-dev libtiff-dev \
      libfreetype6-dev libwebp-dev libopenjp2-7-dev \
      libgomp1 \
      ffmpeg libgl1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /printguard
COPY . /printguard

RUN pip install --upgrade pip \
 && pip install .

FROM --platform=$TARGETPLATFORM python:3.11-slim-bookworm AS runtime

COPY --from=base /usr/local /usr/local

WORKDIR /printguard
COPY --from=base /printguard /printguard

EXPOSE 8000
VOLUME ["/data"]
ENTRYPOINT ["printguard"]