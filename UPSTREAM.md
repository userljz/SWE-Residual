# Harbor source provenance

The complete tracked Harbor source snapshot is included in `vendor/harbor/`.
It contains upstream code, build files, templates, tests, documentation, and
Apache-2.0 license notices. It does not contain the original checkout's Git
metadata, virtual environment, private tasks, jobs, or local logs.

| Item | Value |
| --- | --- |
| Upstream repository | https://github.com/harbor-framework/harbor |
| Upstream commit | `f03db62fd2ed2ed1f79aefe024cfcbc68a0d759e` |
| Upstream version | `0.21.0` |
| Local version | `0.21.0+residual.1` |
| License | Apache-2.0; see `vendor/harbor/LICENSE` |

The project adapters in `src/swe_residual/` use the completed source cleanup:
TB2.1 has four modules (`agents`, `model_api`, `environment`, `tb21_utils`).
The launcher resolves these consolidated routes. Native model protocol and
environment regression tests are retained from that source revision.

## Integrated changes

| Historical change | Included behavior |
| --- | --- |
| 0002: command privilege separation | Optional `command_user`; disabled by default. The command user has a separate environment and no inherited controller credentials. The configured task directory is made writable. |
| 0003: Docker-safe trial names | Generated names use a lowercase, sanitized task prefix. |
| 0004: egress response deadline | GOST `readTimeout` is 1,200 seconds for long non-streaming responses. Model API timeouts remain separate. |
| 0005: retry artifacts | Failed attempts are renamed to `.failed-N` before a retry. A collision or archive failure stops the retry and preserves evidence. |
| 0006: pre-mounted agent reuse | Executable files are detected before PATH setup. An existing tool is not reinstalled or modified by the compatibility step. |
| 0007: LiteLLM client dependencies | The installer requests base `litellm`, without the proxy-server extra. |
| 0008: musl extension compatibility | A newly installed tool's interpreter adds missing GNU-suffix aliases only when needed. Original modules and existing aliases remain intact. |
| Artifact scrubber repair | The base Harbor trial redacts credential fields and known long secrets. It preserves `.patch` files and does not substitute short placeholders into task names or code. |

Local FeatureBench adapter changes (historical 0001) are outside this release's
DeepSWE/TB2.1 scope. The bundled FeatureBench adapter is the upstream version.

The historical DeepSWE jobs did not enable `command_user`. Keep the switch off
when matching that protocol. `swe-residual deepswe --command-user harboragent`
enables it for a new experiment and records the setting in `protocol.json`.
For Harbor's own CLI, set the agent kwarg `command_user=harboragent`.
The task image must support `setpriv`, user creation, and a writable Linux task
directory. This switch changes the execution protocol; its results should be
reported separately.

## Review and installation

`patches/changes-from-upstream.patch` is the single review diff. Its changes are
already included in the source. Installation does not apply a patch or fetch a
Harbor GitHub checkout. Install from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
bash scripts/install.sh
```

The installer supplies both local projects to the resolver and checks the
imported Harbor path and local version. Running `pip install -e .` alone does
not install the vendored dependency. Third-party Python packages and agent
tools still need package downloads unless provided through an approved cache.

With an upstream Git clone that contains the recorded commit, regenerate or
check the review diff:

```bash
python scripts/harbor_diff.py --upstream /path/to/harbor
python scripts/harbor_diff.py --upstream /path/to/harbor --check
```

The diff uses paths relative to the Harbor root. Review it against the recorded
commit, not against a current upstream release. Updated Harbor releases require
a deliberate source refresh and compatibility review.
