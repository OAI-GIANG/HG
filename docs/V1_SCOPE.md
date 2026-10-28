# HG v1 — Phạm vi, kế hoạch và tiêu chí đóng

- Task: `HG-V1-COMPLETION-20261028` (kế thừa `HG-V1-SCOPE-RESET`)
- Nhánh: `stt/v1-assistant-20261028`, base `main` @ `37f1627e3c96835be3ae1dc2ba002fd2a46ff2e8`
- Policy: MAEP-1.1.0 (giữ nguyên, Q4)
- Trạng thái tài liệu: PLAN v0.2 — đã qua thẩm định nội bộ (mục 9; phê bình nội bộ của các agent, KHÔNG phải review độc lập theo MAEP-021); kết quả thực hiện ở mục 10

## 1. Quyết định của Chủ Nhân (2026-10-28, nguyên văn: "chấp nhận tất cả đề xuất")

| # | Quyết định | Hệ quả |
|---|---|---|
| Q1 | v1 dùng `hg serve` trên `main`; `runtime.service` hoãn sang v2 | Phù hợp ADR-012 (hg serve vẫn là runtime vận hành tới khi 6 cổng chuyển đổi đạt); không sửa ADR |
| Q2 | Đóng băng nhánh `stt/maep-v1-20261022` tới khi xong v1 | Không commit lên nhánh đó trong task này |
| Q3 | Kẻ tấn công cùng UID nằm ngoài phạm vi v1 | Ghi là rủi ro còn lại (mục 6) |
| Q4 | Giữ MAEP-1.1.0 trên `main` | Không đổi `owner-grants.json`, không đổi policy |
| Q5 | Model mặc định: Ollama chạy local; API trả phí chỉ là tuỳ chọn bật tay | Không gọi API trả phí nếu Chủ Nhân không bật rõ ràng |
| Q6 | O-1…O-6 và A-1 hoãn cùng runtime.service | Không tạo policy/approval/session thay chủ |
| Q7 | Báo cáo task v1 dạng ngắn | Báo cáo cuối: trạng thái, thay đổi, test, bước tiếp |

Tính năng được chọn: F1, F2, F3, F4, F5.

## 2. Baseline đã xác minh

| Hạng mục | Bằng chứng |
|---|---|
| `main` @ `37f1627`, working tree sạch | `git rev-parse HEAD`, `git status --porcelain` → rỗng |
| Test: maep 304, hg 256, hooks 32 — OK | exit 0 cả ba |
| `hg selfcheck` PASS, `hg bench` 10/10 | exit 0 |
| Điện thoại (Termux, Android 15, aarch64, RAM 15,7 GB, trống 305 GB, Python 3.14.6) online | Desktop Commander `localhost` |
| `hg-runtime` chạy, `/v1/health/ready` = READY, integrity VERIFIED, trust LOADED @ `37f1627` | curl có xác thực; không xác thực → 401 |
| Release đang chạy: `f7cfd766…` build từ commit `f3dac34` (cũ hơn `main`) | `~/.config/hg/releases/f7cfd766….json` |
| `~/HG` trên điện thoại có 46 thay đổi chưa commit của Chủ Nhân trên nhánh runtime | `git status` — **không đụng vào** |
| Ollama chưa cài; gói Termux `ollama` có sẵn (candidate 0.40.6) | `apt-cache policy ollama` |

V1_REQUIRED #1 (xác minh `hg serve` trên điện thoại): **VERIFIED** bằng các dòng trên.

## 3. Bản sắc HG trong v1 — nói đúng mức

Kiểm tra trích dẫn sau khi model trả lời **không phải ý tưởng mới**: RARR (nghiên cứu, ACL 2023) và Vertex AI Check Grounding (dịch vụ đám mây) đã làm việc này. Nghiên cứu ALCE cho thấy khoảng một nửa câu trả lời của ChatGPT/GPT-4 trên ELI5 không được nguồn trích hỗ trợ đầy đủ (Gao và cộng sự, 2023) — đó là vấn đề HG giải quyết, không phải cách giải.

Điều HG làm khác, và là của riêng HG:

1. **Chạy hoàn toàn trên điện thoại, tiếng Việt trước tiên.** Bộ phân tích riêng cho tiếng Việt: bỏ âm tiết chức năng, ghép cặp âm tiết, gõ không dấu vẫn khớp, chuẩn hoá NFC — không dùng embedding, không gửi dữ liệu ra ngoài.
2. **HG tự phán, model chỉ gợi ý.** HG so từng câu với *mọi* ghi chú được truy xuất, không tin vào `[N#]` model viết. Mỗi câu có một nhãn: `[N3·12/10]` (khớp ghi chú 3, ghi ngày 12/10), `[?]` (model tự nói, chưa kiểm chứng), `[≠N3]` (MÂU THUẪN ghi chú 3), `[!]` (trích dẫn sai).
3. **Gác số, tên và phủ định.** Lỗi nguy hiểm nhất với ghi chú cá nhân là sai số, sai ngày, đảo phủ định ("không dị ứng tôm" → "dị ứng tôm"). Câu nào nêu số/ngày/tên không có trong ghi chú, hoặc thêm/bỏ phủ định, bị đánh `MÂU THUẪN` dù trùng nhiều từ.
4. **Bậc thang suy giảm trung thực.** Có model → trả lời có nhãn. Không có model → `MEMORY_ONLY` (nguyên văn ghi chú, không sinh chữ). Không có gì → `NO_DATA`. Mỗi bậc một exit code để script dùng được.
5. **Lịch sử ghi chú không thể xoá lặng lẽ.** Thay thế phải chỉ rõ; quên là thu hồi, không xoá; biên nhận ghi ngày ghi chú và hash sổ cái ghi chú lúc trả lời.
6. **`hg check`**: dán bất kỳ đoạn văn nào (tin nhắn ai đó gửi, kế hoạch) — HG chỉ ra câu nào khớp, câu nào mâu thuẫn với ghi chú, không cần model.

Hai tầng sự thật trong v1: `NOTE` (Chủ Nhân đã nói) và `MODEL` (chưa kiểm chứng). Không có `FACT` trong v1.
Giới hạn: đây là kiểm tra từ vựng (lexical), không phải suy luận ngữ nghĩa như NLI; có thể bỏ sót câu diễn đạt khác (thành `[?]`) và không đánh giá được suy luận qua nhiều ghi chú.

## 4. Phạm vi kỹ thuật

### 4.1 Trong phạm vi

| ID | Hạng mục | Vị trí |
|---|---|---|
| A0 | Lớp trợ lý `hg/assistant/`: thư mục nhà (`HG_HOME`, mặc định `~/.local/share/hg/assistant`, quyền 0700), khoá một-người-ghi, cấu hình provider | `hg/assistant/home.py`, `config.py` |
| F2 | `hg note add|search|list|show|forget` trên `MemoryStore` (kind mới `NOTE`, source `USER`, layer `SEMANTIC`) | `hg/assistant/notes.py`, `hg/memory/store.py` |
| T1 | Bộ phân tích tiếng Việt `textvi` (NFC, stoplist, bỏ dấu, cặp âm tiết); NFC trong `hg.memory.index` | `hg/assistant/textvi.py`, `hg/memory/index.py` |
| F1 | `hg ask "câu hỏi"` — truy xuất ghi chú (BM25 có sẵn), gọi `ModelRouter`, kiểm chứng câu, biên nhận, sổ cái `asks.jsonl` | `hg/assistant/ask.py`, `grounding.py` |
| F5 | `hg summarize FILE|- [--model] [--strict] [--max-sentences N]` | `hg/assistant/summarize.py` |
| C1 | `hg check` (đối chiếu văn bản bất kỳ với ghi chú, không cần model); `hg` không tham số = chế độ tương tác | `hg/assistant/check.py`, `cli.py` |
| R1 | `hg repair` (sổ cái có dòng cuối bị cắt) | `hg/assistant/repair.py` |
| E1 | `hg eval` (HG_HOME tạm, không đụng ghi chú thật) | `hg/assistant/evaluate.py` |
| M1 | `hg model status`: Ollama có chạy không, model nào có sẵn (`GET /api/tags`) | `hg/assistant/config.py` |
| M2 | `OllamaProvider`: tắt chế độ suy nghĩ, bỏ khối `<think>…</think>` khỏi đầu ra | `hg/brain/providers.py` |
| F3 | Giữ nguyên `POST /v1/tasks` (fs.write + readback) | không đổi code |
| F4 | Deploy release mới từ `main` sau merge, smoke, restart, rollback thật | điện thoại |
| D1 | Cài Ollama làm dịch vụ runit `ollama` (chỉ `127.0.0.1:11434`), chọn model bằng đo đạc | điện thoại |
| D2 | Lệnh `hg` (shim) trỏ vào release đang chạy | điện thoại `$PREFIX/bin/hg` |
| D3 | Hướng dẫn sử dụng tiếng Việt | `docs/HG_V1_GUIDE.md` |

### 4.2 Ngoài phạm vi v1 (V2_DEFERRED)

Chuyển sang runtime.service (6 cổng ADR-012); MAEP-1.2.0; chống kẻ tấn công cùng UID và TOCTOU nâng cao; T-1 danh tính principal; A-1b; review độc lập AC-14; mở `ask`/`note` qua HTTP; mở `test.run`/`url.read` qua HTTP; model lớn trên GPU thuê; ASR/TTS tiếng Việt; tìm kiếm ngữ nghĩa (embedding) — chỉ thêm khi benchmark chứng minh cần (MIID §11); dọn 76 nhánh cũ.

## 5. Tiêu chí nghiệm thu (đo được)

Hằng số đã chốt trước khi chạy: `SUPPORT_THRESHOLD = 0.6`, `NEAR_THRESHOLD = 0.4` (`hg/assistant/grounding.py`). Bộ đánh giá nghiệm thu `hg/assistant/eval_vi.json` (30 câu: 20 có đáp án gồm 10 câu gõ không dấu, 10 câu không có đáp án; 15 ghi chú gồm ghi chú gần trùng chủ đề và 2 ghi chú chứa lệnh chèn) được commit **trước** lần chạy đầu trên thiết bị; chọn model bằng bộ riêng `eval_vi_select.json`, không dùng bộ nghiệm thu.

| AC | Tiêu chí | Cách kiểm |
|---|---|---|
| AC-N1 | Thêm 3 ghi chú, khởi động tiến trình mới: `note list` trả đúng 3 ghi chú theo thứ tự; `search "bao hiem"` (không dấu) trả ghi chú "Bảo hiểm…" đứng đầu; truy vấn NFD cho kết quả như NFC | unit + subprocess |
| AC-N2 | Cùng `--subject`, khác nội dung → exit 4; `--replaces ID` → bản cũ SUPERSEDED, `show` còn cả hai; cùng nội dung → không tạo bản mới; `forget` → RETRACTED, nội dung còn trong lịch sử | unit |
| AC-N3 | Tiến trình cha giữ khoá ghi; tiến trình con (`subprocess`) `note add` → exit 75 trong ≤ thời gian chờ; sổ cái vẫn đọc được | subprocess |
| AC-N4 | HG_HOME quyền ≠ 0700, là symlink, hoặc nằm trên /sdcard → exit 78 | unit |
| AC-N5 | Sổ cái có dòng cuối bị cắt dở: lệnh thường → exit 78 kèm hướng dẫn; `hg repair` sao lưu file rồi bỏ đúng dòng hỏng, các dòng trước giữ nguyên | unit |
| AC-A1 | Model giả: câu có đủ từ và số của ghi chú → `NOTE`; không có nguồn → `MODEL`; trích `[N9]` không tồn tại → `BADCITE`; câu khớp ghi chú dù model không trích → `NOTE` | unit |
| AC-A2 | Bộ đối kháng cố định ≥ 20 câu (đổi số, đổi ngày, đổi tên, thêm/bỏ phủ định, "ko") → **0** câu được gắn `NOTE` | unit |
| AC-A3 | Không có provider → exit 3, chỉ in nguyên văn ghi chú; không ghi chú + không model → exit 5 | unit |
| AC-A4 | Ghi chú chứa lệnh chèn nằm trong khối JSON có dấu mốc ngẫu nhiên; ký tự điều khiển (ESC, OSC 52) bị loại khỏi đầu ra; không có đường nào tự gọi provider trả phí | unit |
| AC-A5 | Mỗi lần `ask` ghi một biên nhận: provider, model, digest model, ID ghi chú + sha256, hash sổ cái ghi chú, nhãn từng câu, listener, release — không có khoá API | unit |
| AC-A6 | Trên điện thoại, model đã chọn, HG_HOME tạm: tỷ lệ đúng dữ kiện ≥ 0,8; tỷ lệ gắn đúng ghi chú ≥ 0,7; tỷ lệ từ chối đúng ≥ 0,8; không câu trả lời nào làm theo lệnh chèn; ghi chú hiện ≤ 2 s; câu đầu p50 ≤ 15 s; ghi p95, thời gian nạp nguội, RSS, phiên bản Ollama, digest model, tuỳ chọn | `hg eval` trên thiết bị, log |
| AC-A7 | Hai ghi chú được truy xuất mâu thuẫn nhau → HG cảnh báo trước câu trả lời | unit |
| AC-M1 | `hg model status`: Ollama tắt → exit 3; bật → liệt kê model; digest khác bản đã ghim → exit 78 | unit (HTTP giả) + thiết bị |
| AC-M2 | `<think>…</think>` bị loại (cả khi stream bị cắt giữa thẻ); HTTP_PROXY trỏ ra ngoài vẫn không được dùng cho Ollama; URL không phải IP loopback → bị từ chối | unit |
| AC-S1 | Tóm tắt trích xuất: mọi câu có `[L…]` trỏ dòng có thật; file tiếng Việt chạy được | unit |
| AC-S2 | Model giả neo sai dòng → `[!]`; `--strict` loại và đếm; FIFO, file > 1 MB, có NUL, không phải UTF-8 → exit 2 | unit |
| AC-R1 | Suite cũ vẫn xanh (maep 304, hooks 32, hg 256 + test mới), selfcheck, bench; CI 3.13 + 3.14 xanh; ledger định dạng cũ (`memory.jsonl` của `f3dac34`) vẫn nạp được | CI |
| AC-D1 | Release từ commit merge: build trên điện thoại hai lần trùng hash; cây Git và danh sách file trùng với bản build ở môi trường CI-tương-đương (archive có thể khác byte giữa nền tảng — chốt trước: so `tree` + manifest file) | thiết bị + sandbox |
| AC-D2 | Shim `hg` chạy từ `~/HG` vẫn nạp code của release (`hg.__file__` nằm trong release); đường dẫn tương đối của `summarize` vẫn đúng | thiết bị |
| AC-D3 | Chuyển dịch vụ: sao lưu run script + config + state (dịch vụ dừng, gồm sqlite `-wal`) có hash; release mới READY đúng ID; smoke `CLOSED_VERIFIED`, đọc lại file, gửi lại cùng key → replay, khác body → 409; restart → task còn | thiết bị |
| AC-D4 | Rollback thật sau khi release mới đã ghi state: release cũ READY trên state đó và GET được task smoke mới; rồi chuyển lại release mới, kiểm cả hai task | thiết bị |
| AC-D5 | Có `finish` script: exit 78 → dịch vụ dừng, không vòng lặp khởi động đốt quota GitHub; kiểm `/rate_limit` trước khi deploy | thiết bị |
| AC-G1 | Mọi lệnh trong hướng dẫn chạy trên điện thoại với exit code ghi trong hướng dẫn | thiết bị |

## 6. Mô hình đe doạ v1

| Mối đe doạ | Xử lý v1 |
|---|---|
| Nội dung ghi chú/file chèn lệnh (prompt injection) | JSON giữa dấu mốc ngẫu nhiên mỗi lần gọi + chỉ dẫn hệ thống; nhãn do HG tính; output của model không bao giờ kích hoạt hành động; AC-A4, AC-A6 |
| Model bịa hoặc đổi số/ngày/tên/phủ định | HG kiểm từng câu; AC-A1, AC-A2 |
| Dữ liệu đi qua proxy (HTTP_PROXY) hoặc bị redirect | Kết nối Ollama dùng opener không proxy, không redirect, chỉ IP loopback dạng số; AC-M2 |
| **Ứng dụng Android khác** (UID khác, không thuộc Q3) gọi Ollama loopback không xác thực: đổi/xoá model, hoặc chiếm cổng 11434 khi Ollama tắt để nhận prompt | Ghim digest model, kiểm trước mỗi lần gọi; khi cấu hình `ollama_service_dir`, bắt buộc tiến trình Ollama do runit giám sát còn sống, đúng binary, đúng UID (Ollama tự thoát nếu không bind được cổng). Android chặn đọc /proc/net/tcp nên không thể hỏi kernel ai giữ cổng — giới hạn còn lại ghi trong biên nhận |
| Provider trả phí âm thầm làm dự phòng | Router chỉ có đúng một provider được chọn; trả phí chỉ khi `--provider anthropic` trong chính lệnh đó |
| Hai tiến trình ghi cùng sổ cái | `flock` lấy **trước** khi nạp sổ cái; đọc dùng khoá chia sẻ; không giữ khoá khi model đang chạy; AC-N3 |
| Dòng cuối sổ cái bị cắt (OOM giữa lúc ghi) | Báo lỗi rõ ràng + `hg repair` có sao lưu; AC-N5 |
| File đặc biệt khi tóm tắt (FIFO, /dev/zero, /proc, file khổng lồ, nhị phân) | Mở non-blocking, chỉ file thường, ≤ 1 MB, UTF-8 chặt, không NUL; AC-S2 |
| Agent chạy `hg note` thay Chủ Nhân (T-1: chung danh tính) | Mỗi ghi chú lưu nguồn gốc (gõ trong terminal / pipe / prompt tương tác) |
| Người dùng khác đọc ghi chú; HG_HOME trên /sdcard | Thư mục 0700, file 0600, umask 077; từ chối shared storage; AC-N4 |
| Shim nạp nhầm code từ checkout bẩn `~/HG` | `python3 -I` + `sys.path` tường minh trỏ vào release; AC-D2 |
| Vòng lặp khởi động đốt quota GitHub (60 lần/giờ) và chặn cả rollback | `finish` script dừng dịch vụ khi exit 78; AC-D5 |
| Kẻ tấn công cùng UID | **Ngoài phạm vi (Q3)** — rủi ro còn lại |
| Lộ token dịch vụ khi deploy | Không in token; chỉ đọc vào biến cục bộ cho curl |

Lớp trợ lý chạy **ngoài** ActionGateway/TaskStore: đây là lệnh trực tiếp của Chủ Nhân trong shell của chính Chủ Nhân, với quyền hệ điều hành của Chủ Nhân, chỉ ghi vào HG_HOME. Nó **không** ENFORCED bởi runtime HG và được ghi như vậy trong CLAUDE.md.

## 7. Kế hoạch thực hiện (thứ tự theo giá trị: v1a trước)

| Bước | Việc | Phụ thuộc | Rollback |
|---|---|---|---|
| P1 | Thẩm định nội bộ, sửa kế hoạch (xong: mục 9) | — | — |
| P2 | Nền: `textvi` (NFC, stoplist, bỏ dấu), `home` (khoá trước khi nạp, 0700), `notes`, `repair`; NFC trong `hg.memory.index` | P1 | revert commit |
| P3 | `providers`: không proxy, chỉ loopback, stream, bỏ `<think>`, `tags()`; `config`: ghim digest, xác thực listener; `grounding`; `ask`; `check`; `model status/use` | P2 | revert commit |
| P4 | `summarize` (trích xuất + model có neo dòng) | P2 | revert commit |
| P5 | Test mới (gồm bộ đối kháng, fixture state cũ), full suite, selfcheck, bench | P2–P4 | — |
| P6 | Push, PR, CI 3.13/3.14, merge | P5 | nhánh `recovery/main-pre-v1-assistant-20261028` |
| P7 | Điện thoại: Ollama (dịch vụ runit, `apt-mark hold`), model; chọn model bằng `eval_vi_select.json`; ghim digest | độc lập P6 | `sv down ollama`, xoá dịch vụ/model |
| P8 (v1a) | Điện thoại: build release từ merge commit (thư mục riêng), chạy suite từ release, cài shim `hg` — **chưa** đổi dịch vụ; chạy AC-A6 | P6, P7 | xoá shim |
| P9 | Điện thoại: chuyển dịch vụ hg-runtime (AC-D3), rollback thật (AC-D4), `finish` script (AC-D5) | P8 | run script + config + state đã sao lưu có hash |
| P10 | Hướng dẫn tiếng Việt, chạy từng lệnh trên thiết bị (AC-G1); cập nhật CLAUDE.md (trạng thái thực thi) | P8 | revert |
| P11 | Kiểm tra cuối bởi một agent riêng chưa thấy quá trình làm (vẫn là kiểm tra nội bộ, không phải review độc lập MAEP-021); báo cáo đóng | tất cả | — |

Điều kiện dừng: test cũ đỏ mà không sửa được trong phạm vi; CI đỏ; preflight điện thoại thất bại; release mới không READY và rollback không khôi phục được — dừng ở trạng thái an toàn gần nhất và báo cáo.

## 8. Tài liệu tham chiếu ngoài

- Gao và cộng sự, *Enabling Large Language Models to Generate Text with Citations* (ALCE), 2023 — định nghĩa citation recall/precision theo từng câu bằng NLI: https://arxiv.org/abs/2305.14627
- *Do Retrieval Augmented Language Models Know When They Don't Know?* (AAAI) — RALM hiệu chỉnh kém, cần kết hợp từ chối với abstention theo độ bất định: https://ojs.aaai.org/index.php/AAAI/article/view/40822
- Chạy Ollama trên Termux (`pkg install ollama`, `ollama serve`, `termux-wake-lock`, ưu tiên model nhỏ): https://dev.to/h4ck3r/how-to-run-ollama-in-android-without-root-nam
- Model nhỏ chạy local 2026 (Qwen3 1.7B/4B Apache-2.0, đa ngôn ngữ; Gemma 3 1B/4B; khuyến nghị tự kiểm bằng dữ liệu ngôn ngữ của mình): https://huggingface.co/blog/daya-shankar/open-source-llm-models-to-run-locally
- Gao và cộng sự, *RARR: Researching and Revising What Language Models Say, Using Language Models* (ACL 2023) — kiểm tra và sửa câu của model sau khi sinh: https://arxiv.org/abs/2210.08726
- Google Cloud, Vertex AI check grounding (kiểm tra câu trả lời có được nguồn hỗ trợ, dịch vụ đám mây): https://python.langchain.com/api_reference/google_community/vertex_check_grounding.html
- Các endpoint REST của Ollama (`/api/chat`, trường `message.content`, `eval_count`): https://notes.kodekloud.com/docs/Running-Local-LLMs-With-Ollama/Building-AI-Applications/Ollama-REST-API-Endpoints/page.md

Những gì HG học từ các nguồn trên là *vấn đề* (trích dẫn không đáng tin, model không biết khi nào nên từ chối); cơ chế xử lý — biên nhận do HG tự tính, ba tầng sự thật, bậc thang suy giảm trung thực, tóm tắt neo dòng — là thiết kế của HG.

## 9. Thẩm định nội bộ (2026-10-28) — ba góc nhìn, cùng kết luận APPROVE_WITH_CHANGES

Đây là phê bình nội bộ của ba agent riêng biệt, không phải review độc lập theo MAEP-021.

| Góc nhìn | Phát hiện chính | Xử lý trong v0.2 |
|---|---|---|
| Bảo mật & quản trị | urllib đi qua HTTP_PROXY kể cả với 127.0.0.1 (đã tái hiện) | Opener không proxy, không redirect, chỉ IP loopback (AC-M2) |
| Bảo mật & quản trị | App Android khác gọi/chiếm cổng Ollama, đổi model | Ghim digest + xác thực tiến trình runit; /proc/net/tcp bị Android chặn (đã kiểm trên máy) → ghi giới hạn |
| Bảo mật & quản trị | Phủ định và số làm hỏng kiểm tra từ vựng; NFD tách "không" | Gác số/tên/phủ định; NFC ở mọi đầu vào (AC-A2) |
| Bảo mật & quản trị | Khoá lấy sau khi nạp sổ cái → trùng số thứ tự | Khoá trước khi nạp; đọc LOCK_SH; không giữ khoá khi model chạy (AC-N3) |
| Bảo mật & quản trị | Gọi "thẩm định độc lập" là sai MAEP-021; fallback trả phí âm thầm; đọc file đặc biệt; chèn lệnh qua dấu mốc cố định | Đổi tên; router một provider; mở file an toàn; dấu mốc ngẫu nhiên + JSON + lọc ký tự điều khiển |
| Sản phẩm & bản sắc | Từ chức năng tiếng Việt làm BM25 luôn khớp → không bao giờ từ chối được; gõ không dấu không khớp | `textvi`: stoplist, ghép cặp, bỏ dấu (đ→d thủ công) |
| Sản phẩm & bản sắc | Model 1,7B viết `[N#]` không đều; độ trễ; nhãn tiếng Anh rối mắt | HG tự khớp mọi ghi chú; stream theo câu; nhãn ngắn + chân trang tiếng Việt; không retry model local |
| Sản phẩm & bản sắc | Gõ tiếng Việt trong dấu nháy shell bất tiện | `hg` không tham số mở chế độ tương tác; `note`/`ask`/`check` đọc stdin |
| Sản phẩm & bản sắc | AC-A6 quá yếu; tuyên bố độc đáo quá mức | 30 câu, ngưỡng chốt trước, có câu không dấu và câu không đáp án; mục 3 viết lại đúng mức |
| Kiểm thử & vận hành | Chọn model trên chính bộ nghiệm thu | Tách `eval_vi_select.json` |
| Kiểm thử & vận hành | Rollback thiếu config/state; vòng lặp khởi động đốt quota | Sao lưu có hash; rollback sau khi state mới đã ghi; `finish` script (AC-D3..D5) |
| Kiểm thử & vận hành | Dòng cuối bị cắt làm hỏng sổ cái; shim nạp nhầm code | `hg repair` (AC-N5); shim `-I` (AC-D2) |
| Kiểm thử & vận hành | Tất định ≠ nguồn gốc | So cây Git + manifest với bản build ngoài điện thoại (AC-D1) |

Ý tưởng được nhận vào v1: nhãn có ngày ghi chú; `hg check`; cảnh báo khi hai ghi chú mâu thuẫn nhau (AC-A7). Dời sang v2: `hg ask --verify` (kiểm lại biên nhận sau), lối tắt Termux:Widget/thông báo, đọc PDF/clipboard trực tiếp.

## 10. Kết quả thực hiện (cập nhật 2026-10-28)

### 10.1 Thay đổi đã vào `main`

| PR | Merge commit | Nội dung | CI |
|---|---|---|---|
| #65 | `57f59b2` | Lớp trợ lý `hg/assistant/`, providers loopback/stream, NOTE kind, 63 test mới, tài liệu | `unittest (3.13)`, `unittest (3.14)`, `rt06-anchor` xanh |
| #66 | `98c53fd` | Sửa từ lần chạy chọn model trên thiết bị: cổng câu hỏi đời tư, khớp ≥ nửa từ, tên trùng đại từ | xanh; 3 test mới fail trên code trước sửa, pass sau sửa |

Recovery point trước khi merge: nhánh `recovery/main-pre-v1-assistant-20261028` @ `37f1627`.

### 10.2 Trạng thái từng tiêu chí

| AC | Trạng thái | Bằng chứng |
|---|---|---|
| AC-N1…N5 | VERIFIED (unit/subprocess) | `hg/tests/test_assistant_notes.py`; CI; điện thoại Python 3.14.6 tại `7017949`: hg 319 OK |
| AC-A1, A2, A3, A4, A5, A7 | VERIFIED (unit) | `test_assistant_grounding.py` (bộ đối kháng 21 câu → 0 NOTE), `test_assistant_ask.py` |
| AC-A6 | **NOT_RUN** (bộ nghiệm thu) | Điện thoại mất kết nối trước khi chạy. Bộ chọn model (code `7017949`, trước #66): qwen3:1.7b đúng dữ kiện 0,6, gắn nguồn 0,6, từ chối đúng 0,33, chèn lệnh 0, câu đầu p50 3,5 s → FAIL chất lượng; qwen3:4b ~38–61 s/câu → FAIL độ trễ |
| AC-M1, AC-M2 | VERIFIED (unit); thiết bị: Ollama 0.40.12 `/api/version`, `/api/tags`, `think:false` (qwen3:1.7b 4,3 s gồm 3,5 s nạp) | `test_assistant_ask.py`; log thiết bị |
| AC-S1, AC-S2 | VERIFIED (unit) | `SummarizeTests` |
| AC-R1 | VERIFIED | CI 3.13/3.14 (#65, #66); điện thoại tại `7017949`: maep 304 OK (3 skip), hg 319 OK, hooks 32 OK, selfcheck 0, bench 0; fixture state `f3dac34` nạp được |
| AC-D1 | PARTIAL | Build ngoài thiết bị tại `57f59b2`: 219 file, tree `5cd8dea…`; build trên thiết bị NOT_RUN |
| AC-D2 | VERIFIED (unit, shim chạy từ checkout giả vẫn nạp release); thiết bị NOT_RUN | `ShimAndCliTests` |
| AC-D3, D4, D5 | **NOT_RUN** — BLOCKED_EXTERNAL | Thiết bị offline (Desktop Commander, "last seen" ≈ 20:06 +07); script sẵn ở `deploy/termux/` |
| AC-G1 | NOT_RUN | Cần thiết bị |

### 10.3 Trạng thái vận hành đã quan sát (trước khi thiết bị offline)

- `hg-runtime`: READY, release `f7cfd766…` (commit `f3dac34`), trust LOADED @ `37f1627`, không bị đụng tới.
- Ollama 0.40.12 cài từ gói Termux (mô phỏng `apt-get -s`: chỉ thêm 1 gói, 0 nâng cấp), dịch vụ runit `ollama` trên `127.0.0.1:11434`; model đã tải: `qwen3:1.7b`, `qwen3:4b`, `gemma3:4b`.
- `~/HG` (46 thay đổi chưa commit của Chủ Nhân) không bị đụng tới.
