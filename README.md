# SWE-Residual

SWE-Residual evaluates agents that take over an unfinished task from a previous agent. Each residual instance preserves a normally submitted but unsuccessful task state. A matched clean-start task provides the original starting environment.

This release contains the benchmark definition and evaluation harness. See the paper for model evaluation results. The formal data package contains DeepSWE-Residual v2 and TB2.1 filesystem states with matched clean tasks. Task files, verifiers, DeepSWE state patches, metadata, and construction token records are included in this Git repository. The 31 TB2.1 Residual images are available from [lijinze956/swe-residual-tb21](https://hub.docker.com/r/lijinze956/swe-residual-tb21) on Docker Hub, with fixed registry digests recorded in this repository. See [DATASET.md](DATASET.md) for data preparation and [DOCKER_HUB.md](DOCKER_HUB.md) for image publication.

## Benchmarks

| Benchmark | Residual states | Unique tasks | Clean tasks | Starting state |
| --- | ---: | ---: | ---: | --- |
| DeepSWE-Residual v2 | 165 | 90 | 90 | Original repository with an uncommitted failed patch |
| TB2.1-Residual | 31 | 20 | 20 | Reconstructed filesystem state |

DeepSWE states originate from DeepSeek-V4-Flash-0731 (62), Qwen3.8-27B (72), and GLM 5.3 (31). TB2.1 states originate from Qwen3.8-27B (10), DeepSeek-V4-Flash-0731 (16), and GLM 5.3 (5).

Source runs use task-specific budgets, extended up to 8 hours for TB2.1 construction. We retain normally submitted failures with recoverable task states. DeepSWE applies the source patch without creating a commit. TB2.1 preserves files, logs, shell history, and terminal traces. The evaluated agent starts a fresh model conversation and receives the original task prompt, without the preceding agent's conversation.

The paper and formal release use 31 TB2.1 filesystem instances and 20 matched clean tasks.

## Run your own model

Requirements: Linux, Python 3.12+, Docker, and an internet connection for initial dependency and image downloads. The TB2.1 Residual images target `linux/amd64`. The harness includes a fixed, modified [Harbor source snapshot](UPSTREAM.md) (`0.21.0+residual.1`), provides mini-swe-agent configuration for DeepSWE, and packages the frozen Terminus-2 adapters for TB2.1.

```bash
python -m venv .venv
source .venv/bin/activate
bash scripts/install.sh

# Fetch official Clean bases and reconstruct the selected DeepSWE states.
python scripts/prepare.py --benchmark deepswe --subset dsv4
python scripts/prepare.py --benchmark tb21 --condition clean
# Fetch the 31 published Residual images by their recorded digests.
python scripts/prepare.py --benchmark tb21 --condition residual

export OPENAI_API_KEY='your-key'
export OPENAI_BASE_URL='https://your-provider.example/v1'

# Check task selection without model calls or container startup.
swe-residual deepswe --condition residual --subset dsv4 \
  --tasks assets/deepswe/tasks/dsv4 --model openai/your-model \
  --output runs/model-dsv4 --dry-run

# Run a residual subset; use --api responses for a Responses endpoint.
swe-residual deepswe --condition residual --subset dsv4 \
  --tasks assets/deepswe/tasks/dsv4 --model openai/your-model \
  --api chat --output runs/model-dsv4

# Run the matched clean-start union.
swe-residual deepswe --condition clean \
  --tasks assets/deepswe/tasks/clean --model openai/your-model \
  --api chat --output runs/model-clean

# Restore a TB2.1 state with a fresh agent conversation.
swe-residual tb21 --condition residual --tasks assets/tb21/tasks \
  --catalog assets/tb21/catalog.json \
  --verifier-manifest assets/tb21/verifier-manifest.json \
  --model openai/your-model --api chat --output runs/model-tb21

swe-residual-summarize runs/model-dsv4
```

DeepSWE uses mini-swe-agent 2.4.6, with a default 10,800-second agent budget and 120-second tool execution budget.

For TB2.1 Clean, select `--condition clean` with the same `assets/tb21/tasks` directory and verifier manifest; the Residual catalog is not required. Use `--api kimi --effort max`, `--api dsv41 --effort max`, or `--api responses --effort xhigh` for the corresponding adapters. `--agent-multiplier` defaults to 3 for TB2.1; `--agent-seconds` sets an explicit budget. API timeout, output limit, concurrency, and base URL are configurable. The task packages and approved verifier manifest are included in this repository.

Catalog paths may be relative to the catalog file. TB2.1 catalogs contain the task path, task name, original resources, image reference, and preserved shell/log context. The verifier manifest records `tasks.<name>.files_sha256` and an approved `runtime_profile` for the three tasks with pinned CPU verifier dependencies. Changed task instructions or verifier files stop evaluation before any model call.

Necessary Harbor fixes are already integrated. Harbor's retry queue preserves failed attempts and stops on archive conflicts. The included launcher performs no automatic retry. DeepSWE's optional `--command-user harboragent` enables command privilege separation; it is off by default to match the historical jobs. This setting is recorded in `protocol.json`. See [UPSTREAM.md](UPSTREAM.md) for each change and its scope. `patches/changes-from-upstream.patch` is a review artifact; no patch application is needed.

Each invocation uses a new output directory and performs one attempt per selected instance. It writes the effective protocol and a score record, including unscored outcomes. The summarizer rejects duplicate selected attempts and leaves the complete task-equal metric unset if any recorded instance is unscored. Submitted patch files are preserved byte-for-byte by the credential scrubber. Raw logs and trajectories remain private until separately audited for publication.

The repository provides 196 per-instance source construction token records. The three pinned CPU verifiers install missing dependencies on demand and reuse environments only after their audits pass. Offline runtime caches are excluded from publication.
Experimental model results are reported in the paper.

## Repository layout

```text
README.md                  Benchmark description and harness usage
src/swe_residual/           Run entry point, scoring, and artifact handling
src/swe_residual/tb21/      Agents, model interfaces, environments, and shared utilities
vendor/harbor/             Fixed Harbor source with integrated modifications
UPSTREAM.md                Upstream commit, local changes, and optional settings
scripts/                   Installation, data preparation, Docker publication, and review tools
assets/                    Task packages, DeepSWE patches, and image manifests
metadata/                  Instance indexes and construction token records
provenance/                Original DeepSWE environment definitions
DATASET.md                 Data layout and environment preparation
DOCKER_HUB.md              Published image references and maintainer upload instructions
SHA256SUMS.json            Dataset file checksums
patches/                   One consolidated diff against the fixed upstream commit
tests/                     Offline unit checks; no model calls
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
ruff check src tests
```

Code is licensed under Apache-2.0. Benchmark/task assets retain their own applicable licenses and notices.
