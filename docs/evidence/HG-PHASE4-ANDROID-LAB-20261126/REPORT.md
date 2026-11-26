# HG đợt 4 — phục hồi Termux trên Android cách ly

Ngày 26/11/2026, giờ Việt Nam. Mốc đầu vào [hồ sơ đợt 3](../HG-PHASE3-RECOVERY-20261124/REPORT.md) tại commit `4823924599091e5b1ceae6adc0b3476a2a9ae9a0`.

| Hồ sơ | Giá trị |
| --- | --- |
| Mã HG staging | `40254e60802bc59e40cd739d6ae4081241af4acd` |
| Release ID | `95df7ed9e62f83fe32807a625da4952d191342d1babd2ba19945132dff676153` |
| Thiết bị thử và kênh quan sát | Android AOSP API 35, giả lập x86_64 riêng của GitHub Actions. ADB và HTTP qua ADB forward từ máy chạy CI. |
| Phần mềm thử | Termux 0.118.3, Termux:API 0.53.0, Termux:Boot 0.8.1. Cả ba APK F-Droid có cùng chữ ký đã ghim. |
| Ca đầu | [Run 45833915262](https://github.com/OAI-GIANG/HG/actions/runs/45833915262). HTTP 200 READY lúc 20:57:53.939 +07. Bộ thử dừng tại kiểm tra danh sách job trống, trước sự kiện gián đoạn và reboot. |
| Ca chạy lại | [Run 45834802048](https://github.com/OAI-GIANG/HG/actions/runs/45834802048) ở SHA `3973dfb012721e1e5df4c64dae197e6455414fe1`. |

Giả lập cho phép thử dừng toàn UID và reboot cách ly. Tín hiệu SIGKILL theo kịch bản ADB mô phỏng mất tiến trình. Tác vi riêng như áp lực bộ nhớ trên ColorOS và Force stop cần ca thử riêng. Không có thao tác dừng ứng dụng hay reboot OPPO production.

## Ca 45834802048

Các mốc dưới đây dùng giờ Việt Nam. Hồ sơ trích từ artifact gồm [timeline](run-45834802048/timeline.tsv), [trigger](run-45834802048/triggers.tsv), [xác minh](run-45834802048/verification.json) và [kết quả kiểm tra hash](run-45834802048/artifact-integrity.txt).

| Sự kiện | Bằng chứng |
| --- | --- |
| READY trước thử | 21:03:21.278, HTTP 200 có xác thực, HG PID 2983. |
| Gián đoạn | 21:03:21, ADB gửi SIGKILL đến năm PID đã ghi nhận thuộc UID thử 10148. Endpoint không còn READY lúc 21:03:27. Ảnh tiến trình sau kill đã có PID mới 3089 của Termux:API. Chưa quan sát được UID trống. |
| JobScheduler | JobScheduler Android xác nhận đăng ký job 41226. Kịch bản bật điều kiện sạc lúc 21:03:27. Job chạy lúc 21:03:27 và tạo HG PID 3171. HTTP 200 READY đầu tiên lúc 21:03:31.887, trên manifest đã ghim. |
| Reboot D-04 trong lab | Reboot giả lập lúc 21:03:31. Boot ID đổi từ `7e936071-3b1e-4539-93bf-15c6282324ea` sang `ad6d0d85-df89-44a6-8260-a38f6ca83e89`. Termux:Boot gọi script lúc 21:04:05, HG PID 1925. HTTP 200 READY đầu tiên lúc 21:04:09.784. |
| Hash gói bằng chứng | 25/25 mục qua SHA256SUMS sau khi tải artifact. |

## Ca 45835480103

[Run 45835480103](https://github.com/OAI-GIANG/HG/actions/runs/45835480103) ở SHA `95d29f061517c55701da67d2632819ab9409d859` bổ sung lấy mẫu tiến trình UID ngay trong phiên ADB sau SIGKILL và nhật ký tiến trình Android. Giả lập khởi động nhưng không thấy script bootstrap chạy và hết hạn chờ READY lúc 21:11:17 +07. Ca này dừng trước SIGKILL và reboot. Gói artifact qua 7/7 mục SHA-256. [Timeline](run-45835480103/timeline.tsv).

## Ca 45836657722

[Run 45836657722](https://github.com/OAI-GIANG/HG/actions/runs/45836657722) ở SHA `80e7603f31bef07c82539db98d9e395adfb51be7` dừng khi kênh ADB khởi tạo lại lúc Android boot. Log job ghi `adb: unable to connect for root: closed` lúc 21:13:59 +07, trước khi triển khai staging. Gói artifact qua 5/5 mục SHA-256. Ca tiếp theo chờ kênh ADB ổn định rồi kiểm tra lại UID và dấu hiệu giả lập trước mỗi lần thử.

## Ca quyết định 45837175656

[Run 45837175656](https://github.com/OAI-GIANG/HG/actions/runs/45837175656) tại commit kiểm thử `0a610f518e0168c112894edf88947ea7c7740b44`. [Timeline](run-45837175656/timeline.tsv), [trigger](run-45837175656/triggers.tsv), [nhật ký tiến trình Android](run-45837175656/android-process-events.txt), [đối chiếu máy đọc](run-45837175656/verification.json).

| Sự kiện | Giờ Việt Nam | Bằng chứng |
| --- | --- | --- |
| READY trước thử | 21:18:16.160 | HTTP 200 có xác thực. HG PID 3057, đúng release, integrity VERIFIED, trust LOADED và idempotency USABLE. |
| Gián đoạn | 21:18:16 | SIGKILL từ kênh ADB trong giả lập. Năm PID 2387, 2458, 2529, 2620 và 3057 thuộc UID thử 10148. ADB ghi mẫu UID trống ngay sau kill, HTTP READY mất. Android ghi `am_proc_died` của Termux, Termux:API và Termux:Boot. |
| Điều kiện của job 41226 | 21:18:17 | JobScheduler có đăng ký job trước gián đoạn. Bộ thử bật điều kiện sạc lúc này. |
| Hết cửa sổ phục hồi | 21:19:47 | 90 giây quan sát sau khi bật điều kiện sạc. Không ghi nhận JobScheduler gọi script, không có PID mới của HG, không có HTTP READY. Mẫu UID vẫn trống. Cổng phục hồi toàn ứng dụng **FAIL trong cửa sổ quan sát**. |
| Reboot D-04 trong lab | 21:19:47 | Boot ID đổi từ `963680f7-0968-4be3-9297-49c5249b3915` sang `8200ae87-3761-49b9-b8c4-727e1c8cfc70`. |
| Tác nhân sau reboot | 21:20:28 | Termux:Boot gọi script `hg-phase4.sh`, HG PID mới 1934. Không có thao tác mở giao diện Termux sau reboot. |
| READY đầu tiên sau reboot | 21:20:32.268 | HTTP 200 có xác thực, cùng release, integrity VERIFIED, trust LOADED, idempotency USABLE. **D-04 đạt trong lab AOSP**. |
| Toàn vẹn bằng chứng | Sau khi tải lại artifact | 28/28 mục đạt SHA256SUMS. [Kết quả đối chiếu](run-45837175656/artifact-integrity.txt). |

Job 41226 ở ca 45834802048 đã khôi phục HG khi mẫu sau kill có sẵn một PID Termux:API. Ca 45837175656 là ca xác minh mất toàn UID và có kết quả phục hồi khác. Trạng thái CI xanh của ca quyết định xác nhận bộ đo chạy tới cuối và xuất bằng chứng. Cổng phục hồi lấy kết quả từ timeline và tiến trình quan sát. Nhật ký hiện có chưa xác định nguyên nhân JobScheduler không gọi script trong 90 giây.

## Quyết định

- **Soak 24 giờ chưa mở.** Phục hồi sau khi toàn UID mất chưa đạt. D-04 chỉ được kiểm chứng trên giả lập Android cách ly. Cần Android staging chạy liên tục với kênh quan sát độc lập cho ca soak, vì mỗi GitHub-hosted job tối đa 6 giờ. [Giới hạn GitHub Actions](https://docs.github.com/en/actions/reference/limits).
- **PR #217 HOLD.** GitHub vẫn hiển thị draft mở, head `9c694267079f6a739258bc3b31192cff99396094`. RDC của call `e6827410-634b-403d-9e86-620225e861b3` trả `not_found`, `retry_original=false`. Cần bằng chứng kết thúc hoặc hết khả năng thực thi trước khi xử lý PR. Không gửi lệnh merge.
- **Production NO-GO.** Worktree của Chủ Nhân và cấu hình production được bảo toàn. Các danh sách [dry-run](../HG-PHASE1-20261124/REPORT.md) vẫn ở trạng thái khảo sát.
- **Bước tiếp theo.** Thu trạng thái job 41226 và lý do bị giữ ngay sau thay đổi điều kiện sạc, trong lúc UID vẫn trống. Thử lại trên Android cách ly. Muốn đạt cổng cần chuỗi bằng chứng UID trống, tác nhân thực sự được Android kích hoạt, PID HG mới và HTTP 200 READY đúng release.
