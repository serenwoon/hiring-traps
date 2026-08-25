"""agent/hiring-traps.json 을 Upstage 계정에 올린다.

팀 레포는 Studio UI 의 「에이전트 설정 일괄 가져오기」로 올렸다고 적었지만,
2026-08-25 에 재보니 POST /v2/agents 와 POST /v2/agents/{id}/configs 가 둘 다
200 이다. 문서를 읽고 단정했던 것을 실호출로 뒤집은 자리다.
"""
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://api.upstage.ai/v2"


def key():
    for line in io.open(".env", encoding="utf-8"):
        if line.startswith("UPSTAGE_API_KEY="):
            k = line.split("=", 1)[1].strip()
            if k:
                return k
    raise SystemExit(".env 의 UPSTAGE_API_KEY 가 비어 있다")


def call(path, payload=None, method=None, k=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data,
                                 {"Authorization": "Bearer " + k,
                                  "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {path}\n{e.read().decode('utf-8', 'replace')[:600]}")


def main():
    k = key()
    doc = json.load(io.open("agent/hiring-traps.json", encoding="utf-8"))
    # 이미 올린 에이전트가 있으면 설정만 얹는다. 설정을 갈아끼우면 같은 문서로
    # 앞 판과 뒤 판을 견줄 수 있다 -- 프롬프트를 고쳤을 때 그게 효과가 있었는지
    # 재려면 이 비교가 있어야 한다.
    prev = Path("agent/deployed.json")
    if prev.exists():
        rec = json.load(io.open(prev, encoding="utf-8"))
        agent = {"id": rec["agent_id"]}
        print("기존 에이전트에 설정 추가", agent["id"])
    else:
        agent = call("/agents", {"name": doc["name"], "description": doc["description"]},
                     method="POST", k=k)
        print("에이전트", agent["id"])
    n = len(call(f"/agents/{agent['id']}/configs", method="GET", k=k).get("data", [])) + 1
    cfg = call(f"/agents/{agent['id']}/configs",
               {"name": f"Config #{n}", "steps": doc["steps"], "is_default": True},
               method="POST", k=k)
    print("설정    ", cfg.get("id"), "steps", len(cfg.get("steps", [])))
    io.open("agent/deployed.json", "w", encoding="utf-8", newline="\n").write(
        json.dumps({"agent_id": agent["id"], "config_id": cfg.get("id"),
                    "config_name": cfg.get("name"), "name": doc["name"], "올린날": "2026-08-25"},
                   ensure_ascii=False, indent=1))
    print("-> agent/deployed.json")


if __name__ == "__main__":
    main()
