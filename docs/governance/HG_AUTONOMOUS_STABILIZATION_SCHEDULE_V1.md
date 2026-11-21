# HG — Autonomous Stabilization Schedule V1

Nguồn: chỉ thị Chủ Nhân 2026-11-22 02:02 +07 *HG — Autonomous Stabilization & Completion Mission, Master Execution Directive V1.0*.
Tài liệu này là lịch điều phối duy nhất của chiến dịch. Trạng thái nghiệm thu R1–R14 nằm trong `HG_MASTER_COMPLETION_LEDGER_V1.csv` (các dòng `R*`), bằng chứng chi tiết nằm trong ledger `HG_MASTER_COMPLETION_LEDGER_V1_RECONCILIATION_20261110B.md` §72 trở đi.

Các quyết định vẫn còn hiệu lực, chỉ thị này không thay thế:
- OD-IR-20261109 (`docs/governance/OWNER_DECISION_OD-IR-20261109.md`).
- Stabilization mode 2026-11-13.
- D-01..D-05:
  - Production chỉ được đọc.
  - Không nâng cấp Ollama production.
  - Không đổi trust registry hay listener policy.
  - Soak 24 h chỉ chạy sau khi kiểm tra reboot đạt.
  - Claude không reboot và không đổi cài đặt Android.

## 1. Baseline Giai đoạn 0 — 2026-11-22 02:03 +07 (OBSERVED, đọc trực tiếp)

| Mục | Giá trị |
|---|---|
| `main` | `2201ab9` (#207, P3 Strategy C) |
| Thiết bị | PKC110, Android 17, Termux uid 10460, aarch64; boot id `1b823ef0…`, uptime 5 ngày 9 giờ |
| Production | pointer → release `030a88d5…`; một runsvdir (pid 3203, khởi động 2026-11-22 00:50:09); `hg-runtime`, `ollama`, DC remote/watchdog chạy; `hg-staging-soak`, `sshd`, `ssh-agent` ở trạng thái down |
| Entrypoint | `hg-ensure-services.sh` `3acc0785…`, profile hook `e1fd7e2e…`, boot hook `618f5856…`: trùng khớp `main` |
| Health (token thật, loopback) | `/v1/health/live` 200 LIVE; `/v1/health/ready` 200 READY, release `030a88d5…` |
| `~/HG` | `stt/hg-h1.3.1-idempotency-progress` @`2a80f4f`, 4 mục dirty; 43 worktree, 24 worktree dirty, tổng 429 mục (không đổi so với P1 20/11) |
| PR mở | #205 draft (cổng L5 đỏ, giữ cùng #77 theo D2); #206 draft (G3-1, đã hoãn); #77 HOLD (D2); #64 DEFERRED_V2 |
| Manifest bảo toàn | trên máy: `~/hg-evidence/P0-BASELINE-20261122/` (`WORKTREE_PRESERVATION_MANIFEST.json` `4b388f43…`, `PRODUCTION_BASELINE.json` `12925719…`, `SHA256SUMS`) |

## 2. Phát hiện Giai đoạn 0–1

- **F-P3D-1 (P0)** — Android giết toàn bộ cây Termux trong cùng một boot.
  - Có 54 lần svlogd của `hg-runtime` kết thúc không sạch (`*.u`).
  - Hai lần gần nhất đều được khôi phục bởi `source=profile` (Chủ Nhân mở Termux):
    - 2026-11-21 03:35;
    - 2026-11-22 00:50.
  - Lần mất dịch vụ gần nhất kéo dài khoảng 14 h 50 m. Cận dưới là lần CHECK_OK cuối của guard (21/11 09:55), cận trên là STARTED (22/11 00:50). Đây là INFERENCE trong khoảng hai mốc trên.
- **F-P3D-2** — Job 4211 (guard 15 phút) có chạy, nhưng chỉ khi cây Termux còn sống.
  - Lịch sử CHECK_OK:
    - 18/11 đến 15:18;
    - 21/11 từ 03:39 đến 09:55;
    - 22/11 từ 01:48.
  - Job im lặng trong mọi khoảng mất dịch vụ, tức là nó chung miền lỗi với Termux, không phải bộ kích hoạt ngoài.
  - Điều này chỉnh lại câu "không chạy kể từ 2026-11-18 15:18" ở §67.
- **F-EV-1 (P1)** — Mỗi shell đăng nhập (Chủ Nhân hoặc một lệnh Desktop Commander) ghi 2 dòng routine vào `ensure.log` (giới hạn 16 KiB).
  - Các dòng hiếm như ABSENT_VERIFIED, STARTED và các dòng boot bị đẩy ra sau khoảng 80 shell.
  - Hậu quả: bằng chứng P3 và kiểm tra hậu-reboot D-03 có thể mất trước khi kịp đọc.
  - Sửa trong PR của §72 bằng `events.log`.
- **F-P3D-3** — Cờ phantom-process (`settings_enable_monitor_phantom_procs`) không đọc được từ uid ứng dụng (SecurityException), nên trạng thái là UNKNOWN.
  - Android 14+ có công tắc trong Tùy chọn nhà phát triển: "Disable child process restrictions" (tắt hạn chế tiến trình con).
  - Nguyên nhân giết cây (phantom-killer, LMK hay ColorOS freeze) vẫn chưa phân biệt được, vì Termux không đọc được logcat, `/proc/stat` hay `/proc/pressure`.
- **Quan sát** — RAM đang dùng 14.3/15.4 GB, swap 4.1 GB. Ollama không giữ model nào trong bộ nhớ (`/api/ps` rỗng), nên áp lực bộ nhớ đến từ ngoài HG.

## 3. Lịch thực thi

| Giai đoạn | Nội dung | Phụ thuộc | Trạng thái | Việc kế tiếp |
|---|---|---|---|---|
| 0 Baseline | Mục 1 | — | DONE 2026-11-22 | — |
| 1 Termux reliability | F-EV-1 sửa; P3-A VERIFIED; P3-B reboot; P3-C VERIFIED (staging); P3-D | Chủ Nhân (mục 5) | IN_PROGRESS | Merge + cài `events.log`; Chủ Nhân bật cài đặt mục 5 rồi reboot; kiểm tra hậu-reboot chỉ đọc theo D-03 |
| 2 Reconcile | 43 worktree, 429 mục dirty (P1 preservation-first) | Manifest mục 1 | IN_PROGRESS | Phân loại SAME_AS_MAIN/DIVERGED/UNIQUE theo blob, bundle offline |
| 3 Backend/security | #205/#206 trên head SHA; SQLite TOCTOU/NOFOLLOW; idempotency | Giai đoạn 2 | HOLD theo D2/G3-1 | Chỉ sửa lỗi có finding P0/P1 |
| 4 AI/memory/model | Gateway, provenance, VN retrieval | Giai đoạn 3 | NOT_STARTED | — |
| 5 F-D4/F-W1 | Holdout v4 ≥ 40 câu theo protocol phương án A (Chủ Nhân 15/11), đóng băng SHA-256, chạy đúng 1 lần | Giai đoạn 4 | NOT_STARTED | Khôi phục protocol phương án A từ nguồn |
| 6 UI | Web UI hiện có | Giai đoạn 4 | NOT_STARTED | — |
| 7 Integration | Full suites theo SHA, soak 24 h (D-04) | P3-B đạt | BLOCKED (P3-B) | — |
| 8 Release | RC từ `main`, GO/NO-GO | Giai đoạn 7 + phê duyệt production riêng | NOT_APPROVED (D-05) | — |

## 4. Sở hữu workstream

Một người ghi cho mỗi workstream; agent kiểm toán chỉ đọc. TEAM 01–10 của chỉ thị được gộp như sau:
- Forensic/Release/Testing: Claude điều phối.
- Termux: một nhánh mỗi work package.
- Không có hai agent ghi cùng một tệp hay cùng một branch.

## 5. Việc chỉ Chủ Nhân làm được (giao diện Android, Claude không có quyền)

1. Tùy chọn nhà phát triển → bật **Disable child process restrictions** (tắt hạn chế tiến trình con). Trên ColorOS có thể mang tên khác; tìm "child process" hoặc "tiến trình con".
2. Theo handoff §B / D-03:
   - Auto-launch (Tự khởi chạy) cho Termux, Termux:Boot, Termux:API;
   - Pin: Không hạn chế / cho phép chạy nền;
   - khóa Termux trong Recents;
   - mở Termux:Boot một lần.
3. Reboot mà không mở Termux, rồi báo Claude. Claude chỉ kiểm tra chỉ đọc: boot id, `events.log` có `source=boot`, đúng một runsvdir, readiness 200, release `030a88d5`, hash không đổi.

## 6. Khôi phục phiên

Đọc tài liệu này → các dòng `R*` của CSV → §72 trở đi → `~/hg-evidence/` trên máy → kiểm tra process, lock, log thực tế trước khi tiếp tục. Không giả định tiến trình nền còn chạy.
