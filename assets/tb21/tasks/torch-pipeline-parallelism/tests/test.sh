#!/bin/bash
# Prepare pinned dependencies on demand, then run the unchanged verifier tests.
set -euo pipefail
mkdir -p /logs/verifier
exec > >(tee -a /logs/verifier/bootstrap-and-test.log) 2>&1
trap 'rc=$?; echo "[$(date -Is)] verifier exit=$rc"' EXIT
echo "[$(date -Is)] verifier dependency preparation start"
if ! py="$(bash /tests/prepare_runtime.sh)"; then
    echo 'VERIFIER_BOOTSTRAP_ERROR: dependency preparation failed; no task reward written'
    exit 70
fi
touch /logs/verifier/bootstrap.ok
echo "[$(date -Is)] pytest start"
set +e
"$py" -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
rc=$?
set -e
if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
    echo "VERIFIER_INFRASTRUCTURE_ERROR: pytest exit=$rc"
    exit "$rc"
fi
"$py" -c 'import json; r=json.load(open("/logs/verifier/ctrf.json")); assert r["results"]["summary"]["tests"]>0'
if [ "$rc" -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
echo "[$(date -Is)] verifier completed with valid test execution"
