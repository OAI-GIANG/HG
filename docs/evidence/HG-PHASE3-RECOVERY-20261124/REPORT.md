# HG đợt 3 — điều kiện thử phục hồi toàn ứng dụng Termux

Ngày 24/11/2026, giờ Việt Nam. Bắt đầu từ hồ sơ đợt 2 tại `7af214df09b41f8da564f1f90814acef932e3b11`.

## Bằng chứng và phạm vi

| Trường | Đợt 2 trên nhóm HG staging | Đợt 3 trên OPPO |
| --- | --- | --- |
| Tác nhân | Termux:API chuyển job Android một lần `41577` đến script phục hồi | Chưa có tác nhân phục hồi sau mất toàn ứng dụng được chứng minh. Termux:API trả `No jobs found` ở preflight. |
| Sự kiện gián đoạn | Nhóm runit staging riêng bị dừng. Job ghi nhận mất supervisor lúc 22:08:28 +07. | `NOT_EXECUTED`. Không có mốc gián đoạn mới để ghi. |
| SHA và release | `40254e60802bc59e40cd739d6ae4081241af4acd`, `95df7ed9e62f83fe32807a625da4952d191342d1babd2ba19945132dff676153` | Preflight production lúc 23:04:54 +07 là release `030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5`, source `4eaac81132ae57028cf2432eec911a01b6ecf1fd`. |
| Readiness | HTTP 200 READY cùng release, integrity VERIFIED, trust LOADED. File bằng chứng ghi chính xác thời điểm job thấy supervisor biến mất. | HTTP 200 READY có xác thực, integrity VERIFIED, trust LOADED, idempotency USABLE ở **preflight**. Chưa có trạng thái sau phục hồi toàn ứng dụng. |

Nguồn đợt 3 gồm [preflight trên OPPO](preflight.json). Nguồn đợt 2 là [kết quả thử JobScheduler](../HG-PHASE2-20261124/hg-staging-recovery-result.json). Evidence Ledger §72 ghi rõ job 4211 trước đây im lặng trong các lần toàn cây mất và hai lần khôi phục quan sát được đi qua profile hook. §73 giữ D-04 chờ kiểm tra reboot. [Ledger](https://github.com/OAI-GIANG/HG/blob/7af214df09b41f8da564f1f90814acef932e3b11/docs/governance/HG_MASTER_COMPLETION_LEDGER_V1_RECONCILIATION_20261110B.md#72-addendum-2026-11-22-0203-0240-07--p3-d-stabilization-and-loss-of-observability-fix)

## Điểm nghẽn đã kiểm tra

Trên OPPO, bốn tiến trình HG, Ollama, RDC và watchdog cùng dùng UID Termux 10460. Dừng toàn ứng dụng hiện tại sẽ làm gián đoạn production và mất kênh quan sát RDC cùng lúc. Kiểm tra preflight thấy Termux:API và Termux:Boot, cùng checksum boot và profile hook. Các dữ kiện này chưa chứng minh có một trigger hoạt động độc lập sau khi Termux mất. Phiên này chưa thấy kênh ngoài ứng dụng có thể quan sát xuyên suốt sự kiện trên OPPO. Truy vấn package Broker từ Termux chưa xác nhận được package.

## Cách chấp nhận thử nghiệm khi có môi trường thích hợp

1. Dùng môi trường Android cách ly khỏi Termux production và có kênh quan sát độc lập. Ghim source, manifest và release staging. Kiểm tra READY có xác thực trước thử. Ghi boot ID, các PID/UID và mốc thời gian từ kênh ngoài.
2. Ghi chính xác dạng sự kiện Android đã quan sát. Phân tích mất tiến trình tự nhiên, thao tác Force stop và reboot như các sự kiện riêng. Lưu bằng chứng toàn bộ tiến trình của ứng dụng thử đã mất. Dừng nếu tác động có thể lan sang worktree hay runtime production.
3. Ghi ID/thời điểm Android gọi trigger, thời điểm runtime đổi PID và HTTP READY đầu tiên sau phục hồi. So SHA hoặc release ID, integrity và trust với manifest đã ghim. Nếu cần mở Termux hoặc khởi động tay, ghi đó là phục hồi thủ công. Đóng dấu hash sau khi log đã ghi xong.
4. Kiểm tra D-04 riêng bằng bằng chứng sau reboot được ủy quyền, gồm boot ID mới và chuỗi startup đến READY. Chỉ mở soak khi cả phục hồi tự động và kiểm tra D-04 đã đạt.

**Trạng thái**: phục hồi toàn ứng dụng `NOT_EXECUTED`, D-04 `NOT_RUN`, soak 24 giờ `NOT_STARTED`. PR #217 vẫn `HOLD` vì RDC `e6827410-634b-403d-9e86-620225e861b3` trả `not_found` và `retry_original=false`. Dry-run được giữ, production `NO-GO`.
