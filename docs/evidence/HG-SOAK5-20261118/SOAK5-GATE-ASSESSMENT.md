# Soak5 Gate Assessment — 2026-11-18

## Decision

**This Soak5 attempt is BLOCKED / deterministically INCOMPLETE. Do not report PASS.**

The original driver and logs are preserved in place; this assessment does not stop or alter the active run, change counters, insert ticks, restart the staging process, or affect production.

## Driver acceptance rules

Source: g_soak4.sh, SHA-256 07d7e0251a510a4456d21ed01f73b60c23156c49cdca14aca5ad8a111e4914f9.
- Tick period: 1,800 seconds.
- Maximum allowed unobserved gap: 3,600 seconds.
- The verdict function sets INCOMPLETE when the longest gap is greater than GAP_MAX.
- The verdict function also sets INCOMPLETE whenever ENVREC is nonzero.
- Tick observations include the driver's boot identity and suspend-time measurement; missing intervals are not counted as stable time.

## Exact observed state

- Window start: 2026-11-18 01:46:30 +07.
- Window target end: 2026-11-19 01:46:30 +07.
- Snapshot: 2026-11-18 15:41:59 +07.
- Observed elapsed: 14 hours, 0 minutes, 3 seconds.
- Tick rows: 24; RUN=23; OK=23; SKIP=1; FAIL=0.
- ENVREC=1; ENVFAIL=0; REBOOTS=0; PIDCHG=0.
- Longest gap: 6,935 seconds = 115.58 minutes (limit 3,600 seconds).
- Second gap above limit: 3,888 seconds = 64.80 minutes.
- Unobserved time calculated by the driver's own formula: 9,700 seconds.
- The one initial SKIP was due to GitHub quota being below 30; it is recorded as observed, not verified.

The driver's current verdict logic therefore has two independent INCOMPLETE conditions already true: LONGEST_GAP > GAP_MAX and ENVREC > 0. Further successful ticks cannot reverse either historical fact. The 24-hour window has not ended yet, so this is a gate assessment, not the driver's final end-of-window summary.

## Source evidence hashes

| Source | SHA-256 |
|---|---|
| g_soak4.sh | 07d7e0251a510a4456d21ed01f73b60c23156c49cdca14aca5ad8a111e4914f9 |
| state.env | cc4275693d3130c681ce9900eb213ca438c71b6c89d07fd560a52620b6f326e2 |
| ticks.tsv | 8fddd71732a7699e514ec1ff5852968285e9d82ecf9c047f9489122f0db872b5 |
| soak.log | 2322d2b1a76e3b45a4cd41f0a97c9fd6347f7989555af93780f382843b1de831 |
| availability.json | 437730c85cf358725b8489774d7206f663c2dec9871179ee171fd9d1ad6d3ed6 |
