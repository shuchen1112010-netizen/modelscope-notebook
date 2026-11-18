import json, os, time, sys
import requests
from playwright.sync_api import sync_playwright

PROF = r"D:\ai视频制作\out\pwprofile"
OUT = r"D:\msctl"
COOKIE = os.path.join(OUT, "cookie.txt")
ID = "dsw-jrcxroxx5b95ff6w48"
STATE = os.path.join(OUT, "watch_state.json")
NET = os.path.join(OUT, "netcap.jsonl")

def wstate(**kw):
    cur = {}
    try:
        if os.path.exists(STATE):
            cur = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        pass
    cur.update(kw)
    cur["ts"] = time.strftime("%H:%M:%S")
    json.dump(cur, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def poll_instance():
    try:
        jar = open(COOKIE, encoding="utf-8").read().strip()
        H = {"Cookie": jar, "User-Agent": "Mozilla/5.0",
             "Referer": "https://modelscope.cn/my/mynotebook"}
        r = requests.get("https://modelscope.cn/api/v1/notebooks/all",
                         headers=H, params={"PageNumber": 1, "PageSize": 20, "Channel": "dsw"},
                         timeout=30)
        rows = (((r.json().get("Data") or {}).get("Notebooks") or {}).get("NotebookList") or [])
        for x in rows:
            if x.get("InstanceId") == ID:
                return {"status": x.get("Status"), "url": x.get("Url"),
                        "remain_sec": x.get("RemainingQuota")}
    except Exception as e:
        return {"err": str(e)[:120]}
    return {}

seen = set()

def on_req(r):
    u = r.url
    if "/api/" not in u:
        return
    if not any(k in u for k in ("notebook", "captcha", "dsw", "pay", "verify")):
        return
    key = r.method + u + (r.post_data or "")
    if key in seen:
        return
    seen.add(key)
    rec = {"t": time.strftime("%H:%M:%S"), "m": r.method, "u": u,
           "body": (r.post_data or "")[:1500],
           "headers": {k: v for k, v in r.headers.items()
                       if k.lower() in ("content-type", "x-csrf-token", "x-requested-with")}}
    with open(NET, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if any(k in u for k in ("start", "/notebooks")) and r.method in ("PUT", "POST"):
        wstate(last_start_req=rec)

wstate(status="starting", msg="launch browser")
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROF, headless=False, channel="chrome",
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        no_viewport=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("request", on_req)
    try:
        page.goto("https://modelscope.cn/my/mynotebook", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        wstate(status="nav_warn", msg=str(e)[:150])
    page.wait_for_timeout(5000)
    # 关掉干扰弹层
    for _ in range(3):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
    # 自动点 AMD 行「启动」，把滑块弹出来给用户拖
    clicked = False
    try:
        sel = 'button[data-autolog*="AMD"]'
        if page.locator(sel).count():
            page.eval_on_selector(sel, "el => el.click()")
            clicked = True
    except Exception as e:
        wstate(click_err=str(e)[:150])
    wstate(status="waiting_slider", clicked=clicked,
           msg="已点启动，等你在窗口里拖滑块")

    last = 0
    for i in range(1200):   # ~100 分钟
        try:
            page.wait_for_timeout(5000)
        except Exception:
            break
        if i - last >= 2:
            last = i
            st = poll_instance()
            wstate(instance=st)
            if st.get("status") in ("Running", "running"):
                wstate(status="running", url=st.get("url"))
                if st.get("url"):
                    wstate(status="ready")
    try:
        ctx.close()
    except Exception:
        pass
