"""Phase 0 표본 수집기. 제품 코드가 아니라 측정 장치다.

알리오(www.alio.go.kr) 채용정보에서 정규직 신입 공고문 PDF를 받는다.
경로: getRecruitList.json -> seq -> informationRecruitDtl.do -> fileNo -> download.json

PDF는 저장소에 안 넣는다. 대장(manifest)만 남기고 누구나 같은 파일을 다시 받게 한다.
"""
import hashlib
from collections import Counter
import io
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# 🔴 윈도우 기본 콘솔은 cp949라 한글 대시 하나에 스크립트가 죽는다. 먼저 막는다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://www.alio.go.kr"
LIST = BASE + "/information/getRecruitList.json"
DTL = BASE + "/information/informationRecruitDtl.do?seq="
DOWN = BASE + "/download/download.json?fileNo="
UA = "hiring-traps phase0 collector (https://github.com/serenwoon/hiring-traps)"


def _req(url, data=None):
    headers = {"User-Agent": UA, "Referer": BASE + "/information/informationRecruitList.do"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=90) as r:
        return r.read(), dict(r.headers)


def list_page(page, s_date, e_date):
    raw, _ = _req(LIST, {"pageNo": page, "s_date": s_date, "e_date": e_date, "order": "BDATE"})
    return json.loads(raw.decode("utf-8"))["data"]["recruitList"]


def attachments(seq):
    """상세 페이지에서 (fileNo, 파일명) 목록. 파일명은 헤더에서 받으므로 여기선 번호만."""
    raw, _ = _req(DTL + str(seq))
    html = raw.decode("utf-8", "replace")
    return sorted(set(re.findall(r"download\.json\?fileNo=(\d+)", html)), key=int)


def name_score(name):
    """파일명으로 공고문다움을 점수화. 직무기술서·서식·붙임은 공고문이 아니다."""
    if any(k in name for k in ("직무기술서", "서식", "양식", "동의서", "지원서")):
        return -1
    if "공고문" in name:
        return 3
    if "공고" in name:
        return 2
    if "모집" in name:
        return 1
    return 0


def fetch_file(file_no, out_dir):
    raw, hdr = _req(DOWN + str(file_no))
    disp = hdr.get("Content-Disposition", "")
    m = re.search(r'filename="+([^"]+)"+', disp)
    name = urllib.parse.unquote(m.group(1)) if m else f"{file_no}.bin"
    try:                                      # 헤더가 UTF-8 바이트인데 latin-1로 읽힌다
        name = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    is_pdf = raw[:4] == b"%PDF"
    path = Path(out_dir) / f"{file_no}.pdf"
    if is_pdf:
        path.write_bytes(raw)
    return {
        "fileNo": file_no,
        "name": name,
        "pdf": is_pdf,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "path": str(path) if is_pdf else "",
    }


def total_pages(s_date, e_date):
    raw, _ = _req(LIST, {"pageNo": 1, "s_date": s_date, "e_date": e_date, "order": "BDATE"})
    d = json.loads(raw.decode("utf-8"))["data"]
    return max(1, -(-int(d["totalcount"]) // 10))


def main(want=20, s_date="2026.01.01", e_date="2026.08.25", out_dir="fixtures/live",
         max_per_org=1):
    """🔴 표집이 이 스크립트의 전부다.

    앞에서부터 받으면 병원이 스무 건 중 열다섯을 먹는다(2026-08-25 실측).
    기관을 자주 올리는 곳이 표본을 삼키기 때문이다. 그래서 두 가지를 건다 —
    기관당 상한, 그리고 목록 전체에 고르게 흩뿌리기.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    tp = total_pages(s_date, e_date)
    pages = list(range(1, tp + 1))
    random.Random(20260825).shuffle(pages)      # 시드 고정 — 같은 표본이 다시 나온다
    print(f"목록 {tp}쪽을 고정 시드로 섞어 훑는다")
    rows, seen, org_count, skipped = [], set(), Counter(), Counter()
    failed_pages = []
    examined = 0
    for page in pages:
        if len(rows) >= want:
            break
        items = None
        for attempt in (1, 2):
            try:
                items = list_page(page, s_date, e_date)
                break
            except Exception as exc:
                # 🔴 한 쪽이 실패했다고 수집 전체를 멈추면 표본이 앞쪽으로 쏠린다.
                #    2026-08-25: 196쪽 타임아웃 하나로 20건 목표가 6건에서 끝났다.
                print(f"목록 {page}쪽 실패({attempt}차): {exc}", file=sys.stderr)
                time.sleep(1.5)
        if items is None:
            failed_pages.append(page)
            continue
        if not items:
            continue
        for it in items:
            if len(rows) >= want:
                break
            if it["workTypeNa"] != "정규직" or "신입" not in it["carrerNa"]:
                continue
            if it["seq"] in seen or org_count[it["pname"]] >= max_per_org:
                continue
            seen.add(it["seq"])
            examined += 1
            try:
                nos = attachments(it["seq"])
            except Exception as exc:
                print(f"  seq={it['seq']} 상세 실패: {exc}", file=sys.stderr)
                continue
            # 🔴 첫 PDF를 집으면 안 된다. 첨부에 직무기술서가 섞여 있고
            #    그건 공고문이 아니다 (2026-08-25: 스무 건 중 세 건이 그렇게 들어왔다).
            cands = []
            for no in nos:
                info = fetch_file(no, out_dir)
                time.sleep(0.4)
                if info["pdf"]:
                    cands.append(info)
            got = max(cands, key=lambda c: name_score(c["name"]), default=None)
            if not got:
                skipped["PDF 첨부 없음"] += 1
                print(f"  건너뜀 seq={it['seq']} PDF 첨부 없음 (첨부 {len(nos)}개)", file=sys.stderr)
                continue
            got["name_score"] = name_score(got["name"])
            if got["name_score"] <= 0:
                # 공고문이 PDF로 안 올라온 건이다. 표본에 넣으면 '함정 없음'이
                # 몇 건 생기는데 이유가 문서가 달라서다. 세어만 두고 건너뛴다.
                skipped["공고문 아님"] += 1
                print(f"  건너뜀 seq={it['seq']} 공고문 아님: {got['name'][:40]}", file=sys.stderr)
                continue
            org_count[it["pname"]] += 1
            rows.append({
                "seq": it["seq"], "기관": it["pname"], "제목": it["title"],
                "등록일": it["bdate"], "고용형태": it["workTypeNa"], "경력": it["carrerNa"],
                **got,
            })
            print(f"[{len(rows):>2}/{want}] {it['pname']} — {got['name'][:44]}")
        time.sleep(0.4)
    doc = {
        "수집일": "2026-08-25",
        "조건": {"기간": [s_date, e_date], "고용형태": "정규직", "경력": "신입 포함",
                 "기관당 상한": max_per_org, "목표": want},
        "살펴본 공고": examined,
        "건너뜀": dict(skipped),
        "목록 실패 쪽": failed_pages,
        "채택": len(rows),
        "표본": rows,
    }
    with io.open("docs/phase0-manifest.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"\n살펴본 공고 {examined} · 건너뜀 {dict(skipped)} · 채택 {len(rows)}")


if __name__ == "__main__":
    main(want=int(sys.argv[1]) if len(sys.argv) > 1 else 20)
