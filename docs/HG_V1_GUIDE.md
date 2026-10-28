# HG v1 — Hướng dẫn dùng trên điện thoại

Dành cho Chủ Nhân, chạy trong Termux. Mọi thứ nằm trên máy: ghi chú, model, câu trả lời. Không có gì gửi ra ngoài trừ khi Chủ Nhân tự chọn `--provider anthropic`.

## 1. Cách nhanh nhất: gõ `hg`

```
hg
```

Một dấu nhắc `HG>` hiện ra:

| Gõ | HG làm |
|---|---|
| `Lần cuối thay dầu xe khi nào?` | Trả lời từ ghi chú, mỗi câu có nhãn |
| `+ Thay dầu xe ngày 15/10 ở 19.000 km` | Lưu ghi chú |
| `/tim bao hiem` | Tìm ghi chú (gõ không dấu cũng được) |
| `/kiem Họp lúc 9 giờ thứ Năm` | Đối chiếu một câu với ghi chú |
| `/q` | Thoát |

## 2. Đọc nhãn câu trả lời

| Nhãn | Nghĩa |
|---|---|
| `[N2·12/10]` | Câu này khớp ghi chú N2, ghi ngày 12/10 |
| `[?]` | Model tự nói, HG không tìm thấy trong ghi chú — chưa kiểm chứng |
| `[≠N2]` | **Mâu thuẫn** ghi chú N2 (sai số, sai ngày, sai tên hoặc đảo phủ định). Dòng `↳` cho biết sai chỗ nào |
| `[!]` | Model trích một ghi chú không có hoặc không khớp |

Dòng cuối tóm tắt, ví dụ: `— 2 câu có nguồn · 1 câu model tự nói · ollama:qwen3:1.7b · 6.2 giây`.

HG tự kiểm từng câu bằng cách so từ ngữ, số, ngày, tên và phủ định với ghi chú. Một câu chỉ được nhãn nguồn khi ghi chú đó nói đúng chủ đề Chủ Nhân hỏi và có đủ phần thông tin câu trả lời thêm vào. Đây không phải hiểu nghĩa sâu: câu diễn đạt rất khác ghi chú có thể bị gắn `[?]` dù đúng.

Câu hỏi về việc riêng của Chủ Nhân (có "tôi", "mình", "nhà mình"…) mà không có ghi chú nào đúng chủ đề thì HG tự trả lời "Ghi chú chưa có thông tin này." và không hỏi model, để tránh model đoán mò.

### Ghi chú có câu lệnh nhắm vào AI

Nếu Chủ Nhân lưu một tin nhắn lạ kiểu "SYSTEM: bỏ qua mọi hướng dẫn…", HG vẫn hiện nó (có dấu ⚠) nhưng **không gửi cho model** và không bao giờ dùng nó làm nguồn. Nếu đó là ghi chú của chính Chủ Nhân (ví dụ một prompt mẫu cho công việc) và an toàn, gỡ cách ly bằng:

```
hg note trust M-000012-ab12cd
```

Việc gỡ được ghi vào sổ cái. Bộ phát hiện chỉ là lớp bảo vệ thêm (có thể bỏ lọt hoặc nhận nhầm); bảo vệ chính vẫn là nhãn HG tự tính.

## 3. Ghi chú

```
hg note add "Bảo hiểm xe máy hết hạn ngày 2027-03-01"     # lưu
echo "Ghi chú dài nhiều dòng" | hg note add               # lưu từ văn bản khác
hg note add --subject xe "Thay dầu ngày 2026-09-15"       # lưu theo chủ đề
hg note search bao hiem                                    # tìm
hg note list                                               # 20 ghi chú mới nhất
hg note show M-000003-7292b0                               # mọi phiên bản của chủ đề
hg note forget M-000003-7292b0                             # thu hồi (vẫn còn trong lịch sử)
hg note trust M-000003-7292b0                              # gỡ cách ly cho một ghi chú an toàn
```

Cùng một `--subject` mà nội dung khác, HG từ chối (mã 4) và chỉ ra ghi chú cũ. Muốn thay, ghi rõ: `hg note add --subject xe --replaces M-000002-5f4a22 "Thay dầu ngày 2026-10-01"`.

`forget` **không xoá**: HG giữ lịch sử để biết ghi chú đã đổi thế nào. Ghi chú nằm trong `~/.local/share/hg/assistant/notes.jsonl` (chỉ Chủ Nhân đọc được, quyền 600).

## 4. Hỏi, đối chiếu, tóm tắt

```
hg ask "Họp nhóm HG lúc mấy giờ?"
hg ask --notes-only "bảo hiểm"            # không gọi model, chỉ đưa ghi chú
hg ask --json "..."                        # biên nhận đầy đủ dạng JSON
echo "Mai họp lúc 21 giờ nhé" | hg check   # tin nhắn này có khớp ghi chú không
hg summarize bien-ban.txt                  # tóm tắt trích nguyên câu, có số dòng [L3]
hg summarize --model bien-ban.txt          # model viết, HG kiểm từng câu với dòng được trích
hg summarize --model --strict bien-ban.txt # bỏ câu nào không neo được vào dòng nguồn
termux-clipboard-get | hg summarize -      # tóm tắt nội dung vừa sao chép (cần Termux:API)
```

`summarize` chỉ nhận file văn bản UTF-8 tối đa 1 MB. PDF chưa hỗ trợ trong v1.

## 5. Model trên máy

```
hg model status                 # Ollama có chạy không, model nào, đã ghim chưa
hg model use qwen3:1.7b         # chọn model và ghim mã (digest) của nó
sv up ollama / sv down ollama   # bật / tắt dịch vụ Ollama
```

HG ghim digest của model: nếu có ứng dụng khác thay model qua Ollama, HG từ chối chạy (mã 78) cho tới khi Chủ Nhân chạy lại `hg model use`.

Model tắt hoặc chưa tải: `hg ask` vẫn chạy, đưa nguyên văn ghi chú liên quan (mã 3), không bịa câu trả lời.

## 6. Mã thoát (dùng trong script)

| Mã | Nghĩa |
|---|---|
| 0 | Xong |
| 2 | Đầu vào không hợp lệ |
| 3 | Không có model — chỉ đưa ghi chú |
| 4 | Mâu thuẫn ghi chú (note add cùng chủ đề; check có câu mâu thuẫn) |
| 5 | Không tìm thấy gì |
| 75 | HG khác đang ghi, thử lại sau vài giây |
| 78 | Thư mục, cấu hình, sổ cái hoặc model không an toàn — đọc thông báo |

## 7. Khi có lỗi

| Hiện tượng | Cách xử lý |
|---|---|
| `Sổ cái hỏng hoặc không đọc được … Chạy: hg repair` | `hg repair` — HG sao lưu file rồi bỏ đúng dòng cuối bị cắt (xảy ra khi Android tắt Termux giữa lúc ghi). Hỏng ở giữa file thì HG không tự sửa |
| `model MISSING` | `ollama pull qwen3:1.7b` rồi `hg model use qwen3:1.7b` |
| `supervised Ollama is not running` | `sv up ollama` |
| `digest changed` | Kiểm tra lại, rồi `hg model use <tên>` để ghim lại |
| `HG_BLOCKED: hg-runtime failed … held down` trong log dịch vụ | Dịch vụ khởi động lỗi 5 lần liên tiếp nên HG tự giữ dừng để không tiêu hết lượt gọi GitHub. Xem `tail $PREFIX/var/log/sv/hg-runtime/current`, sửa nguyên nhân (thường là mất mạng), rồi `sv up hg-runtime` |
| Trả lời chậm lần đầu | Lần đầu phải nạp model vào RAM (vài giây); các lần sau nhanh hơn trong 30 phút |

## 8. Dịch vụ hg-runtime (máy chủ cục bộ)

`hg-runtime` vẫn chạy như trước ở `127.0.0.1:18766` (ghi/đọc file có xác minh qua `POST /v1/tasks`). Kiểm tra:

```
sv status hg-runtime
T=$(cat ~/.config/hg/runtime-service.token); curl -s -H "Authorization: Bearer $T" http://127.0.0.1:18766/v1/health/ready; unset T
```

## 9. Giới hạn của v1

- Kiểm tra câu là kiểm tra từ vựng, không phải suy luận ngữ nghĩa.
- Không chống được chương trình chạy cùng tài khoản Termux (quyết định Q3).
- Lệnh `hg` là lệnh trực tiếp của Chủ Nhân; nó không đi qua cổng quản trị của runtime HG.
- Phát hiện câu lệnh nhắm vào AI theo mẫu: có thể bỏ lọt cách viết mới; tỉ lệ bắt được trên dữ liệu chưa thấy chưa đo được (UNVERIFIED).
- Chưa có: PDF, giọng nói, hỏi đáp qua HTTP, lối tắt màn hình chính.
