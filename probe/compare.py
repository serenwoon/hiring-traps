"""골든셋과 에이전트 출력을 대조한다. 점수를 내지 않는다.

표본이 셋이라 정확도를 계산하면 33% 단위로만 움직인다. 그런 수는 뜻이 없다.
대신 어디가 어떻게 다른지를 나란히 놓고 사람이 읽게 한다.
"""
import io
import json
import sys
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def machine(file_no, agent_suffix):
    hits = list(Path("fixtures/studio").glob(f"{file_no}__{agent_suffix}.json"))
    if not hits:
        return None
    d = json.load(io.open(hits[0], encoding="utf-8"))
    return json.loads(d["output"][0]["content"][0]["text"])


def main(agent_suffix="DfxGLjFv"):
    for p in sorted(Path("docs/golden").glob("*.json")):
        g = json.load(io.open(p, encoding="utf-8"))
        m = machine(g["fileNo"], agent_suffix)
        print(f"\n===== {g['기관']} ({g['쪽수']}쪽) =====")
        if m is None:
            print("  기계 출력 없음")
            continue
        t = g["함정"]
        db = m.get("date_bases", [])
        print(f"자격기준일  사람={t['자격기준일']['판정']}/{t['자격기준일'].get('값','')}"
              f"  기계={len(db)}줄 시점 {len({x.get('basis') for x in db})}종")
        req = m.get("requirements", [])
        print(f"필수와우대  사람={t['필수와우대']['판정']}"
              f"  기계={dict(Counter(r.get('kind') for r in req))}")
        bs = m.get("bonus_stacking", [])
        print(f"가점중복    사람={t['가점중복']['판정']}/{t['가점중복'].get('값','')}"
              f"  기계={[x.get('rule') for x in bs]}")
        print(f"가점조건    기계={len(m.get('bonus_conditions', []))}건")
        docs = m.get("documents", [])
        print(f"서류        사람={t['서류리드타임']['판정']}"
              f"  기계={len(docs)}건 {dict(Counter(x.get('when') for x in docs))}")


if __name__ == "__main__":
    main(*sys.argv[1:])
