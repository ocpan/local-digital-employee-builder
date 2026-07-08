#!/usr/bin/env python3
"""Stream-search the local RAG JSONL shards without loading the full index."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path


KB_ROOT = Path(__file__).resolve().parents[1]
SHARDS_JSON = KB_ROOT / "rag" / "index" / "shards.json"


def tokenize(text: str) -> list[str]:
    terms: list[str] = []
    terms.extend(term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text))
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,8}", text))
    return terms


def load_shards(args: argparse.Namespace) -> list[Path]:
    shards = json.loads(SHARDS_JSON.read_text(encoding="utf-8"))
    result: list[Path] = []
    for shard in shards:
        if args.part and shard.get("part") != args.part:
            continue
        if args.product and shard.get("product") != args.product:
            continue
        if args.module and shard.get("module") != args.module:
            continue
        result.append(KB_ROOT / shard["shard"])
    return result


def score_chunk(chunk: dict, query_terms: list[str], wiki_boost: float = 1.0) -> float:
    text = " ".join(
        [
            chunk.get("doc_title", ""),
            " ".join(chunk.get("heading_path", [])),
            " ".join(chunk.get("keywords", [])),
            chunk.get("text", ""),
        ]
    )
    lowered = text.lower()
    score = 0.0
    for term in query_terms:
        tf = lowered.count(term.lower())
        if tf:
            score += 1.0 + math.log(tf + 1)
            if term in chunk.get("doc_title", ""):
                score += 3.0
            if term in " ".join(chunk.get("heading_path", [])):
                score += 2.0
            if term in chunk.get("keywords", []):
                score += 1.5
    if chunk.get("layer") == "wiki":
        score *= wiki_boost
    return score


def search(args: argparse.Namespace) -> list[tuple[float, dict]]:
    query_terms = tokenize(args.query)
    if not query_terms:
        query_terms = [args.query]
    results: list[tuple[float, dict]] = []
    for shard_path in load_shards(args):
        with shard_path.open("r", encoding="utf-8") as file:
            for line in file:
                chunk = json.loads(line)
                if args.layer and chunk.get("layer", "raw") != args.layer:
                    continue
                score = score_chunk(chunk, query_terms, args.wiki_boost)
                if score > 0:
                    results.append((score, chunk))
    results.sort(key=lambda item: item[0], reverse=True)
    return results[: args.top_k]


def main() -> None:
    parser = argparse.ArgumentParser(description="Search RAG chunks.")
    parser.add_argument("query")
    parser.add_argument("--part", help="日常工作 | 产品 | 编译层")
    parser.add_argument("--product", help="如 产品A / 产品B / 制度中心")
    parser.add_argument("--module", help="如 节点流 / 空间管理 / 零部件管理")
    parser.add_argument("--layer", choices=["raw", "wiki"], help="只检索某一层（raw=原文，wiki=编译产物）")
    parser.add_argument("--wiki-boost", type=float, default=1.3, help="wiki 层命中加权，>1 让编译产物优先（默认 1.3）")
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    src_file = KB_ROOT / "rag" / "index" / "source_links.json"
    source_links = json.loads(src_file.read_text(encoding="utf-8")) if src_file.exists() else {}

    for score, chunk in search(args):
        preview = re.sub(r"\s+", " ", chunk["text"])[:220]
        tag = "wiki" if chunk.get("layer") == "wiki" else "raw"
        print(f"[{score:.2f}][{tag}] {chunk['doc_title']}")
        print(f"  path: {chunk['doc_path']}")
        print(f"  heading: {' > '.join(chunk['heading_path'])}")
        src = source_links.get(chunk["doc_path"])
        if src:
            print(f"  source: {src['title']} | {src['url']}")
        print(f"  chunk_id: {chunk['chunk_id']}")
        print(f"  preview: {preview}")
        print()


if __name__ == "__main__":
    main()
