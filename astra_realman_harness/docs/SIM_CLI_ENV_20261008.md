# Local CLI environment follow-up

Base: `3e7fcd51f386f715f266168c7f8de067be9c8b7d`; retain both this input-contract
commit and `f7c8da1`, plus the first failed-call evidence. Workspace files were
moved beneath `/home/alex/astra-realman_ws`; Git worktree path records were
repaired without modifying the old source trees or evidence.

The first attempt failed before any model response: resolving the configured
Codex symlink before constructing PATH dropped the nvm bin directory and selected
system Node 12. `worker_environment()` now prepends the configured launcher
directory, followed by the resolved script directory and `/usr/bin:/bin`.
The original seven-variable environment allowlist is unchanged. This does not
inherit shell PATH, NODE_OPTIONS, CODEX_HOME or other shell settings, change
system Node, or install a different CLI.

`preflight()` and `infer()` use this same builder. Preflight runs only Node
`--version`, Codex `--version`, and `codex exec --help`, with stdin closed, in
an empty worker-style `input_only` directory. It records launcher, resolved
script, selected/resolved Node, PATH, cwd, environment key names, and each probe's
stdout/stderr/exit code. Actual infer records the same path metadata in
`environment.json`; each invocation retains its own isolated runtime directory.
No prompt or model request is sent by preflight. The simulation entrypoint
requires preflight PASS before constructing RM65Backend; failure exits with
zero scene creation, zero model calls and zero hardware calls.

Offline commands from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python -m unittest discover -s astra_realman_harness/tests -p test_cli_environment.py -v
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python -m unittest discover -s astra_realman_harness/tests -p test_sim_skills.py -v
```

Results: 4 + 29 tests PASS. The new regression constructs a symlinked fake Codex,
a new fake Node beside its launcher and an old fake system Node. It reproduces
the old failure, then verifies both version/help preflight and actual infer
(with a fake CLI only) select the new Node. Other tests cover the environment
allowlist, preflight timeout, and failure before scene creation. Existing tests
cover final M/S input contracts, request limits, STOP/late results and simulation
isolation. These are offline tests, not physical or model performance evidence.

Real version/help preflight also passed before commit: launcher
`/home/alex/.nvm/versions/node/v22.23.2/bin/codex`, script
`/home/alex/.nvm/versions/node/v22.23.2/lib/node_modules/@openai/codex/bin/codex.js`,
Node `/home/alex/.nvm/versions/node/v22.23.2/bin/node` at `v22.23.2`, Codex
`0.161.0`. The sandboxed preflight retained two nonfatal PATH-alias read-only
warnings in stderr; all three probes exited 0. System Node remains `v12.22.9`.
Receipts: `/tmp/astra-cli-env-evidence-20261008/`.

The entire sim_skills directory, targets, shared primitive generator and CLI
command builder are unchanged from the base. No M/S, prompts, medium, physics,
checks, output protocol or retry behavior changed. All 56 frozen asset entries
and all 118 files in the prior failure evidence manifest were hash-verified.

Subsequent authorization is at most one fresh S-condition gpt-6-astra/medium
top-level CLI request with the existing 120-second decision budget. Stop, CLI/API
failure, timeout or parse error does not permit a second attempt. Server identity,
effort and internal retries remain unknown unless explicitly returned. Results
are fixed engineering scene channel validation, not an E1 performance claim.

OpenAI Docs reference checked for the CLI command surface:
https://learn.chatgpt.com/docs/developer-commands?surface=cli
Local version/help receipts establish the installed behavior used here.
