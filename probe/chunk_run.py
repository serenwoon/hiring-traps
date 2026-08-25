"""③ 문서를 쪼개서 넣는다. 낮은 모델에 긴 문서가 부담이라는 가설을 잰다.

절 단위로 자르는 게 이상적이지만 절 경계를 찾는 것 자체가 또 하나의 문제다.
그래서 쪽 단위로 자르되 한 쪽씩 겹쳐서 자른다 -- 쪽을 넘어가는 조항이 통째로
잘리는 것을 줄이려는 것이고, 완전히 막지는 못한다.
"""
import io
import json
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import fitz
sys.path.insert(0, "probe")
import studio_run as S


def split(src, size=5, overlap=1, out_dir="fixtures/chunks"):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    d = fitz.open(src)
    stem = Path(src).stem
    parts, start = [], 0
    while start < d.page_count:
        end = min(start + size, d.page_count)
        sub = fitz.open()
        sub.insert_pdf(d, from_page=start, to_page=end - 1)
        p = Path(out_dir) / f"{stem}_p{start + 1}-{end}.pdf"
        sub.save(p)
        parts.append((str(p), start + 1, end))
        if end >= d.page_count:
            break
        start = end - overlap
    return parts


def main():
    src, agent_id = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    key = S.api_key()
    parts = split(src, size=size)
    print(f"{Path(src).name} -> {len(parts)}조각 ({size}쪽씩, 1쪽 겹침)")
    merged, t0 = {}, time.time()
    for path, a, b in parts:
        f = S.upload(path, key)
        job = S.run(agent_id, f["id"], key)
        done = S.poll(job["id"], key, every=8, cap=40)
        outs = done.get("output") or []
        if not outs:
            print(f"  p{a}-{b}: 출력 없음 (분류에서 멈춤일 수 있다)")
            continue
        txt = outs[0]["content"][0].get("text", "")
        try:
            j = json.loads(txt)
        except Exception:
            print(f"  p{a}-{b}: JSON 아님 -> {txt[:60]}")
            continue
        counts = {k: len(v) if isinstance(v, list) else 1 for k, v in j.items()}
        print(f"  p{a}-{b}: {counts}")
        # 쪽 번호를 원본 기준으로 되돌린다. 조각 안에서는 1부터 다시 세기 때문이다.
        for k, v in j.items():
            if not isinstance(v, list):
                continue
            for row in v:
                if isinstance(row, dict) and row.get("source_page"):
                    row["source_page"] = row["source_page"] + a - 1
            merged.setdefault(k, []).extend(v)
    out = Path("fixtures/studio") / f"{Path(src).stem}__chunk{size}.json"
    io.open(out, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"조각": len(parts), "쪽당": size,
                    "걸린초": round(time.time() - t0), **merged}, ensure_ascii=False, indent=1))
    print(f"\n{time.time() - t0:.0f}초 -> {out}")


if __name__ == "__main__":
    main()
