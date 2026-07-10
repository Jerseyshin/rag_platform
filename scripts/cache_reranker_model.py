import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache a reranker model for offline use."
    )
    parser.add_argument(
        "--model",
        default="BAAI/bge-reranker-v2-m3",
        help="Model id to cache.",
    )
    parser.add_argument(
        "--source",
        choices=["modelscope", "huggingface"],
        default="modelscope",
        help="Download source. ModelScope is usually more reliable in China.",
    )
    parser.add_argument(
        "--cache-dir",
        default="offline_cache/rerankers",
        help="Project-local cache root.",
    )
    parser.add_argument(
        "--max-workers",
        default=1,
        type=int,
        help="Parallel download workers. Use 1 for unstable networks.",
    )
    parser.add_argument(
        "--timeout",
        default=60,
        type=int,
        help="Hugging Face download timeout in seconds.",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Optional endpoint. For Hugging Face, for example https://hf-mirror.com.",
    )
    args = parser.parse_args()

    target_dir = Path(args.cache_dir) / Path(*args.model.split("/"))
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if args.source == "modelscope":
        from modelscope import snapshot_download

        snapshot_download(
            model_id=args.model,
            local_dir=str(target_dir),
            max_workers=args.max_workers,
            endpoint=args.endpoint,
        )
    else:
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(args.timeout))
        os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", str(args.timeout))
        if args.endpoint:
            os.environ.setdefault("HF_ENDPOINT", args.endpoint.rstrip("/"))

        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=args.model,
            local_dir=target_dir,
            max_workers=args.max_workers,
        )
    print(f"Cached {args.model} to {target_dir}")


if __name__ == "__main__":
    main()
