#!/usr/bin/env python3
# 本机控制端：DSH_CMD_TOPIC 发命令，DSH_RES_TOPIC 收结果。
# 用法：python ctl.py   然后逐行输入命令；:watch 持续收；:raw <text> 原样发；exit 退出
import os, sys, json, time, urllib.request, urllib.parse

BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
CMD  = os.environ.get("DSH_CMD_TOPIC") or sys.exit("need DSH_CMD_TOPIC")
RES  = os.environ.get("DSH_RES_TOPIC") or sys.exit("need DSH_RES_TOPIC")

def send(text):
    req = urllib.request.Request(BASE + "/" + CMD, data=text.encode("utf-8"),
                                 method="POST", headers={"User-Agent": "dsh-ctl"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status

def poll(since):
    url = f"{BASE}/{RES}/json?poll=1&since={since}"
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-ctl"})
    with urllib.request.urlopen(req, timeout=25) as r:
        txt = r.read().decode("utf-8", "replace")
    out = []
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("event") == "message":
            out.append((ev.get("title") or "", ev.get("message") or ""))
    return out

def main():
    since = int(time.time())
    print(f"[ctl] cmd={CMD}  res={RES}")
    print("输入命令回车即发；:watch 持续监听 60s；exit 退出")
    while True:
        try:
            line = input("dsh> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("exit", "quit", ":q"):
            break
        if line == ":watch":
            t_end = time.time() + 60
            while time.time() < t_end:
                try:
                    for title, msg in poll(since):
                        print(f"[{title}] {msg}")
                    since = int(time.time())
                except Exception as e:
                    print("[poll err]", e)
                time.sleep(2)
            continue
        if line.startswith(":raw "):
            print("[sent raw]", send(line[5:]))
            continue
        n = len(line)
        print(f"[sent {n}B]", send(line))
        # 等 8 秒收首包
        t_end = time.time() + 8
        got = False
        while time.time() < t_end:
            try:
                for title, msg in poll(since):
                    print(f"[{title}] {msg}")
                    got = True
                since = int(time.time())
            except Exception as e:
                print("[poll err]", e)
            if not got:
                time.sleep(2)
            else:
                break
        if not got:
            print("（暂无回包，可再输 :watch 继续收）")

if __name__ == "__main__":
    main()