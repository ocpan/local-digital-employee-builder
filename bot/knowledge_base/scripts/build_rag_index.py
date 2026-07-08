#!/usr/bin/env python3
"""Build a lightweight, GitHub-hostable RAG chunk layer.

Path-based: walks docs/ (raw layer) and wiki/entities|concepts (wiki layer)
directly, deriving facets (part/product/module/doc_category) from the new
taxonomy path. No longer depends on docs/00-index/manifest.csv.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

KB_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = KB_ROOT / "docs"
WIKI_ROOT = KB_ROOT / "wiki"
WIKI_CONTENT_DIRS = ("entities", "concepts")
RAG_ROOT = KB_ROOT / "rag"
CHUNKS_ROOT = RAG_ROOT / "chunks"
INDEX_ROOT = RAG_ROOT / "index"

SUPPORTED_TEXT_EXTS = {".md", ".txt", ".csv"}
SUPPORTED_BINARY_EXTS = {".docx"}
SKIP_DIR_NAMES = {"00-index"}

TARGET_CHARS = 900
MAX_CHARS = 1200
MIN_CHARS = 180
OVERLAP_CHARS = 80
KEYWORDS_PER_CHUNK = 24


@dataclass(frozen=True)
class Doc:
    path: Path
    layer: str       # raw | wiki
    part: str        # 产品 | 日常工作 | 编译层
    product: str
    module: str
    doc_category: str
    shard_key: str
    mtime: str
    size: int


def stable_id(value: str, length: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def rel(path: Path) -> str:
    return path.relative_to(KB_ROOT).as_posix()


def safe_segment(value: str) -> str:
    value = re.sub(r"[:：/\\|?*\"<>]", "_", (value or "").strip())
    value = re.sub(r"\s+", "_", value)
    return value or "综合"


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def token_estimate(text: str) -> int:
    cjk = len(re.findall(r"[一-鿿]", text))
    non_cjk_words = len(re.findall(r"[A-Za-z0-9_./#-]+", text))
    return int(cjk * 0.6 + non_cjk_words)


def tokenize(text: str) -> list[str]:
    terms: list[str] = []
    terms.extend(term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text))
    terms.extend(re.findall(r"[一-鿿]{2,8}", text))
    return terms


def top_keywords(text: str, limit: int = KEYWORDS_PER_CHUNK) -> list[str]:
    stop = {"the", "and", "for", "with", "this", "that", "from",
            "文档", "系统", "功能", "配置", "需求", "说明", "模块"}
    counts = Counter(term for term in tokenize(text) if term not in stop)
    return [term for term, _ in counts.most_common(limit)]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    meta: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_]+):[ \t]*(\S.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta, body


def facets_from_parts(parts: list[str]) -> tuple[str, str, str, str, str]:
    """parts = path segments under docs/, excluding filename."""
    part = parts[0] if parts else "其他"
    seg = parts[1:]
    if part == "产品":
        product = seg[0] if seg else "通用"
        tail = seg[1:]
        if tail and tail[0] in ("基础模块", "业务模块"):
            module = tail[1] if len(tail) > 1 else "综合"
            doc_category = tail[2] if len(tail) > 2 else "综合"
        else:
            module = ""
            doc_category = tail[0] if tail else "综合"
        shard = f"产品/{product}/{module or doc_category}"
        return part, product, module, doc_category, shard
    # 日常工作 等
    domain = seg[0] if seg else part
    if len(seg) > 1:
        product = seg[1]
        doc_category = seg[-1]
        shard = f"{part}/{domain}/{product}"
    else:
        product = domain
        doc_category = ""
        shard = f"{part}/{domain}"
    return part, domain, "", doc_category, shard


def iter_docs() -> list[Doc]:
    docs: list[Doc] = []
    # raw layer: docs/
    for path in sorted(DOCS_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relp = path.relative_to(DOCS_ROOT)
        if relp.parts and relp.parts[0] in SKIP_DIR_NAMES:
            continue
        if path.suffix.lower() not in SUPPORTED_TEXT_EXTS | SUPPORTED_BINARY_EXTS:
            continue
        part, product, module, doc_cat, shard = facets_from_parts(list(relp.parts[:-1]))
        st = path.stat()
        docs.append(Doc(path, "raw", part, product, module, doc_cat, shard,
                        datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), st.st_size))
    # wiki layer: wiki/entities|concepts
    for sub in WIKI_CONTENT_DIRS:
        base = WIKI_ROOT / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            product = meta.get("product") or meta.get("business_line") or "通用"
            st = path.stat()
            docs.append(Doc(path, "wiki", "编译层", product, "", "wiki", f"wiki/{product}",
                            datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), st.st_size))
    return docs


def extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except Exception:
        return ""
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", ns):
        texts = [node.text or "" for node in para.findall(".//w:t", ns)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs)


def read_doc_text(doc: Doc) -> tuple[str, str]:
    ext = doc.path.suffix.lower()
    if ext in SUPPORTED_TEXT_EXTS:
        try:
            return doc.path.read_text(encoding="utf-8"), ext.lstrip(".")
        except UnicodeDecodeError:
            return doc.path.read_text(encoding="utf-8", errors="ignore"), ext.lstrip(".")
    if ext == ".docx":
        return extract_docx(doc.path), "docx"
    return "", ext.lstrip(".")


@dataclass(frozen=True)
class Section:
    heading_path: tuple[str, ...]
    text: str


def markdown_sections(text: str, title: str) -> list[Section]:
    sections: list[Section] = []
    current_headings: list[str] = [title]
    current_lines: list[str] = []

    def flush() -> None:
        body = normalize_text("\n".join(current_lines))
        if body:
            sections.append(Section(tuple(current_headings), body))

    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush()
            level = len(heading.group(1))
            current_headings[:] = current_headings[:level]
            current_headings.append(heading.group(2).strip())
            current_lines.clear()
        else:
            current_lines.append(line)
    flush()
    return sections or [Section((title,), normalize_text(text))]


def plain_sections(text: str, title: str) -> list[Section]:
    lines = [line.strip() for line in text.splitlines()]
    sections: list[Section] = []
    current_heading = title
    current: list[str] = []

    def looks_like_heading(line: str) -> bool:
        if len(line) > 60 or not line:
            return False
        if re.match(r"^([一二三四五六七八九十]+[、.．]|第.+[章节]|[0-9]+[.、])", line):
            return True
        return line.endswith(("：", ":")) and len(line) <= 40

    def flush() -> None:
        body = normalize_text("\n".join(current))
        if body:
            sections.append(Section((title, current_heading), body))

    for line in lines:
        if looks_like_heading(line):
            flush()
            current_heading = line.rstrip("：:")
            current.clear()
        else:
            current.append(line)
    flush()
    return sections or [Section((title,), normalize_text(text))]


def split_long_text(text: str, target: int = TARGET_CHARS, max_chars: int = MAX_CHARS) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    blocks = re.split(r"(\n\n+)", text)
    chunks: list[str] = []
    current = ""

    def push(value: str) -> None:
        value = normalize_text(value)
        if value:
            chunks.append(value)

    for block in blocks:
        if not block.strip():
            if current:
                current += "\n\n"
            continue
        if len(block) > max_chars:
            if current:
                push(current); current = ""
            sentences = re.split(r"(?<=[。！？!?；;])", block)
            buf = ""
            for sentence in sentences:
                if len(buf) + len(sentence) <= target:
                    buf += sentence
                else:
                    push(buf)
                    buf = (buf[-OVERLAP_CHARS:] if len(buf) > OVERLAP_CHARS else "") + sentence
            if buf:
                push(buf)
            continue
        if len(current) + len(block) <= target or len(current) < MIN_CHARS:
            current += block
        else:
            push(current)
            current = (current[-OVERLAP_CHARS:] if len(current) > OVERLAP_CHARS else "") + block
    if current:
        push(current)
    return chunks


def build_chunks_for_doc(doc: Doc) -> tuple[list[dict], dict | None]:
    raw_text, source_type = read_doc_text(doc)
    _, raw_text = parse_frontmatter(raw_text)
    text = normalize_text(raw_text)
    if len(text) < 20:
        return [], None

    title = doc.path.stem
    sections = markdown_sections(text, title) if source_type in {"md", "txt"} else plain_sections(text, title)
    doc_id = stable_id(rel(doc.path))
    chunks: list[dict] = []
    ordinal = 0
    for section in sections:
        for part_index, chunk_text in enumerate(split_long_text(section.text)):
            if len(chunk_text) < 20:
                continue
            ordinal += 1
            heading_path = " > ".join(section.heading_path)
            chunk_id = stable_id(f"{doc_id}:{ordinal}:{heading_path}:{chunk_text[:80]}")
            chunks.append({
                "chunk_id": chunk_id, "doc_id": doc_id, "ordinal": ordinal,
                "doc_title": doc.path.name, "doc_path": rel(doc.path),
                "layer": doc.layer, "part": doc.part, "product": doc.product,
                "module": doc.module, "doc_category": doc.doc_category,
                "heading_path": list(section.heading_path), "section_part": part_index + 1,
                "char_count": len(chunk_text), "token_estimate": token_estimate(chunk_text),
                "keywords": top_keywords(f"{doc.path.name} {heading_path} {chunk_text}"),
                "text": chunk_text,
            })

    doc_meta = {
        "doc_id": doc_id, "doc_title": doc.path.name, "doc_path": rel(doc.path),
        "layer": doc.layer, "part": doc.part, "product": doc.product,
        "module": doc.module, "doc_category": doc.doc_category,
        "modified_at": doc.mtime, "size_bytes": doc.size, "source_type": source_type,
        "chunk_count": len(chunks), "char_count": len(text), "token_estimate": token_estimate(text),
    }
    return chunks, doc_meta


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def build_index() -> dict:
    docs = iter_docs()
    if RAG_ROOT.exists():
        shutil.rmtree(RAG_ROOT)
    CHUNKS_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_ROOT.mkdir(parents=True, exist_ok=True)

    shard_chunks: dict[str, list[dict]] = defaultdict(list)
    shard_meta: dict[str, Doc] = {}
    doc_rows: list[dict] = []
    skipped: list[dict] = []
    all_keywords: Counter = Counter()

    for doc in docs:
        chunks, doc_meta = build_chunks_for_doc(doc)
        if not doc_meta or not chunks:
            skipped.append({"doc_path": rel(doc.path), "reason": "no_extractable_text"})
            continue
        key = "/".join(safe_segment(s) for s in doc.shard_key.split("/"))
        shard_chunks[key].extend(chunks)
        shard_meta.setdefault(key, doc)
        doc_rows.append(doc_meta)
        for chunk in chunks:
            all_keywords.update(chunk["keywords"])

    shards: list[dict] = []
    total_chunks = 0
    for key, chunks in sorted(shard_chunks.items()):
        shard_path = CHUNKS_ROOT / f"{key}.jsonl"
        write_jsonl(shard_path, sorted(chunks, key=lambda i: (i["doc_path"], i["ordinal"])))
        total_chunks += len(chunks)
        d = shard_meta[key]
        shards.append({
            "shard": rel(shard_path), "chunk_count": len(chunks), "layer": d.layer,
            "part": d.part, "product": d.product, "module": d.module,
            "size_bytes": shard_path.stat().st_size,
        })

    write_jsonl(INDEX_ROOT / "documents.jsonl", sorted(doc_rows, key=lambda i: i["doc_path"]))
    write_jsonl(INDEX_ROOT / "skipped.jsonl", skipped)
    (INDEX_ROOT / "shards.json").write_text(json.dumps(shards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (INDEX_ROOT / "keywords.json").write_text(
        json.dumps(dict(all_keywords.most_common(500)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "taxonomy": "日常工作 + 产品/产品-模块-文档类别 (path-based)",
        "chunk_policy": {"target_chars": TARGET_CHARS, "max_chars": MAX_CHARS,
                         "min_chars": MIN_CHARS, "overlap_chars": OVERLAP_CHARS},
        "storage_policy": {"format": "jsonl", "embedding_vectors": False},
        "documents_indexed": len(doc_rows), "documents_skipped": len(skipped),
        "chunk_count": total_chunks, "shard_count": len(shards),
        "avg_chunk_chars": math.floor(sum(r["char_count"] for r in doc_rows) / total_chunks) if total_chunks else 0,
        "index_files": {"documents": "rag/index/documents.jsonl", "shards": "rag/index/shards.json",
                        "keywords": "rag/index/keywords.json", "skipped": "rag/index/skipped.jsonl"},
    }
    (INDEX_ROOT / "rag_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    manifest = build_index()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
