"""④ 필드를 나눠 여러 호출로 뽑는다.

한 호출에 다섯 필드를 시키는 것이 낮은 모델에 부담이라는 가설을 잰다.
필드마다 에이전트를 하나씩 만들어 같은 문서에 돌리고, 한꺼번에 뽑은 판과
개수를 견준다. 비용은 호출 수만큼 늘어난다.
"""
import copy
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, "agent")
sys.path.insert(0, "probe")
import build_agent as B
import studio_run as S

V2 = "https://api.upstage.ai/v2"


def call(path, key, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(V2 + path, data,
                                 {"Authorization": "Bearer " + key,
                                  "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def one_field_steps(field):
    """그 필드 하나만 남긴 설정.

    🔴 deepcopy 가 없으면 안 된다. steps() 가 모듈 수준 스키마를 그대로 넘겨줘서,
    첫 필드를 잘라내는 순간 원본이 파괴되고 두 번째 필드에서 KeyError 가 났다.
    """
    steps = copy.deepcopy(B.steps())
    ex = steps[2]
    schema = ex["data"]["text"]["format"]["schema"]
    schema["properties"] = {field: schema["properties"][field]}
    ex["data"]["schema_layout"] = {"version": 1, "columns": [{"name": field, "source": "root"}]}
    ex["data"]["custom_name"] = f"extract_{field}"
    ex["data"]["user_system_prompt"] = (
        "입력은 공공기관 채용공고문이다. 아래 한 가지만 뽑는다. 다른 것은 보지 않는다.\n\n"
        f"뽑을 것: {field}\n\n"
        "문서에 명시된 사실만 뽑는다. 문서가 정하지 않은 칸은 빈 문자열로 둔다. "
        "quote 는 원문 그대로 옮기고 다듬지 않는다.")
    return steps


def main():
    src = sys.argv[1]
    fields = sys.argv[2:] or ["date_bases", "documents"]
    key = S.api_key()
    result, created = {}, []
    try:
        for field in fields:
            a = call("/agents", key, {"name": f"hiring-traps {field}",
                                      "description": f"④ 필드 분리 실험 — {field}"}, "POST")
            created.append(a["id"])
            call(f"/agents/{a['id']}/configs", key,
                 {"name": "single-field", "steps": one_field_steps(field),
                  "is_default": True}, "POST")
            t0 = time.time()
            f = S.upload(src, key)
            job = S.run(a["id"], f["id"], key)
            done = S.poll(job["id"], key, every=8, cap=40)
            outs = done.get("output") or []
            rows = []
            if outs:
                try:
                    rows = json.loads(outs[0]["content"][0].get("text", "{}")).get(field, [])
                except Exception:
                    pass
            result[field] = {"개수": len(rows), "초": round(time.time() - t0),
                             "토큰": done.get("usage", {}).get("total_tokens"), "값": rows}
            print(f"  {field:<16} {len(rows):>3}건  {result[field]['초']:>4}초  "
                  f"{result[field]['토큰']}tok")
        out = Path("fixtures/studio") / f"{Path(src).stem}__fieldsplit.json"
        io.open(out, "w", encoding="utf-8", newline="\n").write(
            json.dumps(result, ensure_ascii=False, indent=1))
        print(f"-> {out}")
    finally:
        # 🔴 에이전트를 먼저 만들고 설정을 나중에 붙이는 순서라, 중간에 죽으면
        #    껍데기가 남는다. 오늘 세 번 남겨서 손으로 치웠다.
        for aid in created:
            try:
                call(f"/agents/{aid}", key, method="DELETE")
            except Exception as exc:
                print(f"정리 실패 {aid}: {exc}", file=sys.stderr)
        print(f"실험 에이전트 {len(created)}개 정리")


if __name__ == "__main__":
    main()
