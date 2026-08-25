"""Phase 0 위치 측정기. 판정하지 않는다 — 후보 줄을 위치와 함께 뱉을 뿐이다.

함정이냐 아니냐는 사람이 정한다. 이 스크립트가 정하면 내가 만든 어휘 목록이
곧 정답이 되어버려서, 재는 장치가 아니라 자기 확인 장치가 된다.
"""
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import fitz  # PyMuPDF

HIDDEN_MARKS = ("※", "*", "(", "（", "주)", "註")


def body_size(doc):
    """본문 글자 크기 = 문자 수가 가장 많은 크기."""
    c = Counter()
    for page in doc:
        for blk in page.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                for span in line.get("spans", []):
                    c[round(span["size"], 1)] += len(span["text"])
    return c.most_common(1)[0][0] if c else 0.0


def scan(pdf_path, phrases):
    doc = fitz.open(pdf_path)
    base = body_size(doc)
    hits = []
    for pno, page in enumerate(doc, 1):
        h = page.rect.height
        for blk in page.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                text = "".join(s["text"] for s in line.get("spans", [])).strip()
                if not text:
                    continue
                sizes = [s["size"] for s in line["spans"]]
                size = round(max(sizes), 1)
                for concept, words in phrases.items():
                    if concept.startswith("_"):
                        continue
                    matched = [w for w in words if w in text]
                    if not matched:
                        continue
                    hits.append({
                        "concept": concept,
                        "page": pno,
                        "size": size,
                        "rel_size": round(size - base, 1),
                        "y": round(line["bbox"][1] / h, 3),
                        "hidden_mark": any(m in text for m in HIDDEN_MARKS),
                        "matched": matched,
                        "text": text[:160],
                    })
    return {"pages": doc.page_count, "body_size": base, "hits": hits}


def main():
    phrases = json.load(io.open("probe/phrases.json", encoding="utf-8"))
    manifest = json.load(io.open("docs/phase0-manifest.json", encoding="utf-8"))["표본"]
    out = []
    for row in manifest:
        p = Path(row["path"])
        if not p.exists():
            print(f"없음: {p}", file=sys.stderr)
            continue
        try:
            res = scan(str(p), phrases)
        except Exception as exc:
            print(f"실패 {p.name}: {exc}", file=sys.stderr)
            continue
        res.update({"seq": row["seq"], "기관": row["기관"], "제목": row["제목"],
                    "fileNo": row["fileNo"], "sha256": row["sha256"]})
        out.append(res)
        per = Counter(h["concept"] for h in res["hits"])
        print(f"{row['기관'][:16]:<16} {res['pages']:>3}쪽 본문{res['body_size']}pt  " +
              " ".join(f"{k}={v}" for k, v in per.items()))
    with io.open("docs/phase0-hits.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n문서 {len(out)}건 -> docs/phase0-hits.json")


if __name__ == "__main__":
    main()
