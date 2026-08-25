"""백엔드 판정. Studio 는 뽑기만 하고 여기서 판정한다.

두 단계로 나눈 이유가 있다.

  겹침을 찾는 것    -> 코드. 집합 연산이라 LLM 을 쓰면 편차만 들어온다
  겹침이 풀렸는지   -> Solar. 「이 전형에서는 해당 가점을 적용하지 않는다」 같은
                       줄이 그 겹침을 정리한 것인지는 언어를 읽어야 안다

그리고 추출 자체가 실행마다 흔들려서(docs/variance.md) 여러 판을 합집합으로
모으고 몇 판에서 나왔는지를 같이 남긴다. 1/3 과 3/3 은 같은 값이 아니다.
"""
import io
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SOLAR = "https://api.upstage.ai/v1/chat/completions"
MODEL = "solar-pro2"

PREF_WORDS = ("우대", "가점", "특전", "가산")
# 겹침 후보를 만들 때 무시할 낱말. 이것들이 겹치는 건 뜻이 없다.
STOP = {"자에", "한함", "해당", "경우", "이상", "이하", "관한", "의한", "따른", "기준",
        "법률", "지원", "대상", "제출", "서류", "필수", "증명서", "확인서", "공고",
        "마감일", "채용", "응시", "가능", "여부", "등록", "관련", "우리", "병원"}


def tokens(text):
    """한글 두 글자 이상 낱말만. 조사는 대충 떼고 간다 -- 형태소 분석기를 안 쓴다."""
    raw = re.findall(r"[가-힣]{2,}", text or "")
    out = set()
    for w in raw:
        # 🔴 자른 것과 안 자른 것을 둘 다 넣는다. 조사 목록에 「인」이 들어 있어서
        #    「장애인」이 「장애」로 잘리고 「장애인은」은 「장애인」이 되어, 같은 낱말이
        #    자리에 따라 다른 토큰이 됐다 (2026-08-25 실측). 형태소 분석기를 안 쓰는
        #    대가이고, 둘 다 넣으면 어느 쪽으로 잘리든 교집합이 선다.
        forms = {w}
        for suf in ("으로", "에게", "에서", "이나", "라도", "까지", "부터", "이며", "하는",
                    "인", "은", "는", "이", "가", "을", "를", "의", "도"):
            if len(w) > 2 and w.endswith(suf):
                forms.add(w[: -len(suf)])
                break
        for f in forms:
            if len(f) >= 2 and f not in STOP:
                out.add(f)
    return out


def is_pref(section):
    return any(w in (section or "") for w in PREF_WORDS)


def merge(runs):
    """여러 판을 합집합으로. 같은 항목은 원문 인용으로 묶고 지지 판수를 센다."""
    bag = defaultdict(lambda: {"item": "", "section": "", "quotes": set(), "pages": set(), "support": 0})
    for j in runs:
        seen = set()
        for r in j.get("requirements", []):
            key = re.sub(r"\s+", "", (r.get("item") or ""))[:40]
            if not key:
                continue
            e = bag[key]
            e["item"] = e["item"] or r.get("item", "")
            e["section"] = e["section"] or r.get("section", "")
            if r.get("quote"):
                e["quotes"].add(r["quote"][:200])
            if r.get("source_page"):
                e["pages"].add(r["source_page"])
            if key not in seen:
                e["support"] += 1
                seen.add(key)
    return bag


def ask_solar(key, overlap, context):
    prompt = (
        "공공기관 채용공고를 읽는다. 아래 자격 항목이 응시자격 절과 우대 절에 모두 나온다.\n\n"
        f"[응시자격 쪽]\n{overlap['req_quote']}\n\n[우대 쪽]\n{overlap['pref_quote']}\n\n"
        f"[문서에서 뽑은 관련 줄]\n{context}\n\n"
        "문서가 이 겹침을 이미 정리해 두었는가? 「이 전형에서는 해당 가점을 적용하지 않는다」"
        "처럼 적어 둔 줄이 있으면 정리한 것이다.\n"
        "RESOLVED 또는 UNRESOLVED 한 낱말로 먼저 답하고, 줄바꿈 뒤에 근거가 된 원문을 "
        "그대로 한 줄 적는다. 근거가 없으면 빈 줄로 둔다."
    )
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 300, "temperature": 0}).encode()
    req = urllib.request.Request(SOLAR, body, {"Authorization": "Bearer " + key,
                                               "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        txt = json.loads(r.read())["choices"][0]["message"]["content"].strip()
    verdict = "RESOLVED" if txt.upper().startswith("RESOLVED") else "UNRESOLVED"
    evidence = txt.split("\n", 1)[1].strip() if "\n" in txt else ""
    return verdict, evidence


def api_key():
    for line in io.open(".env", encoding="utf-8"):
        if line.startswith("UPSTAGE_API_KEY="):
            k = line.split("=", 1)[1].strip()
            if k:
                return k
    raise SystemExit(".env 의 UPSTAGE_API_KEY 가 비어 있다")


def main(*paths):
    runs = []
    for p in paths:
        d = json.load(io.open(p, encoding="utf-8"))
        runs.append(json.loads(d["output"][0]["content"][0]["text"]))
    n = len(runs)
    bag = merge(runs)
    reqs = {k: v for k, v in bag.items() if not is_pref(v["section"])}
    prefs = {k: v for k, v in bag.items() if is_pref(v["section"])}
    print(f"판 {n}개 합침 · 자격 {len(reqs)} · 우대 {len(prefs)}")

    # 🔴 불용어 목록을 손으로 채우면 문서가 커질 때 무너진다. 4쪽짜리로 만든 목록이
    #    28쪽에서 겹침 46건을 냈고 그중 「조에」·「공단」·「또는」이 대부분이었다.
    #    대신 이 문서 안에서 얼마나 흔한지로 거른다 -- 여러 항목에 나오는 낱말은
    #    구별에 쓸모가 없다. 문서마다 기준이 다시 계산되니 목록을 안 늘려도 된다.
    df = defaultdict(int)
    for v in bag.values():
        for w in tokens(v["item"]):
            df[w] += 1
    total = max(1, len(bag))
    # 🔴 비율만으로 거르면 항목 수가 줄 때 무너진다. 스키마를 좁혀 자격이 22개에서
    #    11개가 되자 「장애인」이 3/12=25% 가 되어 흔한 낱말로 버려졌고, 지지 3/3 이던
    #    진짜 신호가 0건이 됐다. 절대 개수를 같이 걸어 작은 문서를 지킨다.
    common = {w for w, c in df.items() if c >= 4 and c / total > 0.10}
    print(f"흔해서 버린 낱말 {len(common)}개: {sorted(common)[:10]}")

    # 1단계 코드: 겹침 후보
    cands = []
    for rk, rv in reqs.items():
        rt = tokens(rv["item"]) - common
        for pk, pv in prefs.items():
            shared = rt & (tokens(pv["item"]) - common)
            # 🔴 겹침 하나로는 부족하다. 「또는」·「따라」 같은 두 글자 기능어가 빈도
            #    필터를 아슬아슬하게 통과해 후보를 만들었다. 둘 이상 겹치거나,
            #    하나라도 세 글자 이상이면 올린다 -- 실측한 진짜 신호는 「장애인」(3자)과
            #    「장애·장애인·장애인고용촉진·직업재활법」(4개)이었다.
            if shared and not (len(shared) >= 2 or any(len(w) >= 3 for w in shared)):
                shared = set()
            if shared:
                cands.append({"req": rv, "pref": pv, "shared": sorted(shared),
                              "req_quote": " / ".join(list(rv["quotes"])[:2]),
                              "pref_quote": " / ".join(list(pv["quotes"])[:2])})
    print(f"코드가 찾은 겹침 후보 {len(cands)}건")

    # 2단계 Solar: 문서가 그 겹침을 정리했나
    key = api_key()
    context = "\n".join(list(v["quotes"])[0] for v in bag.values() if v["quotes"])[:3000]
    out = []
    for c in cands:
        verdict, evidence = ask_solar(key, c, context)
        kind = "REQUIRED" if verdict == "RESOLVED" else "UNCLEAR"
        out.append({"item": c["req"]["item"], "shared": c["shared"], "solar": verdict,
                    "evidence": evidence, "kind": kind,
                    "support": f"{c['req']['support']}/{n}"})
        print(f"  {c['shared']} -> {verdict} -> {kind}  (지지 {c['req']['support']}/{n})")

    result = {"실행판수": n, "자격": len(reqs), "우대": len(prefs),
              "겹침후보": len(cands), "판정": out,
              "항목별지지": {v["item"][:50]: f"{v['support']}/{n}" for v in bag.values()}}
    Path("docs").mkdir(exist_ok=True)
    io.open("docs/judged.json", "w", encoding="utf-8", newline="\n").write(
        json.dumps(result, ensure_ascii=False, indent=1))
    print("-> docs/judged.json")


if __name__ == "__main__":
    main(*sys.argv[1:])
