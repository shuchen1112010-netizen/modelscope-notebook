---
name: modelscope-notebook
description: Control ModelScope (魔搭) Notebook / DSW instances from CLI or MCP without a browser — list instances, read remaining quota, start/stop, get the IDE URL, and execute shell commands inside a running instance over an HTTPS pub-sub channel. Use when the user asks to control 魔搭 / ModelScope Notebook, DSW instances, GPU quota, start or stop a cloud instance, or run commands in a ModelScope IDE terminal. 关键词：魔搭实例、ModelScope Notebook、DSW、启动实例、剩余额度、云端跑命令、msctl。
---

# modelscope-notebook

把魔搭（ModelScope）Notebook 实例变成可编程资源：查询、启停、拿 IDE URL、在实例内跑 shell。

不依赖浏览器，不依赖官方 MCP（官方 MCP 只覆盖模型/数据集/创空间的检索，**没有** notebook 能力）。

## 先搞清楚三件事

1. **认证是 Cookie，不是 AK。** 魔搭实例在你阿里云账号之外，阿里云 CLI 管不了。抓一份 `cookie.txt` 即可调全部 REST 接口。
2. **启动必须过一次阿里云滑块。** 服务端强校验 `CaptchaVerify` 字段（由阿里云验证码 SDK 现签），纯 API 启动返回 `403 / 10010109003`。这是唯一的人工动作。
3. **实例内的命令走 ntfy.sh**（HTTPS 443），不需要公网入站、不需要端口映射。

## 准备

```bash
# 1) 抓 cookie（会弹出 Chrome，扫码登录一次）
python scripts/login.py
#    产物：$MSCTL_HOME/cookie.txt（含 HttpOnly）

# 2) 设置数据目录（默认脚本同目录）
export MSCTL_HOME=/path/to/workdir
```

## 命令行

```bash
python scripts/msctl.py                     # 列出实例（默认动作）
python -c "import sys;sys.path.insert(0,'scripts');import msctl;
print(msctl.get_instance('dsw-xxxx'))"      # 单实例
python -c "import sys;sys.path.insert(0,'scripts');import msctl;
print(msctl.ide_url('dsw-xxxx'))"           # 取 IDE URL（需 Running）
python scripts/ctl.py                       # 交互式发命令（需实例内已跑 agent）
```

## 启动（含唯一人工步骤）

1. `python scripts/start_watch.py` —— 打开浏览器并自动点「启动」，弹出滑块
2. 人在窗口里拖一次滑块
3. 脚本自动轮询，实例 Running 后写 `watch_state.json`（含 `url`）
4. `python scripts/msctl.py` 复查，`url` 字段即为 IDE 直连地址

抓包已确认的真实请求（供排查）：

```
POST /api/v1/notebooks
x-csrf-token: <页面签发>
{"Channel":"dsw","AcceleratorType":"AMD","Image":"<镜像>","CaptchaVerify":"{\"sceneId\":..,\"certifyId\":..,\"deviceToken\":..}"}
```

## 实例内执行命令

```bash
# 1) 把 agent 推进实例（IDE 终端粘一次；deploy_agent.sh 是一行 base64）
bash scripts/deploy_agent.sh   # 拷贝其内容到 IDE 终端执行

# 2) 拉起 agent（后台常驻，ntfy 通道）
bash scripts/run_agent.sh

# 3) 之后本机任意发命令
python -c "import sys;sys.path.insert(0,'scripts');import msctl;
print(msctl.exec_remote('nvidia-smi; rocm-smi', wait=60))"
```

`agent.py` 会把 stdout/stderr 分块回传到 `DSH_RES_TOPIC`。

## MCP 接入

任意 MCP 客户端（Cursor / Claude Desktop / DSH）：

```json
{
  "mcpServers": {
    "modelscope-notebook": {
      "command": "python",
      "args": ["/abs/path/scripts/mcp_server.py"],
      "env": { "MSCTL_HOME": "/abs/path/workdir" }
    }
  }
}
```

工具：`ms_list_instances` / `ms_instance_status` / `ms_start_instance` / `ms_stop_instance` / `ms_get_ide_url` / `ms_wait_running` / `ms_exec` / `ms_deploy_agent`

## 已验证的接口

| 接口 | 方法 | 结果 |
|---|---|---|
| `/api/v1/notebooks/all?Channel=dsw` | GET | 200，实例列表 + 剩余额度（秒） |
| `/api/v1/notebooks/specs?Channel=dsw` | GET | 200，规格 |
| `/api/v1/notebooks` | POST | 启动/创建，**需 CaptchaVerify** |
| `/api/v1/notebooks/stop` | PUT | 400，参数格式待补（缺真实抓包） |
| `/api/v1/notebooks/paid/start` | PUT | 403，付费实例通道，需阿里云重新授权 |

## 坑

- `x-csrf-token` 和 Cookie 必须同时带，缺一报错。
- 实例空闲 1 小时自动关；`agent.py` 常驻可保活。
- 单次运行上限约 8 小时，额度按秒计（`RemainingQuota`）。
- 产物出云端：实例里的服务端口无公网入站，只能写文件后走 IDE 文件树下载，或分块经 ntfy 回传（小文件）。
