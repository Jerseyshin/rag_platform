# 内网迁移指南

本文面向把当前 RAG 平台从开发机迁移到内网服务器、离线机器或另一套环境的场景。重点说明要迁移哪些数据、哪些运行时目录可以重建，以及 embedding 模型如何替换。

## 1. 迁移目标

当前系统是 retrieve-only RAG 服务，核心真源有三类：

- 原始文件：`uploads/`
- 应用数据库：PostgreSQL 中的 `files`、`file_segments`、`system_configs`、`scheduler_logs`
- LightRAG 运行时索引：`backend/lightrag_storage/`

其中 `uploads/` 和应用数据库更重要；`backend/lightrag_storage/` 可以迁移，也可以在目标环境重新生成。

## 2. 迁移包清单

建议准备以下内容：

| 类型 | 路径或内容 | 是否必须 | 说明 |
|:---|:---|:---|:---|
| 源码 | 整个 Git 仓库 | 是 | 不包含 ignored 目录 |
| 环境模板 | `backend/.env.example` | 是 | 到目标环境复制为 `backend/.env` |
| 原始文件 | `uploads/` | 生产数据必须 | 用户上传的原文文件 |
| 数据库备份 | PostgreSQL dump | 生产数据必须 | 包含应用表和 Alembic 版本 |
| 本地 embedding/tokenizer 缓存 | `offline_cache/tokenizers/BAAI/bge-m3/` | local embedding 模式必须 | 当前 MVP 默认本地模型 |
| LightRAG 索引 | `backend/lightrag_storage/` | 可选 | 保留现有索引时迁移；换 embedding 时不建议复用 |
| 前端构建产物 | `frontend/dist/` | 可选 | 只部署静态页面时需要 |

不建议迁移：

- `.venv/`
- `frontend/node_modules/`
- `backend/.env` 里的真实密钥
- `__pycache__/`
- `.pytest_cache/`

## 3. 目标环境初始化

### 3.1 创建 Python 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Linux 示例：

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r backend/requirements.txt
```

### 3.2 创建前端依赖或构建产物

开发或联调模式：

```powershell
cd frontend
npm install
npm run dev
```

生产静态构建：

```powershell
cd frontend
npm install
npm run build
```

### 3.3 配置 `.env`

复制模板：

```powershell
Copy-Item backend\.env.example backend\.env
```

填写目标环境真实配置：

- 数据库：`DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`
- LLM 网关：`INTERNAL_LLM_BASE_URL`、`INTERNAL_LLM_API_KEY`、`DEFAULT_LLM_MODEL`
- Embedding：`EMBEDDING_PROVIDER`、`DEFAULT_EMBEDDING_MODEL`、`VECTOR_DIMENSION`
- 缓存路径：`EMBEDDING_CACHE_DIR`、`TOKENIZER_CACHE_DIR`
- LightRAG 存储：`LIGHTRAG_WORKING_DIR`

## 4. 目录落点规则

后端通常从 `backend/` 目录启动：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

相对路径解析规则：

| 配置 | 默认值 | 实际位置 |
|:---|:---|:---|
| `UPLOAD_DIR` | `uploads` | 项目根目录 `uploads/` |
| `LIGHTRAG_WORKING_DIR` | `lightrag_storage` | `backend/lightrag_storage/` |
| `EMBEDDING_CACHE_DIR` | `../offline_cache/tokenizers` | 项目根目录 `offline_cache/tokenizers/` |
| `TOKENIZER_CACHE_DIR` | `../offline_cache/tokenizers` | 项目根目录 `offline_cache/tokenizers/` |

`UPLOAD_DIR` 是特殊规则：代码会把相对路径解析到项目根目录。LightRAG 和缓存目录按后端进程工作目录解析。

LightRAG 检索阶段 token 截断参数：

```env
LIGHTRAG_QUERY_CHUNK_TOP_K=10
LIGHTRAG_QUERY_MAX_ENTITY_TOKENS=6000
LIGHTRAG_QUERY_MAX_RELATION_TOKENS=8000
LIGHTRAG_QUERY_MAX_TOTAL_TOKENS=24000
```

这些参数只影响后续 `/retrieve` 请求，不影响已有索引，不需要重新索引。调大后会保留更多实体、关系和 chunks，但会增加检索延迟、响应体大小和前端图谱复杂度。

## 5. Embedding 模型替换

### 5.1 当前 MVP 默认

```env
EMBEDDING_PROVIDER=local
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
DEFAULT_TOKENIZER_MODEL=BAAI/bge-m3
VECTOR_DIMENSION=1024
EMBEDDING_CACHE_DIR=../offline_cache/tokenizers
TOKENIZER_CACHE_DIR=../offline_cache/tokenizers
EMBEDDING_LOCAL_FILES_ONLY=true
TOKENIZER_LOCAL_FILES_ONLY=true
```

当前本地缓存目录：

```text
offline_cache/tokenizers/BAAI/bge-m3/
```

### 5.2 切换到内网 embedding API

如果内网已有 embedding 网关，推荐使用 API 模式：

```env
EMBEDDING_PROVIDER=api
DEFAULT_EMBEDDING_MODEL=bge-m3
VECTOR_DIMENSION=1024
INTERNAL_EMBEDDING_BASE_URL=https://embedding-gateway.internal.example.com/v1
INTERNAL_EMBEDDING_API_KEY=replace-with-internal-token
INTERNAL_EMBEDDING_TIMEOUT=60
```

后端会请求：

```text
POST {INTERNAL_EMBEDDING_BASE_URL}/embeddings
```

请求体形态：

```json
{
  "model": "bge-m3",
  "input": ["文本1", "文本2"]
}
```

认证方式：

```http
Authorization: Bearer <INTERNAL_EMBEDDING_API_KEY>
```

如果你的内网 embedding API 不是 OpenAI-compatible `/embeddings` 协议，需要改造：

```text
backend/app/infrastructure/embedding_client.py
```

重点保持对上层的契约不变：

```python
embed(texts: Sequence[str]) -> np.ndarray
```

### 5.3 切换到另一个本地 embedding 模型

例如换成内网缓存的 `BAAI/bge-large-zh-v1.5`，需要：

1. 把模型文件放到缓存目录。

```text
offline_cache/tokenizers/BAAI/bge-large-zh-v1.5/
```

2. 修改 `.env`：

```env
EMBEDDING_PROVIDER=local
DEFAULT_EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
DEFAULT_TOKENIZER_MODEL=BAAI/bge-large-zh-v1.5
VECTOR_DIMENSION=1024
EMBEDDING_CACHE_DIR=../offline_cache/tokenizers
TOKENIZER_CACHE_DIR=../offline_cache/tokenizers
EMBEDDING_LOCAL_FILES_ONLY=true
TOKENIZER_LOCAL_FILES_ONLY=true
```

3. 确认模型维度。

不同 embedding 模型的向量维度可能不同。`VECTOR_DIMENSION` 必须和实际输出维度一致，否则 LightRAG 向量库会初始化失败或查询结果异常。

常见例子：

| 模型 | 常见维度 | 备注 |
|:---|:---|:---|
| `BAAI/bge-m3` | 1024 | 当前 MVP 默认 |
| `BAAI/bge-large-zh-v1.5` | 1024 | 中文常用 |
| `BAAI/bge-base-zh-v1.5` | 768 | 维度不同，必须重建索引 |
| `text-embedding-3-small` | 1536 | OpenAI 常见维度 |
| `text-embedding-3-large` | 3072 | OpenAI 常见维度 |

实际维度以目标模型或内网网关返回为准。

## 6. 替换 embedding 后是否要重建索引

结论：只要 embedding 模型、embedding 维度、归一化策略或 tokenizer/chunk 策略发生变化，就应该重建 LightRAG 索引。

必须重建的情况：

- `DEFAULT_EMBEDDING_MODEL` 改了。
- `VECTOR_DIMENSION` 改了。
- `EMBEDDING_NORMALIZE` 改了。
- 从 `local` 切到 `api`，且 API 后面的模型不是同一个。
- `DEFAULT_TOKENIZER_MODEL` 改了。
- `rag.chunk_size` 或 `rag.chunk_overlap` 改了，并希望旧文件也按新策略生效。

可以不重建的情况：

- 只改 LLM 网关地址或 LLM API key。
- 只改 `DEFAULT_TOP_K`、`DEFAULT_THRESHOLD`、`DEFAULT_SEARCH_MODE`。
- 只改 scheduler 间隔、batch size、retry 次数。

## 7. 重建索引方案

### 7.1 空环境迁移

如果目标环境不需要保留旧索引：

1. 不迁移 `backend/lightrag_storage/`。
2. 执行 Alembic 迁移创建应用表。
3. 通过前端或 API 重新上传文件。
4. 触发调度器重新索引。

这是最干净的方式。

### 7.2 保留原文和数据库，重建 LightRAG

适用于已经迁移了 `uploads/` 和数据库，但 embedding/tokenizer 变了。

操作前先备份数据库。

1. 停止后端服务。
2. 删除或挪走旧的 LightRAG 工作目录：

```text
backend/lightrag_storage/
```

3. 在数据库中把需要重建的文件重置为 `pending`，并清理旧 segment。

示例 SQL：

```sql
DELETE FROM file_segments
WHERE file_id IN (
    SELECT id FROM files
    WHERE index_status IN ('completed', 'failed', 'processing')
);

UPDATE files
SET
    index_status = 'pending',
    error_code = NULL,
    error_msg = NULL,
    retry_count = 0,
    next_retry_at = NULL,
    processing_started_at = NULL,
    indexed_at = NULL
WHERE index_status IN ('completed', 'failed', 'processing');
```

4. 启动后端。
5. 进入管理页点击“立即执行”，或等待 scheduler 自动执行。
6. 文件完成后状态应变为 `completed`，新的 `file_segments` 和 LightRAG 索引会重新生成。

注意：

- `deleted/deleting` 文件不建议重建。
- 如果只想重建部分文件，可以在 SQL 中按 `filename` 或 `id` 增加过滤条件。
- 如果迁移后 `files.file_path` 指向旧机器绝对路径，需要先修正路径，否则解析原文会失败。

### 7.3 迁移并复用 LightRAG 索引

只有在以下条件都满足时才建议复用：

- embedding 模型完全相同。
- `VECTOR_DIMENSION` 完全相同。
- tokenizer/chunk 策略没有变化。
- LightRAG 版本没有明显变化。
- `backend/lightrag_storage/` 完整迁移。
- 应用数据库中的 `files/file_segments` 与 LightRAG 索引来自同一套数据。

否则更推荐重建。

## 8. LLM 模型替换

LLM 用于 LightRAG 的实体/关系抽取和查询阶段，不直接决定向量维度。

切换内网 LLM：

```env
INTERNAL_LLM_BASE_URL=https://llm-gateway.internal.example.com
INTERNAL_LLM_API_KEY=replace-with-internal-token
DEFAULT_LLM_MODEL=qwen2.5-72b-instruct
INTERNAL_LLM_TIMEOUT=60
INTERNAL_LLM_MAX_RETRIES=3
INTERNAL_LLM_TRUST_ENV=false
```

如果只改 LLM：

- 旧文件的向量索引仍可查询。
- 后续新文件索引会使用新 LLM 做抽取。
- 如果希望旧文件的实体/关系图也按新 LLM 重建，需要按第 7 节重建索引。

`INTERNAL_LLM_TRUST_ENV=false` 表示 httpx 不读取系统环境里的 `HTTP_PROXY/HTTPS_PROXY`。如果日志堆栈里出现 `http_proxy.py`，并且报 `httpx.ConnectError`，通常说明请求正在走代理；内网部署时建议保持 `false`，除非目标环境必须通过代理访问 LLM 网关。

`INTERNAL_LLM_MAX_RETRIES` 用于连接错误、超时和 5xx 的短暂重试。大文件索引会触发很多 LLM 抽取请求，建议至少设置为 `3`。

## 9. Tokenizer 替换

应用层分片使用 `DEFAULT_TOKENIZER_MODEL`。

原则：

- embedding 模型和 tokenizer 尽量保持同源。
- 中文模型优先使用对应 Hugging Face tokenizer。
- `TOKENIZER_LOCAL_FILES_ONLY=true` 时，目标环境必须已有本地缓存。
- `TOKENIZER_STRICT=true` 适合生产验收，可以强制发现缺缓存问题。

替换 tokenizer 后，旧 `file_segments` 的 token_count 和 chunk 边界不再代表新策略。因此如果希望旧文件也生效，需要重建索引。

## 10. 内网离线缓存准备

目标环境不能访问外网时，需要提前准备：

```text
offline_cache/
  tokenizers/
    BAAI/
      bge-m3/
```

本地模式需要模型权重、tokenizer 文件和 sentence-transformers 配置。至少应包含类似：

```text
config.json
modules.json
pytorch_model.bin
sentence_bert_config.json
sentencepiece.bpe.model
special_tokens_map.json
tokenizer.json
tokenizer_config.json
```

如果目标环境使用 API embedding，不一定需要携带 embedding 模型权重，但仍建议携带 tokenizer 缓存，因为应用层分片依赖 tokenizer。

## 11. 迁移验收清单

基础检查：

- `backend/.env` 已从 `.env.example` 生成，并填入目标环境真实值。
- PostgreSQL 可连接。
- `alembic upgrade head` 已执行。
- `uploads/` 存在，且数据库 `files.file_path` 能指向真实文件。
- `offline_cache/tokenizers/...` 存在，或 embedding/tokenizer API 可访问。
- `backend/lightrag_storage/` 的迁移或重建策略已确定。

启动检查：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/admin/status
```

端到端检查：

1. 上传一个小 TXT 文件。
2. 手动触发调度。
3. 文件状态变为 `completed`。
4. 检索能返回片段和引用。
5. 下载入口能下载原文。
6. 删除文件后检索立即不可见。
7. 再触发一次调度，删除文件最终进入 `deleted`。

## 12. 常见问题

### 12.1 换 embedding 后检索结果很差

通常是旧 LightRAG 索引没有重建。删除 `backend/lightrag_storage/`，重置文件状态为 `pending`，重新调度索引。

### 12.2 启动时报 embedding dimension 错误

检查：

- `VECTOR_DIMENSION` 是否等于模型实际输出维度。
- 旧 `backend/lightrag_storage/` 是否来自另一个维度的模型。

如果维度改了，必须重建索引。

### 12.3 本地模型加载失败

检查：

- `EMBEDDING_CACHE_DIR`
- `TOKENIZER_CACHE_DIR`
- `EMBEDDING_LOCAL_FILES_ONLY`
- `TOKENIZER_LOCAL_FILES_ONLY`
- 缓存目录是否包含完整模型文件。

### 12.4 API embedding 不通

检查：

- `EMBEDDING_PROVIDER=api`
- `INTERNAL_EMBEDDING_BASE_URL` 是否不带尾部 `/embeddings`
- 网关是否支持 OpenAI-compatible `/embeddings`
- `INTERNAL_EMBEDDING_API_KEY` 是否有效
- `DEFAULT_EMBEDDING_MODEL` 是否是网关支持的模型名

### 12.5 迁移数据库后解析文件失败

检查 `files.file_path`。当前上传时保存的是文件路径字符串，如果从 Windows 迁移到 Linux，或项目路径变化，旧路径可能不可用。

解决方式：

- 保持 `uploads/` 目录结构。
- 批量修正 `files.file_path` 到目标机器真实路径。
- 或重新上传文件生成新记录。
