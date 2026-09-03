"""추출 결과의 인용이 원본 PDF 에 글자 그대로 서는지 본다. 점수를 내지 않는다.

기계가 뽑은 항목마다 quote 가 붙어 있다. 그 문장이 원문에 실제로 있는지는
모델을 부르지 않고 문자열로 확인할 수 있다. 여기까지가 이 스크립트다.

그런데 「원문에 없다」의 개수가 내가 고르는 것들에 따라 크게 움직인다. 손잡이가
둘이다 -- 대조 전에 무엇을 지우는가(정규화), 그리고 fitz 에게 쪽을 어떤 순서로
읽게 하는가(읽기 순서). 그래서 한 값을 고르지 않고 격자를 그대로 낸다. 하나를
고르면 그 수가 「모델이 틀린 비율」로 읽히는데, 그건 이 스크립트가 잴 수 있는
것이 아니다.

재는 자가 둘이다. 인용은 파싱이 읽은 텍스트에서 나왔고 대조 대상은 fitz 가
읽은 텍스트다. 둘이 다르면 어느 쪽이 원문인지 이 스크립트는 모른다.

Upstage 키가 필요 없다. 네트워크도 안 쓴다. 다만 fixtures/live 의 PDF 가 있어야
돈다 -- 그 폴더는 .gitignore 대상이라 저장소에 없다. probe/collect.py 로 먼저
받는다. docs/phase0-manifest.json 의 sha256 으로 같은 파일인지 대조한다.
"""
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

STUDIO = Path("fixtures/studio")
LIVE = Path("fixtures/live")

# 손잡이 하나 -- 대조 전에 무엇을 지우는가. 어느 칸이 옳은지 정하지 않는다.
#
# 🔴 태그 제거는 마크업만 지우지 않는다. `<우리공단공정채용주요사항>` 같은
#    한국어 소제목도 같이 지운다. 그러니 그 칸은 "마크업을 걷어낸 값"이 아니라
#    "꺾쇠 안을 전부 걷어낸 값"이다. 아래 「따로 세는 값」이 그 크기를 낸다.
#
# 🔴 칸을 늘리는 것은 이 저장소가 재는 기록에서 처방으로 넘어가는 지점이다.
#    한국 공문서에서 무엇을 지워야 하는지를 여기에 쌓기 시작하면 그건 노하우고,
#    이 저장소가 하기로 한 일이 아니다.
STRIP = [
    ("그대로", lambda s: s),
    ("+공백", lambda s: re.sub(r"\s+", "", s)),
    ("+태그", lambda s: re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", s))),
    ("+제어문자", lambda s: re.sub(r"[\x00-\x1f]", "", re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", s)))),
]

# 손잡이 둘 -- fitz 에게 쪽을 어떤 순서로 읽게 하는가. 정규화와 같은 층의 선택이고
# 크기도 비슷하다. 표시 없이 하나를 고르면 나머지 손잡이만 보이게 된다.
ORDER = [("기본", False), ("sort=True", True)]

# 파일별 표를 세울 때 한 칸을 골라야 정렬이 된다. 아래 칸으로 고정한다.
# 🔴 이 칸이 정답이라는 뜻이 아니다. 다른 칸으로 고르면 순서가 뒤집힌다 --
#    +제어문자 로 고르면 표 머리의 파일이 64 에서 0 으로 떨어진다.
PIVOT_STRIP = "+태그"
PIVOT_ORDER = "기본"


def page_text(pdf_path, sort):
    doc = fitz.open(pdf_path)
    try:
        return "\n".join(page.get_text(sort=sort) for page in doc)
    finally:
        doc.close()


def quotes(node, found):
    """중첩된 출력 어디에 있든 quote 를 전부 긁는다. 스키마가 축마다 다르다.

    🔴 값이 문자열일 때만 담는다. 스키마가 바뀌어 quote 가 리스트가 되면
       조용히 줄어드는 자리다. 지금 코퍼스에서는 누락 0 건을 확인했다.
    """
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
    """envelope 안의 JSON 을 푼다. 못 풀면 알린다 -- 조용히 넘기지 않는다.

    분류에서 멈춘 판은 text 가 JSON 이 아니다. 그걸 그냥 통과시키면 인용 0 칸에
    못 찾은 칸 0 이라 「검사했고 전부 통과」와 같은 화면이 된다.
    """
    raw = json.load(io.open(path, encoding="utf-8"))
    try:
        return json.loads(raw["output"][0]["content"][0]["text"]), True
    except (KeyError, IndexError, TypeError, ValueError):
        return raw, False


def width(s):
    """한글은 두 칸을 차지한다. 표를 맞추려면 문자 수가 아니라 표시 폭이다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def pad(s, w):
    return " " * max(0, w - width(s)) + str(s)


def aside(pdfs):
    """따로 세는 값 둘. 사다리로는 안 나오는데 위 두 주석이 근거로 대는 것들이다."""
    ctrl, angle = [], 0
    for file_no, pdf in pdfs:
        text = page_text(pdf, False)
        n = sum(1 for c in text if ord(c) < 0x20 and c not in "\n\r\t")
        if n:
            ctrl.append((file_no, n))
        if [m for m in re.findall(r"<[^>]+>", text) if re.search(r"[가-힣]", m)]:
            angle += 1
    ctrl.sort(key=lambda t: -t[1])
    return ctrl, angle


def main(suffix="__all"):
    files = sorted(STUDIO.glob(f"*{suffix}.json"))
    if not files:
        print(f"{STUDIO}/*{suffix}.json 이 없다")
        return 1

    rows, skipped, unparsed, pdfs = [], [], [], []
    total = unique = 0

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

        pdfs.append((file_no, pdf))
        total += len(qs)
        unique += len(set(qs))

        texts = {name: page_text(pdf, sort) for name, sort in ORDER}
        row = {"파일": file_no, "인용": len(qs)}
        for order_name, _ in ORDER:
            for strip_name, strip in STRIP:
                normalized = strip(texts[order_name])
                row[(order_name, strip_name)] = sum(1 for q in qs if strip(q) not in normalized)
        rows.append(row)

    head = (f"파일 {len(rows)}건 · 인용 {total}칸(파일 안에서 겹치는 것을 빼면 {unique}칸)"
            + (f" · PDF 없어 건너뜀 {len(skipped)}건 {skipped}" if skipped else "")
            + (f" · 인용을 못 꺼내 건너뜀 {len(unparsed)}건 {unparsed}" if unparsed else ""))
    print(head)

    if not rows:
        print()
        if skipped:
            print(f"잰 것이 없다. {LIVE} 에 PDF 를 먼저 받는다 — python probe/collect.py 20")
        else:
            print("잰 것이 없다. 인용이 든 출력이 한 건도 없다 — 분류에서 멈춘 판으로 보인다.")
        return 1

    print()
    print("격자 — 원문에서 못 찾은 칸. 손잡이가 둘이다")
    print("  " + pad("", 12) + "".join(pad(n, 14) for n, _ in STRIP))
    for order_name, _ in ORDER:
        cells = []
        for strip_name, _ in STRIP:
            n = sum(r[(order_name, strip_name)] for r in rows)
            cells.append(pad(f"{n} ({n / total * 100:.1f}%)", 14))
        print("  " + pad(order_name, 12) + "".join(cells))
    print()
    print("  같은 입력이다. 지우는 줄을 하나 더 쓰거나 읽기 순서를 바꿀 때마다 답이 움직인다.")
    print("  어느 칸이 맞는지 이 스크립트는 정하지 않는다.")
    print("  가로로 줄어드는 것은 정의상 그렇게 된다 — 정보는 방향이 아니라 낙폭의 크기다.")
    print()

    key = (PIVOT_ORDER, PIVOT_STRIP)
    rows.sort(key=lambda r: -r[key])
    zero = sum(1 for r in rows if r[key] == 0)
    print(f"파일별 — 격자에서 「{PIVOT_ORDER} · {PIVOT_STRIP}」 칸 하나를 골라 세운 표다")
    cols = ["파일", "인용"] + [n for n, _ in STRIP]
    print("  " + "".join(pad(c, 12) for c in cols))
    for r in rows:
        cells = [pad(r["파일"], 12), pad(r["인용"], 12)]
        cells += [pad(r[(PIVOT_ORDER, n)], 12) for n, _ in STRIP]
        print("  " + "".join(cells))
    print()
    print(f"  못 찾은 칸이 0 인 파일 {zero}/{len(rows)}건. 고르게 퍼져 있지 않다.")
    print("  다른 칸을 골라 정렬하면 이 순서가 뒤집힌다.")
    print()

    ctrl, angle = aside(pdfs)
    print("따로 세는 값 — 위 표로는 안 나오는데 격자를 읽을 때 필요한 것들")
    if ctrl:
        top = ", ".join(f"{f} {n:,}개" for f, n in ctrl[:3])
        print(f"  제어문자가 든 PDF {len(ctrl)}/{len(rows)}건. 많은 순: {top}")
    print(f"  꺾쇠 안이 한국어인 줄이 있는 PDF {angle}/{len(rows)}건 — 「+태그」 칸이 같이 지우는 것들이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "__all"))
