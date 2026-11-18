# modelscope-notebook

Control **ModelScope (魔搭) Notebook / DSW instances** from a CLI or an MCP client — no browser automation, no official API needed.

用命令行或 MCP 客户端控制魔搭 Notebook 实例：查实例、看剩余额度、启停、取 IDE 直连地址、在实例里跑 shell。

> 官方 ModelScope MCP Server 只覆盖模型/数据集/创空间检索，**没有** Notebook 能力。这个项目补的就是这块。

## 能干什么

| 能力 | 说明 |
|---|---|
| 列出实例 | ID / 加速卡 / 状态 / 剩余额度（秒）/ IDE URL |
| 取 IDE URL | 实例 Running 后直接从 `Url` 字段拿 |
| 在实例里跑命令 | 通过 `ntfy.sh`（HTTPS 443）双向通道，不需要公网入站、不需要端口映射 |
| 启停 | 见下方限制 |
| MCP 接入 | 8 个工具，stdio 传输，纯标准库实现 |

## 关键限制（先看这个）

1. **认证是 Cookie，不是 AK。** 实例在魔搭平台账户下，不在你的阿里云账号里，`aliyun` CLI 管不了。
2. **启动必须过一次阿里云滑块。** 服务端强校验 `CaptchaVerify`（阿里云验证码 SDK 现签），纯 API 启动一律 `403 / 10010109003`。这是唯一的人工动作，绕不过。
3. **实例内自建服务的端口没有公网入站。** 想暴露服务只能自己做反向隧道；产物走 IDE 文件树下载或小文件经 ntfy 回传。

## 安装

```bash
git clone https://github.com/<you>/modelscope-notebook.git
cd modelscope-notebook
pip install requests
```

## 用法

### 1) 抓 cookie（一次）

```bash
# 会弹出 Chrome，扫码登录魔搭
python scripts/login.py
# 产物：cookie.txt（含 HttpOnly cookie）
```

也可以手动：Chrome F12 → Network → 任一 modelscope 请求 → 复制整行 `cookie:`，存成 `cookie.txt`。

### 2) 查实例

```bash
export MSCTL_HOME=$(pwd)     # 数据目录（cookie.txt / .env 所在）
python scripts/msctl.py
```

```
AMD  dsw-xxxxxxxx   Starting  remain=330760s
GPU  dsw-yyyyyyyy   Stopped   remain=126414s
```

### 3) 启动（唯一需要人动手的一步）

```bash
python scripts/start_watch.py
# 浏览器自动打开并点「启动」，滑块弹出后人工拖一下
# 脚本自动轮询，Running 后把 URL 写进 watch_state.json
```

### 4) 实例内执行命令

```bash
# 在 IDE 终端粘一次，把 agent 落到 /mnt/workspace
bash scripts/deploy_agent.sh    # 打印一行 base64 命令，粘贴执行
bash scripts/run_agent.sh       # 拉起 agent（后台常驻）

# 之后本机随便发命令
python -c "import sys;sys.path.insert(0,'scripts');import msctl;
print(msctl.exec_remote('ls -lh /mnt/workspace', wait=60))"
```

## MCP 接入

```json
{
  "mcpServers": {
    "modelscope-notebook": {
      "command": "python",
      "args": ["/abs/path/scripts/mcp_server.py"],
      "env": { "MSCTL_HOME": "/abs/path" }
    }
  }
}
```

工具清单：

```
ms_list_instances   ms_instance_status  ms_start_instance  ms_stop_instance
ms_get_ide_url      ms_wait_running     ms_exec            ms_deploy_agent
```

## 实测接口

| 接口 | 方法 | 结果 |
|---|---|---|
| `/api/v1/notebooks/all?Channel=dsw` | GET | 200，实例列表 + 剩余额度 |
| `/api/v1/notebooks/specs?Channel=dsw` | GET | 200，规格 |
| `/api/v1/notebooks` | POST | 启动/创建，**需 `CaptchaVerify`** |
| `/api/v1/notebooks/stop` | PUT | 400，参数格式未定（缺真实抓包） |
| `/api/v1/notebooks/paid/start` | PUT | 403，付费通道，需阿里云重新授权 |

抓到的真实启动请求（供排查）：

```http
POST /api/v1/notebooks
x-csrf-token: <page-issued>
Content-Type: application/json

{"Channel":"dsw","AcceleratorType":"AMD","Image":"<image>",
 "CaptchaVerify":"{\"sceneId\":\"..\",\"certifyId\":\"..\",\"deviceToken\":\"..\"}"}
```

## 安全

- `cookie.txt` / `.env` 已在 `.gitignore` 中，**不会**被提交。
- cookie 等于账号登录态，泄露等于账号被接管，别外传。
- 通道 topic 名建议自己换一组随机值。

## License

MIT
