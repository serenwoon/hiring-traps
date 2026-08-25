"""Studio 노드 14 종의 계약을 오류 메시지로 캔다.

문서를 못 찾아서 찔러 보는 방식이다. 빈 설정을 보내면 서버가 무엇이 빠졌는지
알려주고, 그것을 채워 다시 보내면 다음 것을 알려준다. 받아줄 때까지 반복한다.

만드는 것은 전부 임시 에이전트 하나 위에 올리고 끝나면 지운다.
"""
import io
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

V2 = "https://api.upstage.ai/v2"
TYPES = ["validate", "match", "export", "merge", "review", "instruct",
         "class-generate", "class-update", "schema-generate", "schema-update",
         "instruct-generate", "document-classify", "document-parse",
         "information-extract"]

# 오류가 필드를 요구하면 채워 넣을 값. 종류를 모르니 몇 가지를 돌아가며 시도한다.
GUESSES = ["x", [], {}, 1, True, [{"name": "x"}], "text"]


def key():
    for line in io.open(".env", encoding="utf-8"):
        if line.startswith("UPSTAGE_API_KEY="):
            k = line.split("=", 1)[1].strip()
            if k:
                return k
    raise SystemExit(".env 의 UPSTAGE_API_KEY 가 비어 있다")


def call(path, k, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(V2 + path, data,
                                 {"Authorization": "Bearer " + k,
                                  "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return True, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return False, e.read().decode("utf-8", "replace")


def missing_fields(msg):
    """pydantic 오류 문장에서 빠진 필드 이름을 긁는다."""
    out = []
    for m in re.finditer(r"\n\s*([A-Za-z_][\w.]*)\n\s*Field required", msg):
        out.append(m.group(1).split(".")[-1])
    for m in re.finditer(r"requires a non-empty '(\w+)'", msg):
        out.append(m.group(1))
    return out


def probe(tp, k, agent_id, rounds=6):
    """한 종류를 받아줄 때까지 채워 본다. 오류 사슬을 그대로 남긴다."""
    data, chain = {}, []
    for _ in range(rounds):
        steps = [{"name": "p", "type": "document-parse",
                  "data": {"model": "document-parse"},
                  "next_steps": [{"step_name": "x", "condition": None}], "is_first": True},
                 {"name": "x", "type": tp, "data": dict(data),
                  "next_steps": [] if tp != "review" else None, "is_first": False}]
        if tp in ("document-parse",):
            steps = [steps[0]]
            steps[0]["next_steps"] = []
        ok, r = call(f"/agents/{agent_id}/configs", k,
                     {"name": f"probe-{tp}", "is_default": False, "steps": steps}, "POST")
        if ok:
            return {"type": tp, "받아준 data": data, "오류사슬": chain}
        try:
            msg = json.loads(r)["error"]["message"]
        except Exception:
            msg = r[:400]
        chain.append(msg[:300])
        need = missing_fields(msg)
        if not need:
            return {"type": tp, "받아준 data": None, "오류사슬": chain, "멈춘이유": "필드를 못 읽음"}
        for f in need:
            if f not in data:
                data[f] = GUESSES[0]
        # 값 종류가 틀렸다고 하면 다음 후보로 바꿔 본다
        for m in re.finditer(r"\n\s*([A-Za-z_][\w.]*)\n\s*Input should be a valid (\w+)", msg):
            f, want = m.group(1).split(".")[-1], m.group(2)
            data[f] = {"list": [], "dictionary": {}, "integer": 1,
                       "boolean": True, "string": "x"}.get(want, "x")
    return {"type": tp, "받아준 data": None, "오류사슬": chain, "멈춘이유": f"{rounds}회 넘김"}


def main():
    k = key()
    a = call("/agents", k, {"name": "probe-contracts", "description": "노드 계약 탐색"}, "POST")[1]
    results = []
    try:
        for tp in TYPES:
            r = probe(tp, k, a["id"])
            results.append(r)
            mark = "받아줌" if r["받아준 data"] is not None else r.get("멈춘이유", "실패")
            print(f"  {tp:<20} {mark:<12} {list((r['받아준 data'] or {}).keys())}")
    finally:
        call(f"/agents/{a['id']}", k, method="DELETE")
        print("프로브 에이전트 정리")
    Path("docs").mkdir(exist_ok=True)
    io.open("docs/node-contracts.json", "w", encoding="utf-8", newline="\n").write(
        json.dumps(results, ensure_ascii=False, indent=1))
    print("-> docs/node-contracts.json")


if __name__ == "__main__":
    main()
