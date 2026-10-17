# Astra × RealMan

[English](README.md) | [简体中文](README_CN.md)

**Status: research paused · archival handoff, 2026-10-17**

An experimental integration and evaluation stack for vision-language decision backends on RealMan robot arms, with simulation and real-robot engineering paths.

**Developed by [@chao142857](https://github.com/chao142857).** Astra/model services, RealMan hardware/SDK, and other upstream systems are external dependencies; this repository does not implement their underlying models.

## Start here

- [Research archive and milestone index](docs/RESEARCH_ARCHIVE_20261017.md) — chronological experimental snapshots, known outcomes, and limitations.
- [Original branch-head manifest (63 refs)](docs/ARCHIVE_BRANCH_MANIFEST_20261017.tsv) — exact commit identifiers for every branch present when archival handoff began.
- [Chinese overview](README_CN.md).

**Important:** `main` retains the original 2026-10-05 real-robot baseline. It is not a unified or verified version of the later experiments. Later results live on separate immutable commit snapshots linked from the archive index. No stable, fully autonomous dual-arm grasp–handoff–placement real-robot baseline is claimed.

## Scope

The project covers multi-view observation, RealMan robot-state/frame integration, structured model proposals, execution and safety checks, telemetry, replay, simulation tools, persistent-world experiments, action-chunk evaluation, spatial-input pilot studies, and dual-arm engineering trials.

Some validation was performed using scripts or heuristic stubs; these results must **not** be interpreted as genuine Astra policy performance. Simulated successes are distinct from hardware success. Some raw experimental records and configuration remain outside GitHub.

## Repository layout

The early public baseline in `main` is centered on `astra_realman_harness/`, which contains observation, decision-backend integration, command protocol, execution utilities, documentation, scripts, and tests. Later branches introduce additional `experiments/` directories and evaluation artifacts.

## Research status

The research direction has been paused; no further experiments or maintenance are currently planned. Existing code and reported outcomes are preserved for reference and possible reuse. This is experimental research software, **not** a production or safety-certified robot controller. Do not operate hardware using old scripts without independent validation of the current device and environment.
