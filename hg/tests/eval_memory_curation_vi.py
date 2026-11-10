"""Labelled synthetic Vietnamese evaluation for the read-only memory-curation heuristics.

This is a regression corpus, not a representative sample of real user memory. Metrics are
reported per candidate class so lexical similarity is never presented as semantic truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hg.memory.curation import analyze_memories


AS_OF = "2026-11-01T00:00:00Z"


def _record(mid, content, *, kind="NOTE", value=None, **extra):
    row = {
        "memory_id": mid, "layer": "SEMANTIC", "kind": kind, "subject": "chu-de",
        "content": content, "value": value, "status": "ACTIVE",
        "source": "USER", "source_ref": "synthetic-evaluation",
        "evidence_refs": [],
    }
    row.update(extra)
    return row


def _pair(mid, a, b, *, kind="NOTE", av=None, bv=None, **extra):
    return [_record(mid + "-A", a, kind=kind, value=av, **extra),
            _record(mid + "-B", b, kind=kind, value=bv, **extra)]


def build_corpus():
    """64 separately authored synthetic scenarios; no repeated template pair."""
    cases = []
    exact_topics = [
        "Lịch thay dầu xe máy của chủ nhân sau mỗi ba nghìn kilomet",
        "Mật khẩu WiFi khách được đổi vào đầu mỗi quý",
        "Lịch tưới cây ban công vào sáng thứ bảy hàng tuần",
        "Hồ sơ thu chi tổ dân phố lưu theo từng tháng dương lịch",
        "Bản sao dự phòng tài liệu HG đặt trong thư mục mã hóa riêng",
        "Lịch kiểm tra bình chữa cháy tại nhà văn hóa mỗi tháng",
        "Quy trình tiếp nhận hồ sơ hành chính tại bộ phận một cửa",
        "Thời hạn bảo hành máy lọc nước tính từ ngày bàn giao",
    ]
    exact_different = [
        ("Lịch họp tổ vào lúc 8 giờ sáng thứ hai", "Lịch họp tổ vào lúc 9 giờ sáng thứ hai"),
        ("Xe máy thay dầu ở mốc 12000 kilomet", "Xe máy thay dầu ở mốc 15000 kilomet"),
        ("Nhiệt độ tủ lạnh đặt ở mức 4 độ C", "Nhiệt độ tủ lạnh đặt ở mức 6 độ C"),
        ("Hạn nộp báo cáo ngày 12 tháng 5", "Hạn nộp báo cáo ngày 19 tháng 5"),
        ("Khoản đóng góp là 250000 đồng", "Khoản đóng góp là 350000 đồng"),
        ("Phòng họp ở tầng 2 khu A", "Phòng họp ở tầng 3 khu A"),
        ("Lịch uống thuốc lúc 7 giờ tối", "Lịch uống thuốc lúc 8 giờ tối"),
        ("Dung lượng lưu trữ còn 64 GB", "Dung lượng lưu trữ còn 128 GB"),
    ]
    for i, text in enumerate(exact_topics):
        cases.append({"id": f"EX-P{i+1}", "class": "exact_duplicate", "expected": True,
                      "records": _pair(f"EX-P{i+1}", text + f"; hồ sơ tham chiếu {101+i}",
                                       text + f"; hồ sơ tham chiếu {101+i}")})
    for i, (a, b) in enumerate(exact_different):
        cases.append({"id": f"EX-N{i+1}", "class": "exact_duplicate", "expected": False,
                      "records": _pair(f"EX-N{i+1}", a, b)})

    near_bases = [
        ("xe máy của chủ nhân cần được kiểm tra hệ thống phanh định kỳ trước mỗi chuyến đi đường dài nhằm bảo đảm an toàn vận hành và hạn chế rủi ro khi di chuyển qua khu vực đông phương tiện giao thông", "phanh", "lái"),
        ("tài liệu dự án HG phải được sao lưu nguyên vẹn kèm mã kiểm tra để có thể phục hồi chính xác khi thiết bị lưu trữ gặp sự cố bất ngờ trong quá trình vận hành thường xuyên", "mã", "dấu"),
        ("cây cảnh ngoài ban công cần được tưới lượng nước vừa đủ vào buổi sáng để tránh úng rễ trong những ngày mưa kéo dài và duy trì điều kiện sinh trưởng ổn định cho từng loại cây", "sáng", "chiều"),
        ("hồ sơ hành chính cần được đối chiếu ngày tiếp nhận và chữ ký trước khi chuyển sang bước xử lý tiếp theo tại cơ quan nhằm bảo đảm trình tự nghiệp vụ công khai minh bạch và chính xác", "ngày", "mã"),
        ("thiết bị mạng gia đình nên được khởi động lại theo lịch bảo trì nhằm duy trì kết nối ổn định cho các thiết bị đầu cuối và giảm thiểu tình trạng gián đoạn dịch vụ trong giờ làm việc", "mạng", "điện"),
        ("ngân sách sinh hoạt hàng tháng cần được ghi nhận theo từng nhóm chi phí để chủ nhân dễ dàng kiểm soát biến động thực tế và điều chỉnh kế hoạch chi tiêu phù hợp với thu nhập hiện có", "chi", "thu"),
        ("bản ghi âm phát thanh phải được kiểm tra âm lượng và tạp âm trước khi ghép vào chương trình thông báo chính thức để người nghe tiếp nhận đầy đủ nội dung rõ ràng trong môi trường công cộng", "âm lượng", "chất lượng"),
        ("dữ liệu ghi nhớ dài hạn nên giữ lại nguồn gốc bằng chứng và thời điểm cập nhật để tránh nhầm lẫn giữa các phiên bản trong quá trình truy xuất phục hồi và đối chiếu lịch sử thay đổi", "nguồn gốc", "dấu vết"),
    ]
    unrelated = [
        ("lịch chăm sóc thú cưng tại nhà vào sáng chủ nhật", "mẫu biên bản nghiệm thu công trình xây dựng mới"),
        ("cấu hình máy chủ lưu trữ bản sao dữ liệu đã mã hóa", "thực đơn ăn chay cho buổi liên hoan cuối năm"),
        ("thời gian xe buýt đến bến trung tâm trong ngày lễ", "cách trồng hoa giấy trong chậu đất nung nhỏ"),
        ("kế hoạch kiểm kê tài sản tại phòng thiết bị của trường", "công thức làm bánh mì nguyên cám không dùng sữa"),
        ("hướng dẫn đổi địa chỉ thư điện tử của tài khoản", "quy trình phân loại rác hữu cơ tại khu dân cư"),
        ("định mức nhiên liệu cho máy phát điện dự phòng", "lịch tiêm phòng định kỳ cho đàn gia cầm"),
        ("phương án bố trí chỗ ngồi cho hội nghị trực tuyến", "mẹo bảo quản rau xanh trong ngăn mát tủ lạnh"),
        ("các bước kiểm tra chữ ký số trên văn bản điện tử", "lịch bảo dưỡng mái tôn trước mùa mưa bão"),
    ]
    for i, (base, old_token, new_token) in enumerate(near_bases):
        left, right = base, base.replace(old_token, new_token, 1)
        if left == right:
            raise AssertionError(f"near-duplicate case {i+1} did not change")
        cases.append({"id": f"ND-P{i+1}", "class": "near_duplicate", "expected": True,
                      "records": _pair(f"ND-P{i+1}", left, right)})
    for i, (a, b) in enumerate(unrelated):
        cases.append({"id": f"ND-N{i+1}", "class": "near_duplicate", "expected": False,
                      "records": _pair(f"ND-N{i+1}", a + f" mã nội bộ {300+i}", b + f" mã nội bộ {700+i}")})

    conflict_contexts = [
        ("giờ bắt đầu cuộc họp tổ dân phố", "18:00", "19:00"),
        ("mức phí vệ sinh hàng tháng", "45000 đồng", "55000 đồng"),
        ("nhiệt độ bảo quản vaccine", "2 độ C", "8 độ C"),
        ("ngày hết hạn hợp đồng thuê nhà", "2027-03-31", "2027-06-30"),
        ("số kilomet cần thay dầu xe máy", "3000 km", "4000 km"),
        ("thời lượng lưu trữ bản ghi camera", "15 ngày", "30 ngày"),
        ("dung lượng phân vùng dữ liệu HG", "64 GB", "96 GB"),
        ("số lượng ghế trong hội trường", "120 ghế", "150 ghế"),
    ]
    disjoint_contexts = [
        ("giờ tiếp dân mùa khô", "08:00", "07:30"),
        ("mức hỗ trợ quý một", "500000 đồng", "550000 đồng"),
        ("định mức điện mùa hè", "120 kWh", "140 kWh"),
        ("lịch trực dịp tết năm trước", "2025-01-28", "2025-02-02"),
        ("chu kỳ bảo dưỡng xe năm trước", "3000 km", "3500 km"),
        ("hạn lưu hồ sơ đợt một", "90 ngày", "120 ngày"),
        ("quota lưu trữ giai đoạn thử nghiệm", "32 GB", "48 GB"),
        ("số ghế phòng họp cũ", "80 ghế", "100 ghế"),
    ]
    for i, (topic, a, b) in enumerate(conflict_contexts):
        cases.append({"id": f"CF-P{i+1}", "class": "conflict", "expected": True,
                      "records": [_record(f"CF-P{i+1}-A", topic + " đã được xác nhận", kind="FACT", value=a),
                                  _record(f"CF-P{i+1}-B", topic + " đã được xác nhận", kind="FACT", value=b)]})
    for i, (topic, a, b) in enumerate(disjoint_contexts):
        cases.append({"id": f"CF-N{i+1}", "class": "conflict", "expected": False,
                      "records": [_record(f"CF-N{i+1}-A", topic + " trong giai đoạn trước", kind="FACT", value=a,
                                           valid_from="2025-01-01", valid_to="2025-04-01"),
                                  _record(f"CF-N{i+1}-B", topic + " trong giai đoạn sau", kind="FACT", value=b,
                                           valid_from="2025-04-01", valid_to="2025-07-01")]})

    expiry_dates = ["2026-01-10", "2026-02-14", "2026-03-21", "2026-04-08",
                    "2026-05-16", "2026-06-29", "2026-07-11", "2026-08-23"]
    old_dates = ["1999-01-01", "2003-05-12", "2008-09-30", "2011-02-17",
                 "2014-11-06", "2017-07-25", "2020-03-18", "2022-12-09"]
    stale_text = ["giấy phép kinh doanh quầy hàng", "thẻ ra vào kho vật tư", "gói cước dữ liệu di động",
                  "hợp đồng bảo trì thang máy", "chứng nhận kiểm định thiết bị", "phiếu bảo hành máy bơm",
                  "giấy phép sử dụng hội trường", "thỏa thuận thuê thiết bị âm thanh"]
    for i, (day, topic) in enumerate(zip(expiry_dates[:4], stale_text[:4])):
        cases.append({"id": f"ST-P{i+1}", "class": "staleness", "expected": True,
                      "records": [_record(f"ST-P{i+1}-A", topic + f" hồ sơ {810+i}", expires_at=day)]})
    for i, (day, topic) in enumerate(zip(old_dates[:4], stale_text[:4])):
        cases.append({"id": f"ST-N{i+1}", "class": "staleness", "expected": False,
                      "records": [_record(f"ST-N{i+1}-A", topic + f" được ghi nhận từ lâu mã {920+i}",
                                          created_at=day + "T00:00:00Z")]})

    cross_topics = [
        "địa chỉ nhận hóa đơn là số 18 đường Lê Lợi",
        "lịch kiểm tra thiết bị vào thứ tư hàng tuần lúc 9 giờ",
        "mức dự phòng ngân sách cho sửa chữa là 12 phần trăm",
        "bản sao lưu cần được kiểm tra mã SHA256 sau khi tạo",
        "cuộc họp điều phối diễn ra trực tuyến qua Google Meet",
        "xe máy cần thay dầu sau mỗi 3500 kilomet vận hành",
        "hồ sơ giấy được lưu tại tủ số 4 phòng văn thư",
        "thời gian phản hồi yêu cầu hỗ trợ tối đa là hai ngày làm việc",
    ]
    cross_unrelated = [
        ("địa chỉ nhận hàng là số 18 đường Lê Lợi", "cách chăm sóc cây lan trong mùa lạnh"),
        ("lịch kiểm tra thiết bị vào thứ tư lúc 9 giờ", "mẫu phiếu bàn giao tài sản cố định"),
        ("mức dự phòng ngân sách sửa chữa là 12 phần trăm", "công thức nấu súp bí đỏ cho trẻ nhỏ"),
        ("bản sao lưu phải kiểm tra mã SHA256 sau khi tạo", "hướng dẫn vệ sinh máy lạnh treo tường"),
        ("cuộc họp điều phối qua Google Meet vào sáng mai", "lịch thu gom rác tái chế tại khu phố"),
        ("xe máy thay dầu sau mỗi 3500 kilomet vận hành", "quy trình nhận hồ sơ xin cấp hộ chiếu"),
        ("hồ sơ giấy được lưu tại tủ số 4 phòng văn thư", "thời gian nấu cơm gạo lứt bằng nồi điện"),
        ("thời gian phản hồi hỗ trợ tối đa hai ngày làm việc", "cách chọn giống hoa phù hợp ban công nhỏ"),
    ]
    for i, text in enumerate(cross_topics[:4]):
        cases.append({"id": f"XS-P{i+1}", "class": "cross_subject", "expected": True,
                      "records": [_record(f"XS-P{i+1}-A", text, subject=f"chu-de-a-{i}"),
                                  _record(f"XS-P{i+1}-B", text, subject=f"chu-de-b-{i}")]})
    for i, (a, b) in enumerate(cross_unrelated[:4]):
        cases.append({"id": f"XS-N{i+1}", "class": "cross_subject", "expected": False,
                      "records": [_record(f"XS-N{i+1}-A", a, subject=f"chu-de-c-{i}"),
                                  _record(f"XS-N{i+1}-B", b, subject=f"chu-de-d-{i}")]})

    # Guard against accidentally padding the evaluation with repeated case pairs.
    fingerprints = set()
    for case in cases:
        fingerprint = json.dumps(case["records"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if fingerprint in fingerprints:
            raise AssertionError("duplicate synthetic evaluation case: " + case["id"])
        fingerprints.add(fingerprint)
    if len(cases) != 64:
        raise AssertionError(f"expected 64 independent scenarios, found {len(cases)}")
    return cases


def _detected(case, report):
    ids = {r["memory_id"] for r in case["records"]}
    if case["class"] == "exact_duplicate":
        return any(ids.issubset(set(row["memory_ids"])) for row in report["exact_duplicate_groups"])
    if case["class"] == "near_duplicate":
        return any(set(row["memory_ids"]) == ids for row in report["near_duplicate_pairs"])
    if case["class"] == "conflict":
        return any(set(row["memory_ids"]) == ids for row in report["conflict_candidates"])
    if case["class"] == "staleness":
        return any(ids == set(row["memory_ids"]) for row in report["staleness_candidates"])
    if case["class"] == "cross_subject":
        return any(ids == set(row["memory_ids"]) for row in report["cross_subject_candidates"])
    raise AssertionError(case["class"])


def evaluate():
    cases = build_corpus()
    classes = sorted({case["class"] for case in cases})
    summary = {}
    false_cases = []
    for label in classes:
        rows = [case for case in cases if case["class"] == label]
        tp = fp = tn = fn = 0
        for case in rows:
            report = analyze_memories(case["records"], as_of=AS_OF)
            actual = _detected(case, report)
            expected = case["expected"]
            if expected and actual:
                tp += 1
            elif expected and not actual:
                fn += 1
                false_cases.append({"id": case["id"], "error": "FALSE_NEGATIVE"})
            elif not expected and actual:
                fp += 1
                false_cases.append({"id": case["id"], "error": "FALSE_POSITIVE"})
            else:
                tn += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        summary[label] = {
            "cases": len(rows), "TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "precision": round(precision, 4), "recall": round(recall, 4),
        }
    return {
        "schema": "HG-CURATION-VI-SYNTHETIC-EVAL/2",
        "evaluation_scope": "synthetic fixtures only; not a claim about production/user data",
        "as_of": AS_OF,
        "total_cases": len(cases),
        "independent_case_fingerprints": len({json.dumps(c["records"], ensure_ascii=False, sort_keys=True, separators=(",", ":")) for c in cases}),
        "thresholds": {"near_duplicate_jaccard": 0.88},
        "case_ids": [case["id"] for case in cases],
        "metrics": summary,
        "errors": false_cases,
        "interpretation": "64 unique labelled synthetic scenarios across exact/near/numeric-conflict/staleness/cross-subject classes; not a representative sample of real user memory. Human Vietnamese review remains required.",
    }


if __name__ == "__main__":
    result = evaluate()
    out = Path("memory-curation-vi-eval.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
