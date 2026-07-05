# MVP Embedding 与 Tokenizer 缓存说明

本文记录 MVP 阶段的 embedding/tokenizer 选择，以及离线部署前需要准备的缓存。

## MVP 决策

- Embedding 模型：`BAAI/bge-m3`
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
