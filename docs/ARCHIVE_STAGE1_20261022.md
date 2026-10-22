# Branch consolidation — Stage 1 / 分支整理第一阶段

Date: 2026-10-22 (Asia/Shanghai).

This is the non-destructive archival stage. No original remote branch has been deleted. The supplied bilingual README files are published verbatim; the original October 5 baseline code is unchanged.

本阶段仅归档与建立入口，没有删除旧远端分支。用户提供的双语 README 原文发布，原始程序基线保持不变。

## Original branch map / 原分支映射

[75 original names, full head SHAs, archive tags, and target ancestry](ARCHIVE_BRANCH_MAP_20261022.tsv)

Every original head is retained by a lightweight tag named `archive/20261022/heads/<original-branch>`. All 75 tags were read back from GitHub and matched to the pre-operation snapshot. Tag names preserve commit references; no claim of an enforced immutable-tag ruleset is made.

## Five entry branches / 五个入口

- `main`: original code baseline plus archive documentation; original head `22bfb2e549e6ca98b741ba84f254d4c1bbe66225` is retained by its archive tag.
- `realman/v17`: `3d765ab9cd8a41fe226db1fd7ea507998752440b`.
- `research/spatial`: `6484545bb3d760a0753cc33f10e6e4f35e0acb5a`.
- `research/rm65`: `c3330268e6288ebde1ea232c56fd29f00c80032b`.
- `develop/aspire`: `c7597fc27c8744044741888a9e6fff6e60a891cf`.

The four new entries start at those exact commits. No merge, squash, rebase or force-push was used. During Stage 1 the 75 original branches coexist with the four new entries: 79 remote branches are expected until separately confirmed cleanup.

## Verified independent Git backup / 独立 Git 备份

- Bundle: `astra-realman-original-75-heads-20261022.bundle` (stored privately; not uploaded into Git).
- Bytes: 800117921.
- SHA256: `01b73151d53b4b0a59e8c94e0bf30d99210d0bda345b9aa275787df9a1eb6323`.
- Restored into a newly initialized empty bare repository without network access, alternates or promisor packs.
- All 75 original branches, 75 archive tags, 182 commits and 18,490 reachable Git objects matched. `git fsck --full --strict --no-reflogs` passed.
- The bundle is a complete pre-documentation-update history for all 75 original heads, including tracked evidence blobs. It is not just a manifest or an incremental bundle.

## Backup coverage limits / 覆盖范围

No canonical Git LFS pointers or submodule gitlinks were found in the reachable original history. Consequently, no separate LFS payload was needed for that history. This does not certify unrelated/unreachable server-side LFS objects.

Workstation-only raw videos, RGB-D, trajectories, model caches, environments, credentials, and untracked/unpushed work are not included unless already tracked and reachable from one of the original heads. No external raw evidence backup or new hardware validation is claimed. Existing working trees and experiment hardware were not modified.

## Stage 2 gate / 第二阶段条件

The 74 non-main original branches in the mapping are deletion candidates, with their original head SHA as the expected SHA. Stage 2 is not executed by this document or commit. It requires Stage 1 acceptance and confirmation of the exact deletion list. Re-read each ref immediately before deletion; a mismatched ref is skipped and reported, never force-deleted or overwritten. Preserve all archival tags and the five entries.

Existing draft PR #1 is retained unchanged during Stage 1. Its earlier archival prose is a historical record and does not replace the supplied current README.
