#!/usr/bin/env bash
# Build backend/dist/lambda.zip for the python3.12 x86_64 Lambda runtime.
# Downloads Linux wheels explicitly, so it works from macOS without Docker.
set -euo pipefail

cd "$(dirname "$0")/.."
rm -rf build dist
mkdir -p build dist

python3 -m pip install \
  --quiet \
  --target build \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  -r requirements.txt

cp -r app lambda_handler.py build/
find build -name "__pycache__" -type d -prune -exec rm -rf {} +

(cd build && zip -qr ../dist/lambda.zip .)
echo "Built $(pwd)/dist/lambda.zip ($(du -h dist/lambda.zip | cut -f1))"
