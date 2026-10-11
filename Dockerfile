FROM python:3.11-slim AS develop
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

FROM develop as build_wheel
COPY . .
RUN python -m pip install --upgrade pip build && python -m build --wheel
