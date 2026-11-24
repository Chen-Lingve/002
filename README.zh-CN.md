# 射频连接器知识库工具

[下载源码包](rfkb-tools-source-verified.zip)或[浏览源码目录](rfkb-tools/)。其中包含 `rfkb-review` Skill、`rf_knowledge` MCP 服务、本地知识工作台、依赖锁文件及合成测试。不包含正式知识条目、工程图纸、项目配置或凭据。

源码包 SHA-256：`768a5299569780dd882a95d5727c18aab1305d075d1448db829101c3d9e62b00`。

## 安装与演示

在 Windows 安装 Python 3.13。若使用 ZIP，在解压目录打开 PowerShell；若克隆仓库，在 `rfkb-tools/` 目录打开 PowerShell。运行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\python.exe -m unittest discover -q
.\.venv\Scripts\python.exe -m rfkb demo --data ./demo-data
.\.venv\Scripts\python.exe -m rfkb serve --data ./demo-data --port 8766
```

最后一条命令可选。运行后打开 `http://127.0.0.1:8766`；服务只监听本机。演示数据是合成数据，不用于工程判断。

## 接入 Codex

1. 将源码包内的 `.agents/skills/rfkb-review/` 放在使用该 Skill 的项目下同名目录。若直接把解压目录作为项目打开，Skill 已在对应位置。
2. 在项目的 `.codex/config.toml` 添加以下 stdio 服务。把两个路径换成本机绝对路径；可先用合成演示库测试，不必启动网页服务。

```toml
[mcp_servers.rf_knowledge]
command = 'C:\path\to\rfkb-tools\.venv\Scripts\python.exe'
args = ["-m", "rfkb", "mcp", "--data", 'C:\path\to\rfkb-tools\demo-data']
```

3. 在项目新会话中调用 `kb_status` 确认数据范围，再用 `kb_search` 查找记录。服务还提供 `kb_get_record`、`kb_get_context`、`kb_evaluate` 和 `kb_get_run`。引用知识时固定记录 ID 和版本。

MCP 不读取草稿、不修改或发布知识条目，也不会修改 CAD 或启动电磁仿真。尺寸或公差检查只适用于明确输入，不替代制造可行性、射频性能或标准符合性验证。

源码入口是 [`rfkb-review` Skill](rfkb-tools/.agents/skills/rfkb-review/SKILL.md) 和 [`rf_knowledge` MCP](rfkb-tools/rfkb/mcp_server.py)。第三方图标的许可证随包保存在 [`rfkb/static/lucide-LICENSE.txt`](rfkb-tools/rfkb/static/lucide-LICENSE.txt)。
