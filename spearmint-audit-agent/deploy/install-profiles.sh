#!/bin/sh
# Copy repo profiles into the running Hermes container and start each gateway.
set -e
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
for dir in "$ROOT/hermes/profiles"/*; do
  name=$(basename "$dir")
  docker exec hermes hermes profile create "$name" || true
  docker cp "$dir/." "hermes:/opt/data/profiles/$name/"
  docker exec hermes hermes -p "$name" gateway start || true
done
echo "Profiles installed. Set the model with: docker exec -it hermes hermes -p lead model"
