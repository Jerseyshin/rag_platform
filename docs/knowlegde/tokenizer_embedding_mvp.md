# MVP Embedding 与 Tokenizer 缓存说明

本文记录 MVP 阶段的 embedding/tokenizer 选择，以及离线部署前需要准备的缓存。

## MVP 决策

- Embedding 模型：`BAAI/bge-m3`
- Rerank 模型：`BAAI/bge-reranker-v2-m3`
- Embedding 维度：`1024`
- 应用层分片 tokenizer：`BAAI/bge-m3` 对应 tokenizer
- LightRAG tokenizer：显式配置，不依赖默认 `gpt-4o-mini`

T5 的 `TokenChunker` 应按 tokenizer token 进行 `chunk_size/chunk_overlap` 控制，不再使用 `text.split()`。这样中文文本不会因为没有空格而被错误地当成一个 token。

## 环境变量

```env
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
DEFAULT_TOKENIZER_MODEL=BAAI/bge-m3
VECTOR_DIMENSION=1024
EMBEDDING_PROVIDER=local
EMBEDDING_CACHE_DIR=./offline_cache/tokenizers
EMBEDDING_LOCAL_FILES_ONLY=true
EMBEDDING_NORMALIZE=true
RERANK_ENABLED=false
RERANK_PROVIDER=local
DEFAULT_RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_CACHE_DIR=./offline_cache/rerankers
RERANK_LOCAL_FILES_ONLY=true
RERANK_BATCH_SIZE=8
RERANK_MAX_LENGTH=1024
TOKENIZER_CACHE_DIR=./offline_cache/tokenizers
TIKTOKEN_CACHE_DIR=./offline_cache/tiktoken
TOKENIZER_LOCAL_FILES_ONLY=true
TOKENIZER_STRICT=false
```

`TOKENIZER_STRICT=false` 时，开发环境如果缺少 `transformers` 或本地缓存，会回退到 `mixed-text-fallback`，保证服务能启动；生产验收建议设置为 `true`，让缺缓存问题尽早暴露。

## Python 依赖

`BAAI/bge-m3` tokenizer 通过 Hugging Face `transformers` 加载：

```powershell
.\.venv\Scripts\pip install -r backend\requirements.txt
```

## Hugging Face 模型缓存

如果部署环境不能访问外网，需要提前缓存 `BAAI/bge-m3` 的 tokenizer 和模型文件。

建议目录：

```text
offline_cache/
  tokenizers/
    BAAI/
      bge-m3/
```

后续实现中应优先从 `TOKENIZER_CACHE_DIR` 或本地模型目录加载 tokenizer，避免运行时联网下载。

当前项目缓存状态：

- 缓存日期：2026-07-05
- 缓存路径：`offline_cache/tokenizers/BAAI/bge-m3`
- 缓存大小：约 4.27 GB
- 已包含：`pytorch_model.bin`、`tokenizer.json`、`sentencepiece.bpe.model`、`config.json`、ONNX 相关文件等。
- 已验证：`local_files_only=True` 且 `strict=True` 时，`HuggingFaceTokenizer` 可以从项目目录离线加载 `BAAI/bge-m3` tokenizer。

注意：当前本地环境尚未安装 PyTorch，因此只能验证 tokenizer 离线加载；后续如需在本服务内直接运行本地 embedding，还需要补充 PyTorch/ONNX Runtime 或接入内部 embedding 网关。

## Rerank 缓存

本项目在应用层执行 rerank：LightRAG 先召回候选 chunk，后端再用本地 reranker 对业务可见片段重新打分排序。这样删除过滤、文件状态过滤、引用回查之后的结果排序是稳定的。

MVP 模型：

- `BAAI/bge-reranker-v2-m3`

建议缓存目录：

```text
offline_cache/
  rerankers/
    BAAI/
      bge-reranker-v2-m3/
```

推荐下载命令（国内网络优先使用 ModelScope）：

```powershell
.\.venv\Scripts\python.exe scripts\cache_reranker_model.py --source modelscope --model BAAI/bge-reranker-v2-m3 --cache-dir offline_cache\rerankers --max-workers 1
```

如果网络环境适合 Hugging Face 或镜像源，也可以使用：

```powershell
.\.venv\Scripts\python.exe scripts\cache_reranker_model.py --source huggingface --model BAAI/bge-reranker-v2-m3 --cache-dir offline_cache\rerankers --endpoint https://hf-mirror.com --max-workers 1
```

后端从 `RERANK_CACHE_DIR` 查找本地模型目录。`RERANK_LOCAL_FILES_ONLY=true` 时，如果缓存不存在，检索会明确失败，避免静默联网或退回随机顺序。缓存完成后，将 `RERANK_ENABLED=true` 打开本地 rerank。

Rerank 只影响后续 `/retrieve` 的排序和 `score`，不影响已完成索引，不需要重建 `backend/lightrag_storage/`。

### 离线 rerank 配置

`backend/.env` 推荐配置：

```env
RERANK_ENABLED=true
RERANK_PROVIDER=local
DEFAULT_RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_CACHE_DIR=../offline_cache/rerankers
RERANK_LOCAL_FILES_ONLY=true
RERANK_BATCH_SIZE=8
RERANK_MAX_LENGTH=1024
```

路径说明：

- 如果后端从 `backend/` 目录启动，`../offline_cache/rerankers` 指向项目根目录下的 `offline_cache/rerankers/`。
- 本地模型目录必须存在：`offline_cache/rerankers/BAAI/bge-reranker-v2-m3/`。
- 目录内至少包含：`model.safetensors`、`tokenizer.json`、`sentencepiece.bpe.model`、`config.json`、`tokenizer_config.json`、`special_tokens_map.json`。

为了强制 transformers 不联网，可在启动后端前设置：

```powershell
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"
```

然后启动后端：

```powershell
Set-Location backend
..\.venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
```

如果使用当前 PowerShell 会话启动后端，上面的离线环境变量只对当前会话和子进程生效。新开终端需要重新设置。

离线验证命令：

```powershell
$env:PYTHONPATH="backend"
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"
Push-Location backend
..\.venv\Scripts\python.exe -c "from app.infrastructure.rerank_client import get_rerank_client; import asyncio; c=get_rerank_client(); print(c.model_name); print(c.tokenizer.__class__.__name__); print(c.model.__class__.__name__); print(asyncio.run(c.score('工程师', ['工程师负责系统设计', '苹果是一种水果'])))"
Pop-Location
```

成功时会看到类似：

```text
BAAI/bge-reranker-v2-m3
XLMRobertaTokenizerFast
XLMRobertaForSequenceClassification
[0.8259..., 0.00001...]
```

这表示 reranker 在离线模式下从本地缓存加载，并完成了本地打分。

## Embedding Provider 模式

当前 MVP 临时使用本地模式：

```env
EMBEDDING_PROVIDER=local
EMBEDDING_CACHE_DIR=./offline_cache/tokenizers
```

本地模式会通过 `sentence-transformers` 从项目缓存目录加载 `BAAI/bge-m3`，适合离线演示和内网无 embedding 网关的开发环境。

后续生产模式切到 API：

```env
EMBEDDING_PROVIDER=api
INTERNAL_EMBEDDING_BASE_URL=https://embedding-gateway.internal.company.com/v1
INTERNAL_EMBEDDING_API_KEY=sk-internal-xxxxxxxxxxxxx
INTERNAL_EMBEDDING_TIMEOUT=60
```

API 模式按 OpenAI-compatible embeddings 风格调用 `/embeddings`，认证方式与大模型 API token 类似。索引流程不需要改动，只替换 provider 配置。

## tiktoken 缓存

LightRAG 默认会用 `tiktoken_model_name="gpt-4o-mini"` 创建 tokenizer，对应 encoding 是 `o200k_base`。如果没有缓存，受限网络环境会尝试访问 `openaipublic.blob.core.windows.net` 并失败。

如果 T6 适配层仍使用 LightRAG tiktoken tokenizer，需要提前执行：

```powershell
.\.venv\Scripts\lightrag-download-cache --cache-dir .\offline_cache\tiktoken --models o200k_base cl100k_base
```

最小缓存建议：

- `o200k_base`：LightRAG 默认 `gpt-4o-mini` tokenizer 需要。
- `cl100k_base`：OpenAI embedding 或部分旧 GPT 模型常用。

## T6 前置要求

- `TokenChunker` 支持可插拔 tokenizer。
- 默认 tokenizer 与 `DEFAULT_TOKENIZER_MODEL=BAAI/bge-m3` 对齐。
- LightRAGClient 初始化时显式传入 tokenizer 策略。
- 插入 LightRAG 时避免应用层 segment 被再次切碎；如无法完全避免，检索响应仍必须通过 `segment_id` 回查 `file_segments`。
