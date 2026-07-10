# LightRAG WebUI 旁路调试指南

LightRAG WebUI 是旁路调试工具，不是本项目的正式业务前端。

本项目正式链路仍然是：

1. 前端上传文件。
2. 后端保存原文和 `file_segments`。
3. 调度器调用内嵌 LightRAG SDK 索引。
4. `/retrieve` 回查应用表并过滤已删除或未完成索引的数据。

LightRAG WebUI 只用于查看 LightRAG 自己的图谱、文档状态和查询结果。

## 前端入口

管理页面有一个“旁路工具”卡片，按钮会打开：

```env
VITE_LIGHTRAG_WEBUI_URL=http://127.0.0.1:9621/webui
```

复制前端示例配置：

```powershell
Copy-Item frontend\.env.example frontend\.env.local
```

修改 `frontend/.env.local`：

```env
VITE_API_BASE=http://127.0.0.1:8000
VITE_LIGHTRAG_WEBUI_URL=http://127.0.0.1:9621/webui
```

修改后需要重启前端 dev server。

## 安装 WebUI/API Server 依赖

主依赖文件 `backend/requirements.txt` 不强制安装 WebUI extra，避免影响主服务部署。

需要 WebUI 时单独安装：

```powershell
.\.venv\Scripts\pip.exe install -r backend\requirements-lightrag-webui.txt
```

如果默认包源无法解析 `lightrag-hku[api]`，可指定镜像源：

```powershell
.\.venv\Scripts\pip.exe install -r backend\requirements-lightrag-webui.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

如果当前 Python 版本或包源无法解析 `lightrag-hku[api]`，可能会看到类似：

```text
No matching distribution found for openai<3.0.0,>=2.0.0
```

这通常是 Python 版本或包源镜像问题。可选处理方式：

- 使用 LightRAG WebUI 支持更完整的 Python 版本重新创建虚拟环境。
- 配置能解析 `openai>=2,<3` 的包源。
- 暂时不启用 WebUI；主 RAG 服务不受影响。

当前本地环境已通过清华镜像源成功安装，并验证 `lightrag-server --help` 可正常输出帮助信息。

LightRAG WebUI 默认使用 `LLM_BINDING=ollama` 和 `EMBEDDING_BINDING=ollama`。这只是 WebUI sidecar 自己的默认运行配置，不代表本项目主服务在使用 Ollama。`backend/requirements-lightrag-webui.txt` 已显式包含 `ollama` Python 包，避免 WebUI 启动时再通过 `pipmaster` 动态安装。

## 启动 LightRAG WebUI

推荐使用脚本启动：

```powershell
.\scripts\start_lightrag_webui.ps1
```

脚本默认读取：

```text
backend/.env.lightrag-webui
```

第一次使用时可从示例文件复制：

```powershell
Copy-Item backend\.env.lightrag-webui.example backend\.env.lightrag-webui
```

`backend/.env.lightrag-webui` 示例：

```env
HOST=127.0.0.1
PORT=9621
WORKING_DIR=backend/lightrag_storage
WEBUI_TITLE=RAG Platform LightRAG Debug
WEBUI_DESCRIPTION=Debug-only sidecar for local LightRAG storage
TOKEN_SECRET=local-debug-change-me
```

也可以手动从项目根目录启动，并显式指定本项目的 LightRAG 存储目录：

```powershell
$env:HOST="127.0.0.1"
$env:PORT="9621"
$env:WORKING_DIR="backend/lightrag_storage"
$env:WEBUI_TITLE="RAG Platform LightRAG Debug"
$env:WEBUI_DESCRIPTION="Debug-only sidecar for local LightRAG storage"
$env:TOKEN_SECRET="local-debug-change-me"
.\.venv\Scripts\lightrag-server.exe
```

打开：

```text
http://127.0.0.1:9621/webui
```

LightRAG Server 读取的关键环境变量：

| 变量 | 建议值 | 说明 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | 只绑定本机，避免无认证暴露 |
| `PORT` | `9621` | LightRAG WebUI/API 端口 |
| `WORKING_DIR` | `backend/lightrag_storage` | 复用本项目 LightRAG 索引目录 |
| `WEBUI_TITLE` | 任意标题 | WebUI 标题 |
| `WEBUI_DESCRIPTION` | 任意描述 | WebUI 描述 |
| `TOKEN_SECRET` | 本地随机字符串 | 避免使用默认 guest-mode JWT secret |

## 重要风险

不要在主服务正在索引时，通过 LightRAG WebUI 对同一个 `WORKING_DIR` 写入文档或删除数据。

原因：

- 本项目有自己的 `files`、`file_segments`、软删除和下载引用状态。
- LightRAG WebUI 直接操作 LightRAG 存储，不会同步应用数据库。
- 并发写同一个 `backend/lightrag_storage/` 可能导致状态文件、图谱文件或缓存互相覆盖。

推荐使用方式：

1. 主服务完成索引。
2. 不触发新的调度任务。
3. 打开 WebUI 查看图谱、文档和查询行为。
4. 如需用 WebUI 做写入实验，复制一份 `backend/lightrag_storage/` 到临时目录，并把 WebUI 的 `WORKING_DIR` 指向临时目录。

## 与本项目前端的关系

LightRAG WebUI 适合回答：

- LightRAG 内部是否生成了实体和关系？
- LightRAG 自己的查询结果是什么？
- LightRAG 存储目录是否可读？

本项目前端适合回答：

- 文件是否完成应用层索引？
- 删除后是否在业务检索中不可见？
- 检索结果是否能回到原文下载和页码/段落引用？
- `/retrieve.trace` 是否能解释本次业务检索过程？

因此，LightRAG WebUI 是调试旁路，不替代主前端。
