# RAG Platform

Retrieve-only RAG 文件知识库服务。后端负责文件上传、异步索引、LightRAG 检索和引用回查；前端提供用户工作台和管理页。

## 当前能力

- 单知识库、无登录、无用户隔离，适合可信内网 MVP。
- 支持上传 PDF、DOCX、TXT、MD。
- APScheduler 扫描待索引文件，使用 PostgreSQL advisory lock 避免并发执行。
- LightRAG 使用本地 `BAAI/bge-m3` embedding function 和 OpenAI-compatible LLM。
- `POST /retrieve` 只返回片段、分数和引用，不生成最终答案。
- 删除文件后检索立即不可见，后台调度清理 LightRAG 索引并标记为 `deleted`。
- Vue 前端包含工作台和管理页。

## 环境准备

1. 创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

2. 安装前端依赖：

```powershell
cd frontend
npm install
cd ..
```

3. 准备 PostgreSQL + pgvector。

推荐使用 Docker 镜像，详细迁移和数据库说明见 [docs/knowlegde/database_migration.md](docs/knowlegde/database_migration.md)。

4. 配置后端环境变量。

复制或编辑 `backend/.env`，至少填写：

```env
DB_HOST=localhost
DB_PORT=5433
DB_NAME=rag_platform
DB_USER=postgres
DB_PASSWORD=postgres

EMBEDDING_PROVIDER=local
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
DEFAULT_TOKENIZER_MODEL=BAAI/bge-m3
EMBEDDING_CACHE_DIR=../offline_cache/tokenizers
TOKENIZER_CACHE_DIR=../offline_cache/tokenizers
EMBEDDING_LOCAL_FILES_ONLY=true
TOKENIZER_LOCAL_FILES_ONLY=true

INTERNAL_LLM_BASE_URL=https://api.deepseek.com
INTERNAL_LLM_API_KEY=你的 API Key
DEFAULT_LLM_MODEL=deepseek-chat

LIGHTRAG_WORKING_DIR=lightrag_storage
SCHEDULER_ENABLED=true
```

本地 tokenizer/embedding 缓存策略见 [docs/knowlegde/tokenizer_embedding_mvp.md](docs/knowlegde/tokenizer_embedding_mvp.md)。

## 数据库迁移

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

## 启动服务

后端：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

接口文档：

- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/health

前端：

```powershell
cd frontend
npm run dev
```

页面地址：

- http://127.0.0.1:5173/

## 演示流程

1. 打开前端工作台。
2. 选择一个 TXT、MD、DOCX 或 PDF 文件上传。
3. 打开管理页，点击“立即执行”触发索引。
4. 回到工作台刷新文件列表，等待状态变为 `completed`。
5. 输入问题执行检索，结果会展示片段、分数、文件名、页码或段落位置。
6. 点击结果里的下载入口核验原文。
7. 删除文件后再次检索，该文件的片段应立即不可见。
8. 再触发一次调度，删除中的文件会被清理为 `deleted`。

## 常用命令

后端编译检查：

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

查看接口：

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/admin/status
```

## 重要目录

- `backend/app`: FastAPI 后端代码。
- `frontend/src`: Vue 前端代码。
- `docs/design.md`: 架构设计。
- `docs/tasks.md`: 实施任务清单。
- `offline_cache/`: 本地 tokenizer/embedding 缓存，体积较大，不入 Git。
- `backend/lightrag_storage/`: LightRAG 运行时向量库和图索引数据，不入 Git。
- `backend/uploads/`: 上传原文文件。
