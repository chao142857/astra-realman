# Astra × RealMan

Experimental real-robot manipulation harness for running Astra-style vision-language decision loops on a RealMan platform.

> **Status:** v0.1 — first public real-robot baseline snapshot (2026-10-05).  
> This repository is under active development; later revisions and experiments will continue here.

## What this repository is

This project is the integration and experimentation stack I built to connect a multimodal decision backend to a real RealMan robot, execute structured manipulation actions, and verify the resulting robot state in a closed loop.

The repository contains the RealMan integration, camera/observation pipeline, decision backend adapters, action protocol, execution/safety checks, telemetry, replay tooling, tests, and experiment runners used in the first real-robot baseline.

**Implementation and experiment pipeline in this repository were developed by [@chao142857](https://github.com/chao142857).**  
Astra/model backends, RealMan hardware, and the RealMan SDK are external dependencies; this repository is an independent research integration rather than an implementation of those upstream systems.

## Current baseline

The current snapshot captures the first end-to-end RealMan baseline used for real-robot manipulation experiments.

Core components include:

- multi-view RGB observation and persistent camera sessions;
- RealMan robot-state / frame integration;
- structured action proposals with explicit Cartesian deltas and gripper commands;
- pluggable decision backends, including the current Codex/Astra experiment path;
- frame, safety, feasibility, and execution checks;
- supervised / step-wise real-robot execution utilities;
- execution telemetry, verification, replay, and offline tests;
- snapshot manifests for reproducibility.

A simplified data flow is:

```text
multi-view RGB + robot state
            ↓
     decision backend
            ↓
   structured action proposal
            ↓
 frame / safety / feasibility checks
            ↓
        robot executor
            ↓
 telemetry + state verification
            ↓
      next observation
```

## Repository layout

```text
astra_realman_harness/
├── decision_backends.py        # backend abstraction / model integration
├── codex_astra_backend.py      # current Astra/Codex backend path
├── observation.py              # observation construction
├── camera_session.py           # multi-camera capture/session handling
├── realman_state.py            # RealMan state integration
├── decision_protocol.py        # structured action protocol
├── decision_safety.py          # safety / validity gates
├── supervised_step.py          # supervised step execution
├── supervised_live.py          # live supervised execution path
├── execution_telemetry.py      # execution logging
├── execution_verification.py   # post-action verification
├── scripts/                    # experiment / replay runners
├── config/                     # experiment configuration
├── schema/                     # action schemas
├── docs/                       # engineering notes / evidence
└── tests/                      # offline tests

SNAPSHOT.md
SNAPSHOT_SHA256.json
```

## Notes

This is an **experimental research harness**, not a production robot-control SDK or a safety-certified system.

The codebase contains both earlier shadow / dry-run safety paths and later real-robot execution experiments. Some paths and configuration values in the archived snapshot are workstation-specific and will need adaptation on another machine.

The first version is intentionally preserved as a baseline. Future work will iterate on the decision loop, execution reliability, latency, placement accuracy, and higher-level reasoning while keeping the earlier snapshot reproducible.

## Development

Current work is ongoing. This repository will be updated as the next RealMan experiments and system revisions are completed.
