# Pilot 02 production preflight — blocked before dispatch

Baseline: `e6f0e31`. The user authorized at most 20 new requests on 2026-10-13. **0 dispatched; 20 remain.** No real ledger or usable batch grant has been created because the required host checks did not pass. This is an evidence record, not a dispatcher authorization file.

- `ssh -o BatchMode=yes -o ConnectTimeout=10 yanglab` timed out connecting to `100.78.222.78:22`.
- Mac `codex login status`: logged in using ChatGPT.
- `lsof -nP -iTCP:18767 -sTCP:LISTEN`: no listener. No `/decide` health request was sent.
- Existing four Pilot 01 worker processes were observed, not modified or used. Their inspected worker source sets a 180-second server timeout, insufficient for this authorization's greater-than-180-second requirement.
- The original production bridge and baseline source hashes match. Its existing `--timeout-s 190` option can satisfy the timeout requirement without modifying source, model or Code Mode once the original single bridge can be started.
- Mac verification: all 607 frozen entries and 20 ordered inputs passed. Yanglab sync and tests remain unperformed because SSH is unavailable.
- Local Tailscale reports Running but no peer entry with the target IP. This does not establish the remote machine's permanent state.

No hardware accessed, no worker switched, no old ledger read/reset, no model inference or retries. No success rates can be calculated without real observations; missing samples are not zero scores.

Restore yanglab connectivity, then continue the already authorized preflight and sequential batch. The existing 20-request authorization persists; do not create a second budget. Future server startup uses the original source with `--mode lab --executable /opt/homebrew/bin/codex --timeout-s 190`. Do not start generation until yanglab code/tests, authentication, reverse tunnel and server timeout pass, and a fresh ledger has been bound to this authorization.
