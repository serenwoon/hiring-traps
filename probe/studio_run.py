"""Studio 에이전트 한 번 돌리기. 2026-08-22 팀 코드에서 확인된 경로 그대로.

    POST /v2/files (purpose=assistants) -> file_id
    POST /v2/responses {model: agt_..., input:[input_file]} -> job
    GET  /v2/responses/{id} 폴링

webhook이 없어서 폴링이다. 결과 문자열은 output[].content[].text 에 온다.
"""
import io
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://api.upstage.ai/v2"


def api_key():
    for line in io.open(".env", encoding="utf-8"):
        if line.startswith("UPSTAGE_API_KEY="):
            k = line.split("=", 1)[1].strip()
            if k:
                return k
    raise SystemExit(".env 에 UPSTAGE_API_KEY 가 비어 있다")


def _open(req):
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def upload(path, key):
    boundary = uuid.uuid4().hex
    data = Path(path).read_bytes()
    ctype = mimetypes.guess_type(path)[0] or "application/pdf"
    body = b""
    for name, val in (("purpose", "assistants"),):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{Path(path).name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    body += data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/files", body, {
        "Authorization": "Bearer " + key,
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _open(req)


def run(agent_id, file_id, key):
    payload = {"model": agent_id,
               "input": [{"role": "user", "content": [{"type": "input_file", "file_id": file_id}]}]}
    req = urllib.request.Request(BASE + "/responses", json.dumps(payload).encode(), {
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    return _open(req)


def poll(job_id, key, every=10, cap=40):
    for i in range(cap):
        req = urllib.request.Request(f"{BASE}/responses/{job_id}", None,
                                     {"Authorization": "Bearer " + key})
        j = _open(req)
        st = j.get("status")
        print(f"  [{i * every:>3}s] {st}")
        if st not in ("in_progress", "queued", "pending"):
            return j
        time.sleep(every)
    raise SystemExit("폴링 상한을 넘겼다")


def main():
    pdf, agent_id = sys.argv[1], sys.argv[2]
    key = api_key()
    t0 = time.time()
    f = upload(pdf, key)
    print(f"올림 file_id={f['id']} {f.get('bytes', 0) // 1024}KB")
    job = run(agent_id, f["id"], key)
    print(f"실행 job={job.get('id')} status={job.get('status')}")
    done = poll(job["id"], key)
    out = Path("fixtures/studio")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{Path(pdf).stem}__{agent_id[-8:]}.json"
    with io.open(dest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(done, fh, ensure_ascii=False, indent=1)
    print(f"\n{time.time() - t0:.0f}초 · status={done.get('status')} -> {dest}")


if __name__ == "__main__":
    main()
