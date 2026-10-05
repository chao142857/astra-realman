# CodexAstraBackend
Model source is now the Mac's official Codex ChatGPT login, model gpt-6-astra,
reasoning effort low. There is no xmapi fallback. No login token is copied.

## Start the model bridge on the Mac
Run in a Mac terminal, not in the workstation SSH shell:

    ssh yanglab 'cat /home/tongji/alex/astra_realman_harness/scripts/codex_astra_mac_bridge.py' > /tmp/codex_astra_mac_bridge.py
    python3 /tmp/codex_astra_mac_bridge.py

Keep this terminal open. Ctrl-C stops the bridge and its own SSH tunnel.
This starts no robot loop and sends no hardware commands.
The workstation backend selection is CodexAstraBackend.
No new Enter/confirmation step was added to the continuous loop.
Do not start real automatic execution while the known collision-protection gap remains unresolved.

## Transport
Workstation -> existing call_astra -> CodexAstraBackend.decide(context, images)
-> authenticated loopback HTTP over SSH reverse tunnel
-> Mac official codex exec -> original raw JSON -> existing parser.
Mac port 18767 and workstation port 18766 are loopback-only.
A bridge token is stored at config/codex_astra_bridge.token (0600).
This is not an OpenAI credential. Do not publish it.
Context stdin JSON is unchanged. Image bytes are copied to local attachment files;
paths inside context remain the original recorded paths. Existing schema is supplied verbatim.
Shell, external tools, MCP, plugins and agents are disabled in the model process.
A missing bridge, timeout, CLI failure, missing output, forbidden tool event,
or invalid action raises BackendFailure; it never becomes REJECTED_IK.
The bridge performs no hardware calls, planning, projection, retry, or recovery.

## Logs
Existing decision directory: prompt.txt, command.json, astra_raw.txt, last_message.json,
events.jsonl, stderr.log, backend_result.json.
Mac CLI logs: /private/tmp/codex-astra-bridge/<request uuid>/.
Existing proposal/execution/after-state logging is unchanged.
Model cancellation terminates only its own CLI process, never a robot motion.

## Acceptance
6 backend mock tests and 11 existing feasibility/loop mock tests passed.
Archived four-image official end-to-end acceptance:
logs/codex-astra-backend-acceptance-20261005T114614Z
CLI exit=0; CLI latency=14.7466 s; backend latency=15.0471 s.
Returned zero arm delta, opening=1, done=false; existing parser accepted.
No robot SDK or executor was invoked during this acceptance.
Temporary acceptance bridge stopped after test.
Backup: logs/codex-astra-backend-upgrade-20261005T114525Z
Loop, executor, IK and schema hashes match the backup manifest.
Context builder, parser and safety function ASTs also match.
