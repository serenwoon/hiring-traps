"""인용이 원문의 어디에 앉아 있는지 본다. 판정하지 않는다.

probe/recheck.py 가 「인용이 원문에 있나」를 물었다. 있는 것에 대해 다음
질문은 「어디에 있나」다. 이 저장소가 처음 묻기로 한 것이 그것이고, README 가
안 한 것으로 적어둔 첫 줄이기도 하다 -- 추출 결과에는 쪽 번호만 오고 그 줄이
각주인지 괄호인지가 안 담긴다.

probe/locate.py 가 위치를 재긴 하는데 손으로 만든 어휘 목록(probe/phrases.json)
으로 줄을 찾는다. 그 파일 머리가 스스로 걱정을 적어뒀다 -- 내가 만든 목록이
곧 정답이 되어버린다고. 이제 기계가 낸 인용이 793 칸 있으니 목록이 필요 없다.
줄을 고르는 것이 내 어휘가 아니라 추출 결과다.

함정이냐 아니냐는 여전히 사람이 정한다. 이 스크립트는 위치를 뱉을 뿐이다.

고르는 자리가 둘이라 둘 다 낸다.
  - 인용이 여러 줄에 걸치면 어느 줄의 위치를 쓰나 (첫 줄 / 가장 작은 줄)
  - 「숨어 있다」의 표시를 무엇으로 보나 (표시마다 따로 센다. 뭉치지 않는다)

Upstage 키가 필요 없다. 네트워크도 안 쓴다. fixtures/live 의 PDF 가 있어야
돈다 -- probe/collect.py 로 먼저 받는다.
"""
import io
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

STUDIO = Path("fixtures/studio")
LIVE = Path("fixtures/live")

# recheck.py 의 「기본 · +태그」 칸과 같은 정규화다. 거기서 622 칸이 원문에 섰고
# 이 스크립트는 그 622 칸의 자리를 본다. 정규화를 바꾸면 분모부터 바뀐다.
NORM = lambda s: re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", s))

# 🔴 하나의 불리언으로 뭉치지 않는다. probe/locate.py 는 이 여섯을 hidden_mark
#    하나로 묶었는데, 재보니 그중 괄호가 절반을 만든다. 괄호는 어느 문서에나
#    있으니 「숨어 있다」의 근거로는 약하다. 표시마다 따로 센다.
MARKS = [("※", "※"), ("*", "*"), ("（", "（"), ("주)", "주)"), ("註", "註"), ("(", "( 괄호")]
WEAK = {"( 괄호", "（"}

# 걸친 인용의 자리를 어느 줄로 잡나. 고르지 않고 둘 다 낸다.
PICKS = [("첫 줄", lambda sp: sp[0]), ("가장 작은 줄", lambda sp: min(sp, key=lambda l: l["size"]))]


def quotes(node, found):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "quote" and isinstance(value, str) and value.strip():
                found.append(value)
            else:
                quotes(value, found)
    elif isinstance(node, list):
        for value in node:
            quotes(value, found)
    return found


def payload(path):
    raw = json.load(io.open(path, encoding="utf-8"))
    try:
        return json.loads(raw["output"][0]["content"][0]["text"]), True
    except (KeyError, IndexError, TypeError, ValueError):
        return raw, False


def read_lines(pdf_path):
    """줄마다 텍스트와 위치. 본문 글자 크기는 문자 수가 가장 많은 크기로 잡는다."""
    doc = fitz.open(pdf_path)
    try:
        sizes = Counter()
        for page in doc:
            for blk in page.get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    for span in line.get("spans", []):
                        sizes[round(span["size"], 1)] += len(span["text"])
        base = sizes.most_common(1)[0][0] if sizes else 0.0

        lines = []
        for pno, page in enumerate(doc, 1):
            height = page.rect.height
            for blk in page.get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    raw = "".join(s["text"] for s in line.get("spans", [])).strip()
                    if not raw:
                        continue
                    size = round(max(s["size"] for s in line["spans"]), 1)
                    lines.append({
                        "norm": NORM(raw), "raw": raw, "page": pno, "size": size,
                        "rel": round(size - base, 1), "y": round(line["bbox"][1] / height, 3),
                    })
        return lines, base
    finally:
        doc.close()


def span_of(quote, lines, joined):
    """인용이 걸치는 줄들. 못 찾으면 빈 리스트.

    🔴 세 번째 고르는 자리다. 같은 문자열이 문서에 두 번 이상 나오는 인용이
       622 칸 중 34 칸이고, 그때 어느 자리를 그 인용의 위치로 볼지는 정해져
       있지 않다. 여기서는 앞에서부터 첫 자리를 쓴다.

       그리고 한 줄에 통째로 들어가는 줄이 따로 있는데 이어붙인 문자열의 첫
       자리는 두 줄에 걸치는 경우가 2 칸 있다. 그런 것은 한 줄 쪽을 쓴다 --
       줄을 넘어가며 우연히 이어진 것보다 한 줄 안에 실제로 있는 쪽이 그
       인용의 자리에 가깝다. 이것도 고른 것이지 정해진 것이 아니다.
    """
    nq = NORM(quote)
    if not nq or nq not in joined:
        return []
    for line in lines:
        if nq in line["norm"]:
            return [line]
    start = joined.index(nq)
    end = start + len(nq)
    out, acc = [], 0
    for line in lines:
        if acc + len(line["norm"]) > start and acc < end:
            out.append(line)
        acc += len(line["norm"])
    return out


def band(rel):
    return "본문보다 작다" if rel < -0.05 else ("본문보다 크다" if rel > 0.05 else "본문 크기")


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def pad(s, w):
    return " " * max(0, w - width(s)) + str(s)


def main(suffix="__all"):
    files = sorted(STUDIO.glob(f"*{suffix}.json"))
    if not files:
        print(f"{STUDIO}/*{suffix}.json 이 없다")
        return 1

    seat = Counter()
    spread = Counter()
    repeated = 0
    picks = {name: Counter() for name, _ in PICKS}
    split = 0
    marks = Counter()
    weak_only = 0
    ys = {name: [] for name, _ in PICKS}
    skipped, unparsed = [], []
    total = 0

    for path in files:
        file_no = path.name.split("__")[0]
        pdf = LIVE / f"{file_no}.pdf"
        if not pdf.exists():
            skipped.append(file_no)
            continue
        data, ok = payload(path)
        if not ok:
            unparsed.append(file_no)
            continue
        qs = quotes(data, [])
        if not qs:
            unparsed.append(file_no)
            continue

        lines, _ = read_lines(pdf)
        joined = "".join(l["norm"] for l in lines)
        total += len(qs)

        for q in qs:
            sp = span_of(q, lines, joined)
            if not sp:
                seat["원문에서 못 찾음"] += 1
                continue
            seat["한 줄 안에 통째로" if len(sp) == 1 else "여러 줄에 걸침"] += 1
            spread[len(sp)] += 1
            if joined.count(NORM(q)) > 1:
                repeated += 1

            chosen = {}
            for name, pick in PICKS:
                line = pick(sp)
                chosen[name] = line
                picks[name][band(line["rel"])] += 1
                ys[name].append(line["y"])
            if chosen[PICKS[0][0]] is not chosen[PICKS[1][0]]:
                split += 1

            found = {label for mark, label in MARKS if any(mark in l["raw"] for l in sp)}
            for label in found:
                marks[label] += 1
            if found and found <= WEAK:
                weak_only += 1

    print(f"인용 {total}칸"
          + (f" · PDF 없어 건너뜀 {len(skipped)}건 {skipped}" if skipped else "")
          + (f" · 인용을 못 꺼내 건너뜀 {len(unparsed)}건 {unparsed}" if unparsed else ""))

    located = seat["한 줄 안에 통째로"] + seat["여러 줄에 걸침"]
    if not located:
        print()
        if skipped:
            print(f"잰 것이 없다. {LIVE} 에 PDF 를 먼저 받는다 — python probe/collect.py 20")
        else:
            print("잰 것이 없다. 원문에 서는 인용이 한 칸도 없다.")
        return 1

    print()
    print("① 인용이 PDF 줄에 어떻게 앉나")
    for key in ("한 줄 안에 통째로", "여러 줄에 걸침", "원문에서 못 찾음"):
        n = seat[key]
        print(f"  {pad(key, 20)} {n:5}  ({n / total * 100:.1f}%)")
    top = ", ".join(f"{k}줄 {v}" for k, v in sorted(spread.items())[:5])
    print(f"  걸친 줄 수: {top} …")
    print("  못 찾은 칸은 probe/recheck.py 의 「기본 · +태그」 칸과 같은 수다.")
    print(f"  같은 문자열이 문서에 두 번 이상 나오는 인용 {repeated}칸. 앞에서부터 첫 자리를 썼다.")
    print()

    print(f"② 걸친 인용의 자리를 어느 줄로 잡나 — 고르지 않고 둘 다 낸다 (분모 {located})")
    bands = ["본문보다 작다", "본문 크기", "본문보다 크다"]
    print("  " + pad("", 14) + "".join(pad(b, 15) for b in bands) + pad("세로 위치 중앙값", 18))
    for name, _ in PICKS:
        cells = "".join(pad(f"{picks[name][b]} ({picks[name][b] / located * 100:.0f}%)", 15) for b in bands)
        med = sorted(ys[name])[len(ys[name]) // 2]
        print("  " + pad(name, 14) + cells + pad(f"{med:.3f}", 18))
    print(f"  두 규칙이 다른 줄을 고른 인용 {split}칸 ({split / located * 100:.1f}%). 나머지는 같은 줄이다.")
    print()

    print(f"③ 걸린 줄에 있는 표시 — 하나로 뭉치지 않는다 (분모 {located})")
    for label, _ in [(l, m) for m, l in MARKS]:
        n = marks[label]
        if n:
            print(f"  {pad(label, 12)} {n:5}  ({n / located * 100:.1f}%)")
    print(f"  이 중 괄호밖에 없는 것 {weak_only}칸 ({weak_only / located * 100:.1f}%).")
    print("  괄호는 어느 문서에나 있어 「숨어 있다」의 근거로는 약하다.")
    print("  probe/locate.py 는 위 표시를 hidden_mark 하나로 묶는다. 그 값의 절반쯤이 괄호다.")
    print()
    print("함정이냐 아니냐는 이 스크립트가 정하지 않는다. 위치만 뱉는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "__all"))
