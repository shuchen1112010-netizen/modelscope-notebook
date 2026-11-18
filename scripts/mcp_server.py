#!/usr/bin/env python3
"""[MCP] ModelScope Notebook 控制服务（stdio / JSON-RPC 2.0，纯标准库）"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import msctl

SERVER = {"name": "modelscope-notebook", "version": "1.0.0"}
PROTO = "2024-11-05"

TOOLS = [
    {"name": "ms_list_instances",
     "description": "列出魔搭 Notebook 实例（ID / 加速卡 / 状态 / 剩余额度 / IDE URL）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "ms_instance_status",
     "description": "查单个实例状态",
     "inputSchema": {"type": "object", "properties": {"instance_id": {"type": "string"}},
                     "required": ["instance_id"]}},
    {"name": "ms_start_instance",
     "description": "启动实例。服务端要求阿里云滑块验证 token，纯 API 调用会返回 403；实际启动需在浏览器过一次滑块。",
     "inputSchema": {"type": "object", "properties": {"instance_id": {"type": "string"}},
                     "required": ["instance_id"]}},
    {"name": "ms_stop_instance",
     "description": "停止实例（PUT /api/v1/notebooks/stop）",
     "inputSchema": {"type": "object", "properties": {"instance_id": {"type": "string"}},
                     "required": ["instance_id"]}},
    {"name": "ms_get_ide_url",
     "description": "取实例 IDE 直连 URL（需 Running）",
     "inputSchema": {"type": "object", "properties": {"instance_id": {"type": "string"}},
                     "required": ["instance_id"]}},
    {"name": "ms_wait_running",
     "description": "轮询等待实例进入 Running 并返回 IDE URL",
     "inputSchema": {"type": "object", "properties": {"instance_id": {"type": "string"},
                                                      "timeout": {"type": "integer"}},
                     "required": ["instance_id"]}},
    {"name": "ms_exec",
     "description": "在实例内执行 shell 命令（需实例内已部署 agent.py，走 ntfy 通道，返回 stdout/stderr）",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"},
                                                      "wait": {"type": "integer"}},
                     "required": ["command"]}},
    {"name": "ms_deploy_agent",
     "description": "返回在实例 IDE 终端里粘贴的一行 agent 部署命令（只需一次）",
     "inputSchema": {"type": "object", "properties": {}}},
]


def res(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle_call(name, a):
    if name == "ms_list_instances":
        return res(json.dumps(msctl.list_instances(), ensure_ascii=False, indent=1))
    if name == "ms_instance_status":
        i = msctl.get_instance(a["instance_id"])
        return res(json.dumps(i, ensure_ascii=False, indent=1) if i else "not found")
    if name == "ms_start_instance":
        r = msctl.start(a["instance_id"])
        if r["http"] == 200 and r.get("code") == 200:
            return res("启动成功: " + json.dumps(r, ensure_ascii=False))
        return res(json.dumps({
            "http": r["http"], "code": r.get("code"),
            "说明": "服务端拒绝纯 API 启动（10010109003 / 需阿里云滑块验证 token）。请在浏览器点一次启动并过滑块，随后用 ms_wait_running 等 URL。",
            "raw": r.get("raw")}, ensure_ascii=False, indent=1), True)
    if name == "ms_stop_instance":
        return res(json.dumps(msctl.stop(a["instance_id"]), ensure_ascii=False, indent=1))
    if name == "ms_get_ide_url":
        return res(json.dumps(msctl.ide_url(a["instance_id"]), ensure_ascii=False, indent=1))
    if name == "ms_wait_running":
        return res(json.dumps(msctl.wait_running(a["instance_id"], int(a.get("timeout", 900))),
                              ensure_ascii=False, indent=1))
    if name == "ms_exec":
        return res(json.dumps(msctl.exec_remote(a["command"], int(a.get("wait", 60))),
                              ensure_ascii=False, indent=1))
    if name == "ms_deploy_agent":
        e = msctl._env()
        cmd = ("export DSH_CMD_TOPIC=%s DSH_RES_TOPIC=%s; cd /mnt/workspace && "
               "(nohup python3 agent.py > agent.log 2>&1 &) ; sleep 1; tail -3 agent.log"
               % (e.get("DSH_CMD_TOPIC"), e.get("DSH_RES_TOPIC")))
        return res("在实例 IDE 终端粘贴这一行（只需一次）：\n\n" + cmd)
    return res("unknown tool %s" % name, True)


def send(o):
    sys.stdout.buffer.write((json.dumps(o, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def main():
    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            break
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        mid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": PROTO, "capabilities": {"tools": {}}, "serverInfo": SERVER}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            try:
                out = handle_call(params.get("name"), params.get("arguments") or {})
            except Exception as e:
                out = res("error: %s" % e, True)
            send({"jsonrpc": "2.0", "id": mid, "result": out})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            if mid is not None:
                send({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32601, "message": "method not found: %s" % method}})


if __name__ == "__main__":
    main()
