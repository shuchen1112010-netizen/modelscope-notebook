#!/usr/bin/env python3
"""ModelScope Notebook 控制核心库。

数据目录（cookie.txt / .env）优先取环境变量 MSCTL_HOME，
否则取本文件所在目录。
"""
import json, os, time
import requests

BASE = "https://modelscope.cn/api/v1"
HERE = os.environ.get("MSCTL_HOME") or os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(HERE, "cookie.txt")
ENV_FILE = os.path.join(HERE, ".env")
NTFY = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")


def _headers():
    jar = open(COOKIE_FILE, encoding="utf-8").read().strip()
    return {"Cookie": jar, "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://modelscope.cn/my/mynotebook",
            "Origin": "https://modelscope.cn"}


def _j(r):
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text[:500], "_status": r.status_code}


def list_instances(channel="dsw"):
    r = requests.get(f"{BASE}/notebooks/all", headers=_headers(),
                     params={"PageNumber": 1, "PageSize": 20, "Channel": channel},
                     timeout=40)
    j = _j(r)
    rows = (((j.get("Data") or {}).get("Notebooks") or {}).get("NotebookList") or [])
    out = [{"id": x.get("InstanceId"), "accel": x.get("AcceleratorType"),
            "status": x.get("Status"), "gpu": x.get("GpuMemory"),
            "cpu": x.get("Cpu"), "mem": x.get("Memory"),
            "remain_sec": x.get("RemainingQuota"), "url": x.get("Url"),
            "image": x.get("Image")} for x in rows]
    return {"ok": r.status_code == 200, "http": r.status_code, "instances": out}


def get_instance(inst_id):
    for i in list_instances()["instances"]:
        if i["id"] == inst_id:
            return i
    return None


def start(inst_id):
    """纯 API 启动：服务端要求 CaptchaVerify（阿里云滑块），通常 403。"""
    r = requests.put(f"{BASE}/notebooks/paid/start", headers=_headers(),
                     json={"InstanceId": inst_id, "Channel": "dsw"}, timeout=60)
    j = _j(r)
    return {"http": r.status_code, "code": j.get("Code"),
            "message": j.get("Message"), "raw": j}


def stop(inst_id):
    r = requests.put(f"{BASE}/notebooks/stop", headers=_headers(),
                     json={"InstanceId": inst_id}, timeout=60)
    j = _j(r)
    return {"http": r.status_code, "code": j.get("Code"),
            "message": j.get("Message"), "raw": j}


def ide_url(inst_id):
    i = get_instance(inst_id)
    if not i:
        return {"ok": False, "err": "instance not found"}
    if i.get("url"):
        return {"ok": True, "url": i["url"], "status": i["status"]}
    return {"ok": False, "status": i["status"],
            "err": f"status={i['status']}，url 尚未生成（需 Running）"}


def wait_running(inst_id, timeout=900, interval=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        i = get_instance(inst_id)
        if i and str(i["status"]).lower() == "running" and i.get("url"):
            return {"ok": True, "instance": i, "url": i["url"],
                    "waited": round(time.time() - t0)}
        time.sleep(interval)
    return {"ok": False, "instance": get_instance(inst_id),
            "err": f"timeout {timeout}s"}


# ---------------- ntfy 命令通道 ----------------
def _env():
    d = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                d[k] = v
    d.setdefault("NTFY_BASE", NTFY)
    return d


def send_cmd(cmd, topic=None):
    e = _env()
    t = topic or e.get("DSH_CMD_TOPIC")
    r = requests.post(f"{e.get('NTFY_BASE', NTFY)}/{t}", data=cmd.encode("utf-8"),
                      timeout=30)
    return {"ok": r.status_code == 200, "http": r.status_code}


def collect_res(since, topic=None, limit=50):
    e = _env()
    t = topic or e.get("DSH_RES_TOPIC")
    r = requests.get(f"{e.get('NTFY_BASE', NTFY)}/{t}/json",
                     params={"poll": 1, "since": since}, timeout=30)
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
    since = int(time.time()) if since is None else since
    s = send_cmd(cmd)
    if not s["ok"]:
        return {"ok": False, "err": f"send failed {s}"}
    out, t0 = [], time.time()
    while time.time() - t0 < wait:
        for m in collect_res(since):
            if m not in out:
                out.append(m)
        if any("rc=" in (m["msg"] or "") for m in out):
            break
        time.sleep(3)
    return {"ok": True, "sent": cmd, "messages": out}


if __name__ == "__main__":
    print(json.dumps(list_instances(), ensure_ascii=False, indent=1))
