# Release candidate source check — main 2201ab9 (cloud, 2026-11-20)

`python3.13 -B -m hg.release build --repo . --commit 2201ab998951fd5e48159657bc589d38f86113fb` was run twice in the cloud (Linux x86_64, Python 3.13.18).
- The two archives and manifests are **byte-identical**.
- `hg.release verify` → `VERIFIED`, 411 files, tree `05766663df63f2368ba345ac896456988d1af165`.
- Cloud archive sha256 `c7132687…`; cloud release id `1e5b4382…`.

The candidate for the staging soak must be built **on the phone**: the release id differs by zlib. That device build is also done twice and compared, and its tree must equal `05766663…`. Owner decision D-04: build and soak start only after P3-B reboot acceptance passes.
