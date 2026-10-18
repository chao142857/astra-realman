# RealMan GUI + Banana V17 deployment snapshot

- Source baseline: `a40d8ac8`; 640 eligible tracked/deployed source, configuration and documentation files on yanglab matched local SHA256 values before this snapshot. Untracked deployment additions were included in the comparison; logs, credentials and AppleDouble files were excluded.
- Prompt bundle: `prompts/banana_handoff_v17/` (four Markdown files and one GUI text prompt). The overview includes the three stage files. Use the GUI text as the task prompt; the Markdown files are the corresponding reference bundle, not extra copies to concatenate into the task text.
- V17 adds left-grasp verification: 0.25 opening, separate 30 mm test lift, then either proceed on whole-object clearance or conditionally request 0.20 opening and a separate retest. Opening is not force; no executor-injected actions.
- Existing system includes bounded decision history, measured gripper feedback, prompt attachments on each request, GUI summaries/export, and strict acceptance of explicitly recognized recovered transport events. No new executor changes in this snapshot.

## Retained successful run

- Host: yanglab; run: `parallel-arms-20261018T142729-853ffbe2`.
- Original status: `MODEL_DONE`; 33 client requests; 1176.332226506 seconds.
- Operator explicitly confirmed task success. This is recorded separately from the model completion flag; no independent physical scoring PASS is invented.
- Full local archive: `/home/tongji/Desktop/Astra成功实验归档/20261018_142729_香蕉完整抓取交接放置_V17`.
- Archive manifest SHA256: `4c0981977738024467fb1a05f6b6da669b1958753f922de9c8363578157307b2`.
- 11029 archived files, 439895528 bytes; source/copy file checksums matched. Full evidence is not included in Git.

## Entry and scope

Existing GUI entry on yanglab: `bash launch/hardware_gui.sh` from the deployed `astra_realman_harness` directory. Starting model/hardware episodes remains an explicit GUI/operator action; this snapshot neither resumes nor authorizes a run.

No authentication material, photos, videos, full logs or robot motion are added by this snapshot. This records the current deployed interface, not a new certification of collision protection or calibration.
