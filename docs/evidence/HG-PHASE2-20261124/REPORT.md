# HG đợt 2 — niêm phong staging và phục hồi Termux

Ngày 24/11/2026, giờ Việt Nam. Scope gồm staging trên OPPO và nhánh `stt/hg-phase2-seal-20261124`. Baseline là `5201ac1c64345183d2e3c30f6e5a3890d395dd6e`. Mọi quyết định tích hợp và triển khai vẫn theo [Evidence Ledger §85](https://github.com/OAI-GIANG/HG/blob/889a117612601c9b1ff6f591fa9b7aafc3cf5911/docs/governance/HG_MASTER_COMPLETION_LEDGER_V1_RECONCILIATION_20261110B.md#85-owner-approval-2026-11-24-07--ac-a6-pass-for-the-pinned-candidate).

## Niêm phong log

- Ca hồi quy chạy trên mã cũ với một rehearsal fixture thất bại ở bước build, sau đó chạy đường finalize thật. Lần kiểm tra hash đầu trả 1 với `rehearsal.log: FAILED`. Ca này kiểm tra cả trạng thái thất bại được ghi ở cuối log.
- Bản sửa `495e18fc9edd88fd7a8256105f2d2d485d01cdf4` ghi xong kết quả cuối rồi mới băm. Manifest được ghi vào tệp tạm và đổi tên khi thành công. Lỗi niêm phong trả mã lỗi. Thư mục bằng chứng phải tạo mới trước khi chạy.
- Bộ staging 13/13 đạt trên Linux Python 3.13 và trên OPPO Termux. Diễn tập thật trên OPPO đạt `SWITCH_OK`, J2 `CLOSED_VERIFIED`, J1 `ANSWERED_NO_ACTION`, `RESTORED`, `ROLLBACK_READY_VERIFIED`. Luồng này dùng runner SHA mới và ứng viên AC-A6 không đổi, `40254e60802bc59e40cd739d6ae4081241af4acd`, release `95df7ed9e62f83fe32807a625da4952d191342d1babd2ba19945132dff676153`.
- Lần kiểm tra `sha256sum -c SHA256SUMS` đầu trên máy đạt **24/24**, exit 0. [Đầu ra kiểm tra lần đầu](first-check.log). Manifest SHA-256 `1615747dd1b32626f80f72752ca8d1da1a98032d2df7d646e86b515be4d0a31c`. Log hoàn chỉnh SHA-256 `639f15f4ceaa7f5af59ac472c44c3a1ab1030687f542b9046480cfe3df984768`.
- So sánh production trước và sau: **0 byte khác biệt**. Rehearsal báo 0 tiến trình staging sót lại.

## Tác nhân phục hồi ngoài Termux

- Trên máy thấy APK `com.termux.api` và `com.termux.boot`. Không xác nhận được `org.hg.cim.broker` qua truy vấn package của Termux.
- Boot hook và profile hook có trên thiết bị. Boot hook cần sự kiện khởi động máy. Profile hook cần một phiên được mở. Runit, RDC và watchdog hiện ở cùng hệ sinh thái tiến trình Termux.
- Trước probe, Termux:API trả `No jobs found`. Job một lần `40328` được đăng ký sau khi cả nhóm runit của fixture riêng đã dừng. Android gọi script, khởi tạo supervisor và child mới. Sau dọn fixture, Termux:API trả `No jobs found`, PID của production và watchdog khớp trước–sau. [Kết quả thăm dò fixture](jobscheduler-fixture-result.json)
- Job Android một lần `41577` được đăng ký trước khi dừng nhóm tiến trình HG staging riêng. Sau khi Android bắt đầu job, bộ thử dừng cả nhóm. Job phát hiện supervisor cũ biến mất và tự khởi động supervisor mới. Endpoint xác thực trả lại READY trên cùng release `95df7ed9…`, integrity VERIFIED, trust LOADED và idempotency USABLE. Cổng thử 18873 đã đóng, production giữ nguyên PID và danh sách job sau dọn trống. [Kết quả phục hồi HG staging](hg-staging-recovery-result.json)
- **Soak chưa mở.** Job một lần chỉ hoạt động trong ca staging có bộ thử điều phối, với ứng dụng Termux đang chạy. Chưa chứng minh khôi phục tự động khi Android dừng ứng dụng Termux, chưa có lịch phục hồi dài hạn được kiểm chứng, và chưa thực hiện kiểm tra sau reboot theo D-04.

## Trạng thái giữ cổng

PR #217 vẫn HOLD. RDC báo `not_found`, `retry_original=false` cho `e6827410-634b-403d-9e86-620225e861b3`. PR #219 vẫn Draft. Main, ref ứng viên, các danh sách dry-run và worktree của Chủ Nhân được giữ. **Production NO-GO.**
