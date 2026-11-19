#!/usr/bin/env python3
"""ModelScope Notebook 控制核心库（纯标准库 + requests）"""
import json, os, time, hashlib, threading, urllib.parse
import requests

BASE = "https://modelscope.cn/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(HERE, "cookie.txt")

def _headers():
    jar = open(COOKIE_FILE, encoding="utf-8").read().strip()
    return {"Cookie": jar, "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0", "Referer": "https://modelscope.cn/my/mynotebook",
            "Origin": "https://modelscope.cn"}

def _j(r):
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text[:500], "_status": r.status_code}

def list_instances(channel="dsw"):
    r = requests.get(f"{BASE}/notebooks/all", headers=_headers(),
                     params={"PageNumber": 1, "PageSize": 20, "Channel": channel}, timeout=40)
    j = _j(r)
    rows = (((j.get("Data") or {}).get("Notebooks") or {}).get("NotebookList") or [])
    out = []
    for x in rows:
        out.append({
            "id": x.get("InstanceId"), "accel": x.get("AcceleratorType"),
            "status": x.get("Status"), "gpu": x.get("GpuMemory"),
            "cpu": x.get("Cpu"), "mem": x.get("Memory"),
            "remain_sec": x.get("RemainingQuota"), "url": x.get("Url"),
            "image": x.get("Image"),
        })
    return {"ok": r.status_code == 200, "http": r.status_code, "instances": out}

def get_instance(inst_id):
    res = list_instances()
    for i in res["instances"]:
        if i["id"] == inst_id:
            return i
    return None

def start(inst_id):
    """会 403（需要滑块 token）；保留以记录服务端真实返回"""
    r = requests.put(f"{BASE}/notebooks/paid/start", headers=_headers(),
                     json={"InstanceId": inst_id, "Channel": "dsw"}, timeout=60)
    j = _j(r)
    return {"http": r.status_code, "code": j.get("Code"), "message": j.get("Message"), "raw": j}

def stop(inst_id):
    r = requests.put(f"{BASE}/notebooks/stop", headers=_headers(),
                     json={"InstanceId": inst_id}, timeout=60)
    j = _j(r)
    return {"http": r.status_code, "code": j.get("Code"), "message": j.get("Message"), "raw": j}

def ide_url(inst_id):
    i = get_instance(inst_id)
    if not i:
        return {"ok": False, "err": "instance not found"}
    if i.get("url"):
        return {"ok": True, "url": i["url"], "status": i["status"]}
    return {"ok": False, "err": f"instance status={i['status']}, url 尚未生成（需 Running）", "status": i["status"]}

def wait_running(inst_id, timeout=900, interval=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        i = get_instance(inst_id)
        if i and i["status"] in ("Running", "running") and i.get("url"):
            return {"ok": True, "instance": i, "url": i["url"], "waited": round(time.time()-t0)}
        time.sleep(interval)
    i = get_instance(inst_id)
    return {"ok": False, "instance": i, "err": f"timeout {timeout}s"}

# ---------- 双通道命令控制：ntfy 主 + GitHub gist 备 ----------
NTFY = "https://ntfy.sh"
GH_API = "https://api.github.com"
GH_UID = "shuchen1112010-netizen"

def _env():
    p = os.path.join(HERE, ".env")
    d = {}
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k] = v
    return d

def _gh_token():
    """本机从 gh CLI 取 token，不落盘、不进云端。"""
    import subprocess
    try:
        t = subprocess.run(["gh", "auth", "token"], capture_output=True,
                           text=True, timeout=10).stdout.strip()
        return t or None
    except Exception:
        return None

def _gh_headers(token):
    return {"Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}

def _gh_gist_get(token, gid):
    return requests.get(f"{GH_API}/gists/{gid}", headers=_gh_headers(token), timeout=25)

def _gh_cmd_append(cmd, gid=None, fname="cmd.jsonl"):
    """把一条命令追加到 gist 队列（本机写，需 token）。"""
    tok = _gh_token()
    if not tok:
        return {"ok": False, "err": "no gh token"}
    e = _env()
    gid = gid or e.get("GH_CMD_GIST")
    if not gid:
        return {"ok": False, "err": "no GH_CMD_GIST in .env"}
    r = _gh_gist_get(tok, gid)
    if r.status_code != 200:
        return {"ok": False, "err": f"gist get {r.status_code}"}
    cur = r.json()["files"][fname]["content"]
    mid = hashlib.md5((cmd + str(time.time())).encode()).hexdigest()[:10]
    rec = json.dumps({"id": mid, "cmd": cmd, "ts": int(time.time())}, ensure_ascii=False)
    new = cur.rstrip("\n") + "\n" + rec + "\n"
    r2 = requests.patch(f"{GH_API}/gists/{gid}", headers=_gh_headers(tok),
                        json={"files": {fname: {"content": new}}}, timeout=25)
    return {"ok": r2.status_code == 200, "http": r2.status_code,
            "channel": "github", "id": mid}

def send_cmd(cmd, topic=None, prefer=None):
    """下发命令：ntfy 主；失败/限流时自动切 GitHub gist。prefer 可强制通道。"""
    e = _env()
    t = topic or e.get("DSH_CMD_TOPIC")
    channel = prefer or e.get("CMD_PREFER", "ntfy")
    # 强制走 github
    if channel == "github":
        return _gh_cmd_append(cmd)
    # 主力 ntfy
    try:
        r = requests.post(f"{NTFY}/{t}", data=cmd.encode("utf-8"), timeout=30)
        if r.status_code == 200:
            return {"ok": True, "http": 200, "channel": "ntfy"}
        err = f"ntfy {r.status_code}"
    except Exception as ex:
        err = f"ntfy err {str(ex)[:80]}"
    # 回退 GitHub
    e2 = _env()
    if e2.get("GH_FALLBACK", "1") == "1":
        g = _gh_cmd_append(cmd)
        g["fallback_from"] = err
        return g
    return {"ok": False, "err": err}

def collect_res(since, topic=None, limit=200):
    e = _env()
    t = topic or e.get("DSH_RES_TOPIC")
    r = requests.get(f"{NTFY}/{t}/json", params={"poll": 1, "since": since}, timeout=30)
    msgs = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("event") == "message":
            msgs.append({"title": ev.get("title") or "", "msg": ev.get("message") or "",
                         "time": ev.get("time")})
    return msgs[:limit]

def exec_remote(cmd, wait=60, since=None):
    """发送命令并收集结果：用消息 id 基线做差集，避免时钟不同步误判。"""
    try:
        base_ids = {m.get("title", "") + "|" + (m.get("msg") or "")[:40] for m in collect_res("all", limit=500)}
    except Exception:
        base_ids = set()
    s = send_cmd(cmd)
    if not s["ok"]:
        return {"ok": False, "err": f"send failed {s}"}
    out, t0 = [], time.time()
    while time.time() - t0 < wait:
        try:
            msgs = collect_res("all", limit=500)
        except Exception:
            msgs = []
        for m in msgs:
            k = m.get("title", "") + "|" + (m.get("msg") or "")[:40]
            if k in base_ids:
                continue
            if m not in out:
                out.append(m)
        if any("rc=" in (x.get("msg") or "") for x in out):
            break
        time.sleep(3)
    return {"ok": True, "sent": cmd, "messages": out}


if __name__ == "__main__":
    print(json.dumps(list_instances(), ensure_ascii=False, indent=1))