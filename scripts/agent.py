#!/usr/bin/env python3
# 云端 agent：在魔搭 IDE 终端里跑，靠 ntfy.sh(HTTPS 443) 收命令、回结果。
# 用法：cd /mnt/workspace && DSH_CMD_TOPIC=xxx-cmd DSH_RES_TOPIC=xxx-res nohup python3 agent.py > agent.log 2>&1 &
import os, sys, json, time, subprocess, threading, urllib.request, socket, hashlib

BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
CMD  = os.environ["DSH_CMD_TOPIC"]
RES  = os.environ["DSH_RES_TOPIC"]
HOST = socket.gethostname()
CHUNK = 3200

def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-agent"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def post(msg, title="res", tag=""):
    body = msg.encode("utf-8")
    hdr = {"Title": title, "User-Agent": "dsh-agent"}
    if tag:
        hdr["Tags"] = tag
    req = urllib.request.Request(BASE + "/" + RES, data=body, method="POST", headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status
    except Exception as e:
        print("[warn] post fail:", e, flush=True)
        return None

def send_chunks(text, seq):
    parts = [text[i:i+CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    n = len(parts)
    for i, p in enumerate(parts):
        post(p, title=f"{HOST}-{seq}-{i+1}/{n}")

def run_and_report(cmd, seq):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=True, executable="/bin/bash",
                           capture_output=True, text=True, timeout=7200)
        out = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "[timeout 7200s]", -1
    except Exception as e:
        out, rc = f"[error] {e}", -1
    dt = time.time() - t0
    head = f"=== seq={seq} rc={rc} {dt:.1f}s ===\n"
    send_chunks(head + out, seq)

seen = set()
since = int(time.time())

def main():
    global since
    print(f"[agent] host={HOST} cmd={CMD} res={RES}", flush=True)
    post(f"agent online: {HOST}", title="agent-online", tag="white_check_mark")
    while True:
        try:
            txt = http_get(f"{BASE}/{CMD}/json?poll=1&since={since}")
            since = int(time.time())
            for line in txt.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") != "message":
                    continue
                mid = ev.get("id")
                if mid in seen:
                    continue
                seen.add(mid)
                cmd = (ev.get("message") or "").strip()
                if not cmd:
                    continue
                seq = hashlib.md5((mid or str(time.time())).encode()).hexdigest()[:6]
                print(f"[cmd] {seq}: {cmd[:120]}", flush=True)
                threading.Thread(target=run_and_report, args=(cmd, seq), daemon=True).start()
        except Exception as e:
            time.sleep(2)
        time.sleep(1)

if __name__ == "__main__":
    main()