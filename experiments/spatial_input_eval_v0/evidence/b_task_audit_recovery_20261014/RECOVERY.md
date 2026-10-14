# ubuntu-robot offline audit recovery — 2026-10-14

Synced audit commit d873caf after SSH recovery. Original 34 untracked audit files are preserved at the backup path in sync.json. Compared archived Linux results with the committed local results: no feasibility, constraint or substantive data differences; 18 timing fields differ and 5,302 numeric entries differ by at most 1.1102230246251565e-16.

25 offline tests passed on Ubuntu-Robot. All 3,577 protected historical/B-v1 files and 63 hashed audit artifacts match. No model requests, bridge connections, ledger changes, B-v1 edits or changes to the original 36-request plan.

This recovery record supersedes the earlier audit acceptance note that final synchronization was pending; the historical audit record remains unchanged.
