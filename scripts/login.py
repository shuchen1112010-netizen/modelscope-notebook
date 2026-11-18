import json, os, sys, time, urllib.request
from playwright.sync_api import sync_playwright

PROF = r"D:\ai视频制作\out\pwprofile"
OUT  = r"D:\ai视频制作\out\remote"
STATE= os.path.join(OUT, "login_state.json")

def wstate(**kw):
    try:
        cur = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    except Exception:
        cur = {}
    cur.update(kw)
    cur["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(cur, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

wstate(status="starting", msg="launching chrome")

with sync_playwright() as p:
    ctx = None
    for kw in ({"channel": "chrome"}, {}):
        try:
            ctx = p.chromium.launch_persistent_context(PROF, headless=False,
                    args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
                    no_viewport=True, **kw)
            wstate(status="launched", msg=f"browser={kw.get('channel','bundled')}")
            break
        except Exception as e:
            wstate(status="launch_retry", msg=str(e)[:300])
    if ctx is None:
        wstate(status="failed", msg="no browser")
        sys.exit(1)

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto("https://modelscope.cn/my/mynotebook", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        wstate(status="nav_warn", msg=str(e)[:200])

    logged = False
    for i in range(180):   # 6 分钟
        try:
            txt = page.inner_text("body")[:4000]
        except Exception:
            txt = ""
        if ("个人主页" in txt) or ("我的Notebook" in txt and "登录" not in txt[:400]):
            logged = True
            break
        if i % 10 == 0:
            wstate(status="waiting_login", msg=f"round {i}")
        time.sleep(2)

    cookies = ctx.cookies()
    jar = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    open(os.path.join(OUT, "cookie.txt"), "w", encoding="utf-8").write(jar)
    json.dump(cookies, open(os.path.join(OUT, "cookies.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 用页面上下文直接调 API 作为第一重验证
    api_res = {}
    try:
        api_res = page.evaluate("""async () => {
            const r = await fetch('/api/v1/notebooks/all?PageNumber=1&PageSize=10&Channel=dsw', {credentials:'include'});
            return {status: r.status, body: (await r.text()).slice(0, 2000)};
        }""")
    except Exception as e:
        api_res = {"err": str(e)[:300]}
    json.dump(api_res, open(os.path.join(OUT, "api_probe.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    wstate(status="done", logged=logged, cookie_len=len(jar), n_cookies=len(cookies), api=api_res.get("status"))
    ctx.close()