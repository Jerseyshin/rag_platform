# 端到端验证与运行时数据位置

本文记录 RAG 平台在本地或离线迁移环境中的启动方式、端到端验收流程，以及上传文件、LightRAG 向量库、模型缓存等运行时数据的位置。

## 1. 环境文件

后端读取的环境文件位于：

```text
backend/.env
```

可迁移模板位于：

```text
backend/.env.example
```

新环境部署时，复制模板并填写真实值：

```powershell
Copy-Item backend\.env.example backend\.env
```

需要重点修改的字段：

- `DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD`
- `INTERNAL_LLM_BASE_URL`
- `INTERNAL_LLM_API_KEY`
- `DEFAULT_LLM_MODEL`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_CACHE_DIR`
- `TOKENIZER_CACHE_DIR`
- `LIGHTRAG_WORKING_DIR`

注意：`.env` 不应提交到 Git；`.env.example` 只能保留匿名化示例。

## 2. 运行时目录

以下路径以项目根目录 `rag_platform/` 为基准。

| 数据类型 | 默认位置 | 说明 | 是否提交 Git |
|:---|:---|:---|:---|
| 后端环境变量 | `backend/.env` | 本地真实配置，包含数据库密码和 API key | 否 |
| 环境变量模板 | `backend/.env.example` | 可迁移匿名模板 | 是 |
| 上传原文文件 | `uploads/` | 用户上传的 PDF/DOCX/TXT/MD 原文件，默认在项目根目录 | 否 |
| LightRAG 向量库与图索引 | `backend/lightrag_storage/` | LightRAG 运行时生成的 chunks/entities/relationships 向量文件和 graphml | 否 |
| 离线 tokenizer/embedding 缓存 | `offline_cache/tokenizers/BAAI/bge-m3/` | 本地 `BAAI/bge-m3` tokenizer/model 缓存，体积较大 | 否 |
| 前端依赖 | `frontend/node_modules/` | npm 安装产物 | 否 |
| 前端构建产物 | `frontend/dist/` | `npm run build` 生成 | 否 |

当前 `.gitignore` 已忽略：

```text
.env
uploads/
offline_cache/
lightrag_storage/
frontend/node_modules/
frontend/dist/
```

因为后端通常从 `backend/` 目录启动，配置中的相对路径会按 `backend/` 解析：

- `UPLOAD_DIR=uploads` 实际落到项目根目录 `uploads/`
- `LIGHTRAG_WORKING_DIR=lightrag_storage` 实际落到 `backend/lightrag_storage/`
- `EMBEDDING_CACHE_DIR=../offline_cache/tokenizers` 实际指向项目根目录的 `offline_cache/tokenizers/`

## 3. LightRAG 向量库在哪里

默认配置：

```env
LIGHTRAG_WORKING_DIR=lightrag_storage
```

当从 `backend/` 目录启动 uvicorn 时，LightRAG 数据会生成在：

```text
backend/lightrag_storage/
```

常见文件包括：

```text
backend/lightrag_storage/vdb_chunks.json
backend/lightrag_storage/vdb_entities.json
backend/lightrag_storage/vdb_relationships.json
backend/lightrag_storage/graph_chunk_entity_relation.graphml
backend/lightrag_storage/kv_store_full_docs.json
backend/lightrag_storage/kv_store_text_chunks.json
backend/lightrag_storage/kv_store_llm_response_cache.json
backend/lightrag_storage/doc_status.json
```

说明：

- `vdb_chunks.json` 保存 chunk 向量索引。
- `vdb_entities.json` 保存实体向量索引。
- `vdb_relationships.json` 保存关系向量索引。
- `graph_chunk_entity_relation.graphml` 保存 LightRAG 构建的实体关系图。
- `kv_store_*` 是 LightRAG 的文档、chunk 和缓存类 KV 存储。

这些文件属于运行时索引数据，不建议提交 Git。迁移环境时可以选择：

1. 迁移 `uploads/`、数据库和 `backend/lightrag_storage/`，保留现有索引。
2. 只迁移 `uploads/` 和数据库应用表，然后删除/重建 `backend/lightrag_storage/`，重新触发索引。

MVP 更推荐第二种：保留原文和应用层 `file_segments` 作为真源，必要时重建 LightRAG 索引。

## 4. 启动前准备

### 4.1 安装后端依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### 4.2 安装前端依赖

```powershell
cd frontend
npm install
cd ..
```

### 4.3 启动 PostgreSQL + pgvector

确保数据库已启动，并且 `backend/.env` 中的数据库配置正确。

迁移说明见：

```text
docs/knowlegde/database_migration.md
```

执行迁移：

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

## 5. 启动后端

打开一个 PowerShell 窗口：

```powershell
cd C:\Users\18186\Desktop\huawei\rag_platform\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

验证：

```powershell
curl.exe http://127.0.0.1:8000/health
```

预期返回：

```json
{"status":"ok","app":"RAG-File-Service","env":"development"}
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

## 6. 启动前端

另开一个 PowerShell 窗口：

```powershell
cd C:\Users\18186\Desktop\huawei\rag_platform\frontend
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5173/
```

如果后端不是 `http://127.0.0.1:8000`，可以通过前端环境变量覆盖：

```env
VITE_API_BASE=http://your-backend-host:8000
```

## 7. 端到端验收流程

建议先使用一个很小的 `.txt` 或 `.md` 文件。

1. 打开前端 `http://127.0.0.1:5173/`。
2. 进入“工作台”。
3. 上传测试文件。
4. 文件列表应出现新文件，状态为 `pending`。
5. 进入“管理”页。
6. 点击“立即执行”，触发 `/admin/scheduler/trigger`。
7. 回到“工作台”刷新文件列表。
8. 等文件状态变为 `completed`。
9. 输入与文件内容相关的问题，点击检索。
10. 检索结果应展示：
    - 片段内容
    - 分数
    - 文件名
    - 页码或段落位置
    - 下载入口
11. 点击下载入口，应能下载原始文件。
12. 点击删除文件。
13. 再次检索，已删除文件的片段应立即不可见。
14. 再到“管理”页点击“立即执行”，后台会清理 LightRAG 索引。
15. 查看管理页任务日志，应能看到调度记录和处理结果。

## 8. API 方式验收

也可以直接使用 Swagger：

```text
http://127.0.0.1:8000/docs
```

推荐接口顺序：

```text
POST   /upload
GET    /files
POST   /admin/scheduler/trigger
GET    /files/{file_id}
POST   /retrieve
DELETE /files/{file_id}
POST   /admin/scheduler/trigger
GET    /admin/scheduler/logs
```

关键期望：

- 上传后文件状态为 `pending`。
- 调度完成后文件状态为 `completed`。
- 检索接口只返回 chunks，不生成答案。
- 删除后 download 和 retrieve 都不应继续暴露该文件。
- 删除清理调度后，文件最终状态进入 `deleted`。

## 9. 常用检查命令

后端编译：

```powershell
cd backend
..\.venv\Scripts\python.exe -m compileall app
```

后端轻量测试：

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests
```

前端构建：

```powershell
cd frontend
npm run build
```

检查后端健康状态：

```powershell
curl.exe http://127.0.0.1:8000/health
```

检查管理状态：

```powershell
curl.exe http://127.0.0.1:8000/admin/status
```

## 10. 离线迁移建议

迁移到另一台机器时，建议携带：

- 源码仓库。
- `backend/.env.example`，到目标机器后复制为 `backend/.env` 并填写真实值。
- `uploads/`，用于保留用户上传的原文文件。
- `offline_cache/tokenizers/BAAI/bge-m3/`，用于本地 embedding/tokenizer 离线加载。
- PostgreSQL 数据库备份，或重新执行 Alembic 迁移后重新上传/索引。
- 如需保留已有索引，可额外迁移 `backend/lightrag_storage/`。

不建议携带：

- `backend/.env` 中的真实密钥。
- `frontend/node_modules/`。
- `frontend/dist/`，除非目标环境只部署静态构建产物。
- `.venv/`，目标机器应重新创建虚拟环境并安装依赖。

更完整的内网迁移、embedding 模型替换、索引重建和路径修复说明见：

```text
docs/knowlegde/intranet_migration_guide.md
```

## 11. 排障提示

- 访问不了 `/docs`：检查 uvicorn 是否启动在 `127.0.0.1:8000`。
- 前端请求失败：检查 `VITE_API_BASE` 或默认后端地址是否正确。
- 上传后一直 `pending`：进入管理页点击“立即执行”，或检查 scheduler 是否启用。
- 索引失败：查看文件详情里的 `error_code/error_msg`，以及 `/admin/scheduler/logs`。
- 本地 embedding 加载失败：确认 `offline_cache/tokenizers/BAAI/bge-m3/` 存在，并检查 `EMBEDDING_CACHE_DIR`、`TOKENIZER_CACHE_DIR`。
- LLM 调用失败：检查 `INTERNAL_LLM_BASE_URL`、`INTERNAL_LLM_API_KEY`、`DEFAULT_LLM_MODEL`。
- 删除后仍可下载：应确认后端是最新代码；当前设计中 `deleting/deleted` 文件都不应允许下载。
