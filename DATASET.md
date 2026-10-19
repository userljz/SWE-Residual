# Benchmark data

This Git repository supplies task descriptions, admitted verifiers, recoverable
starting states, per-instance metadata, and source construction token records.
Docker Hub supplies the TB2.1 Residual environment images.

| Component | Residual states | Unique tasks | Clean tasks | Environment delivery |
|---|---:|---:|---:|---|
| DeepSWE v2 | 165 | 90 | 90 | Official initialized base images plus exact binary patches |
| TB2.1 filesystem edition | 31 | 20 | 20 | Published Residual images plus 20 pinned official Clean bases |

The formal release uses TB2.1 filesystem31/clean20. The two excluded runtime
states and SWE-bench Pro are outside this release. See the paper for model
evaluation results. This repository contains no experimental model result tables.

## Get the task files

Clone the repository to obtain the task files, metadata, dependency version
lists, and preparation scripts. The three verifier runtime caches are excluded
from publication. Verifiers install their pinned Python and packages on first
use, then reuse an existing environment only after its dependency audit passes.

```bash
# Clone the repository using the Code button's URL, then enter its directory.
python scripts/prepare.py --benchmark tb21 --verify-only
python scripts/prepare.py --benchmark deepswe --verify-only
```

`SHA256SUMS.json` records dataset file digests. The preparation script detects
missing or changed task files before environment preparation.

## Prepare the environments

Docker, Linux, Python 3.12+, and sufficient disk space are required. Install the
harness with `bash scripts/install.sh` in an activated virtual environment.

```bash
# Official TB2.1 Clean images are already pinned by digest.
python scripts/prepare.py --benchmark tb21 --condition clean

# Fetch all 31 published Residual images by their recorded digests.
python scripts/prepare.py --benchmark tb21 --condition residual

# Or select the published Docker Hub repository explicitly.
python scripts/prepare.py --benchmark tb21 --condition residual \
  --docker-repository lijinze956/swe-residual-tb21

# Build one DeepSWE Residual subset from official base images and source patches.
python scripts/prepare.py --benchmark deepswe --condition residual --subset dsv4
python scripts/prepare.py --benchmark deepswe --condition clean

# Print the planned commands without pulling images or starting containers.
python scripts/prepare.py --benchmark tb21 --condition clean --dry-run
```

All 31 Residual images are public in [lijinze956/swe-residual-tb21](https://hub.docker.com/r/lijinze956/swe-residual-tb21) and target `linux/amd64`.
`assets/tb21/dockerhub-images.json` maps each state to its tag and immutable
registry digest. No Docker Hub login is required for public pulls, subject to
Docker Hub's download limits.

Registry pulls use the recorded digest and verify image identity before assigning
the local tag used by the catalog. The check accepts the original config digest
on classic Docker stores or its independently verified manifest digest on
containerd stores. This process preserves the recorded failed starting state.

The existing offline image export remains supported but is not tracked by Git:

```bash
python scripts/prepare.py --benchmark tb21 --condition residual \
  --archive /path/to/images.tar.gz
```

This archive contains 31 independent Residual images. Its hash and size are
recorded in `assets/tb21/image-archive.json`. See [DOCKER_HUB.md](DOCKER_HUB.md)
for the owner's publication commands.

## State preservation

DeepSWE applies each exact binary patch to the recorded base commit without
creating a commit. A BuildKit bind mount keeps the patch file out of image layers.
Task instructions, test assertions, and resource/budget declarations retain their
source content. Three verifier launchers install their locked CPU dependencies
on demand instead of requiring the publisher's offline runtime archives.

TB2.1 preserves filesystem state and natural shell/log traces. API conversations
start empty. Logs can retain naturally persisted prior interactions. Credentials
were masked in copied metadata. Private package mirrors and stale host-specific
Docker labels were normalized; application bytes were preserved.

All 20 Clean tasks use their pinned official bases. Before model execution, the
bundled harness checks `tmux` and `asciinema`, reuses existing tools, and installs
missing tools with logged commands. Inspect `recording-tools-install.log` if
preparation fails. The protein-assembly verifier retains its separate runtime
and existing test assertions. Installing recording tools does not apply failed-agent edits
to a Clean task.

## Metadata and token counters

- `metadata/deepswe-residual.jsonl`: 165 Residual states.
- `metadata/deepswe-clean.jsonl`: 90 matched Clean tasks.
- `metadata/tb21-fs31-residual.jsonl`: 31 Residual states.
- `metadata/tb21-fs31-clean.jsonl`: 20 matched Clean tasks.
- `metadata/token-usage.jsonl`: 196 source construction records.

Token records link to stable asset IDs and preserve the source model and reported
input/output/cache counters. Available reasoning counters are included. Missing
counters remain null. Cache counters are not added again to input plus output.
These are reported counters, not billed usage. Clean tasks have no preceding
failed-agent construction run. Experimental evaluation usage and results remain
private.

Code is Apache-2.0. Source tasks, repositories, images, and dependencies retain
their own licenses and notices. The code license does not assign a global license
to all benchmark assets.
