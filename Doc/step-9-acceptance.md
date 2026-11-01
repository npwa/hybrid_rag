# Step 9 acceptance walkthrough (plan §5.8)

Status as of 2026-11-01. "Done" means I ran it; "Owner" means it needs you (it touches the live Signal path, your login session or time).

| # | Step | Result |
|---|---|---|
| 1 | Demo mode walkthrough of all four pages with the "MCP server down" narrative | Done in part: every page is exercised against the demo data by the browser tests (index, explorer, analytics, tool calls, gold). The narrative walk-through itself is **Owner** (open `./run_console.py --demo`). |
| 2 | Real data, localhost only: page 1 equals the manifest; page 4 shows the router-IP question with time to tool; page 2 explains a chosen query; page 3 has two weeks of JSONL | Page 1: `triage.sh 10` checks the summary against the manifest (2,539 files, match). Page 3: **not met yet**, JSONL history starts 2026-10-30 (a few days at most), so two weeks accumulate by mid-November. Pages 2 and 4: **Owner** to eyeball. |
| 3 | Stop the MCP server: header, page-4 flag and `triage.sh 1` agree | **Owner.** I did not stop the live MCP server (it carries your Signal traffic). The tests cover the three views with a fake down server. |
| 4 | Read-only proof (checksums before/after) | Done: `scripts/verify_readonly.sh` on real data, 1,780 files unchanged. |
| 5 | README wording against the honesty constraint | Done in my pass: README says what is built, and states the sign-off is pending. Please read it once. |
| T-ISO-2 | Signal path unaffected for 24 h with the console running | **Owner / time.** The console has been running on real data since 2026-10-31 and no Signal failure has been attributed to it; a clean 24 h record needs your confirmation. |
| HYR-01 | Reboot the desktop; port 8200 listens with no manual action | Installed 2026-11-01: both units enabled and active, lingering on (checked). Only the real reboot test is outstanding. Original steps: `scripts/install_services.sh --enable`, `loginctl enable-linger $USER`, reboot, `scripts/triage.sh 1`. |
