from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from docx import Document
from pypdf import PdfReader

from .terminology import expand_terminology


TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{2,}")
SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".csv", ".xlsx", ".json", ".yaml", ".yml", ".py"}
EXCLUDED_NAMES = {".env", ".git", ".venv", "__pycache__", "node_modules", "secrets", "credentials"}


@dataclass(frozen=True)
class Passage:
    text: str
    document: str
    location: str
    score: float


@dataclass(frozen=True)
class _Chunk:
    text: str
    retrieval_text: str
    document: str
    location: str
    terms: Counter[str]


class WorkspaceIndex:
    """Local hybrid BM25 + dense retrieval with cross-encoder reranking."""

    def __init__(self, root: str | Path, *, max_file_bytes: int = 5_000_000, enable_semantic: bool | None = None):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError(f"Workspace is not a directory: {self.root}")
        self.max_file_bytes = max_file_bytes
        self.enable_semantic = (os.getenv("RETRIEVAL_ENABLE_SEMANTIC", "true").casefold() == "true") if enable_semantic is None else enable_semantic
        self._chunks: list[_Chunk] = []
        self._document_frequency: Counter[str] = Counter()
        self._average_length = 0.0
        self._dense_matrix: np.ndarray | None = None
        self._embedding_model = None
        self._reranker = None
        self.semantic_ready = False
        self.semantic_error: str | None = None
        self.skipped: list[str] = []

    def build(self) -> int:
        self._chunks.clear()
        self.skipped.clear()
        for path in self.root.rglob("*"):
            if not self._allowed(path):
                continue
            try:
                for text, location in _extract(path):
                    for chunk in _chunk_text(text):
                        retrieval_text = expand_terminology(chunk)
                        terms = Counter(_tokens(retrieval_text))
                        if terms:
                            relative = str(path.relative_to(self.root))
                            self._chunks.append(_Chunk(chunk, retrieval_text, relative, location, terms))
            except Exception as error:
                self.skipped.append(f"{path.name}: {type(error).__name__}")
        self._prepare_bm25()
        if self.enable_semantic and self._chunks:
            self._prepare_semantic()
        return len(self._chunks)

    def search(self, question: str, top_k: int = 5, minimum_score: float = 0.02) -> list[Passage]:
        if not question.strip() or not self._chunks:
            return []
        normalized_query = expand_terminology(question)
        candidate_limit = min(len(self._chunks), max(top_k * 4, 12))
        bm25 = self._bm25_scores(normalized_query)
        lexical_order = np.argsort(bm25)[::-1][:candidate_limit]
        candidate_ids = set(int(index) for index in lexical_order if bm25[index] > 0)
        dense = np.zeros(len(self._chunks), dtype=np.float32)
        if self.semantic_ready and self._dense_matrix is not None:
            query_vector = np.asarray(list(self._embedding_model.query_embed([normalized_query]))[0], dtype=np.float32)
            query_vector /= max(float(np.linalg.norm(query_vector)), 1e-12)
            dense = self._dense_matrix @ query_vector
            candidate_ids.update(int(index) for index in np.argsort(dense)[::-1][:candidate_limit])
        if not candidate_ids:
            return []

        # Reciprocal-rank fusion avoids incompatible BM25 and cosine score scales.
        fused: Counter[int] = Counter()
        for rank, index in enumerate(np.argsort(bm25)[::-1][:candidate_limit]):
            if bm25[index] > 0:
                fused[int(index)] += 1.0 / (60 + rank + 1)
        if self.semantic_ready:
            for rank, index in enumerate(np.argsort(dense)[::-1][:candidate_limit]):
                fused[int(index)] += 1.0 / (60 + rank + 1)
        ordered = sorted(candidate_ids, key=lambda index: fused[index], reverse=True)[:candidate_limit]

        if self.semantic_ready and self._reranker is not None:
            raw_scores = list(self._reranker.rerank(normalized_query, [self._chunks[index].retrieval_text for index in ordered]))
            final = [(index, _sigmoid(float(score))) for index, score in zip(ordered, raw_scores)]
        else:
            peak = max((fused[index] for index in ordered), default=1.0)
            final = [(index, fused[index] / peak) for index in ordered]
        results = []
        for index, score in sorted(final, key=lambda item: item[1], reverse=True):
            if score < minimum_score:
                continue
            chunk = self._chunks[index]
            results.append(Passage(chunk.text, chunk.document, chunk.location, round(score, 6)))
            if len(results) >= top_k:
                break
        return results

    def _prepare_bm25(self) -> None:
        self._document_frequency = Counter(term for chunk in self._chunks for term in chunk.terms)
        self._average_length = sum(sum(chunk.terms.values()) for chunk in self._chunks) / len(self._chunks) if self._chunks else 0.0

    def _bm25_scores(self, question: str, k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        query_terms = Counter(_tokens(question))
        count = len(self._chunks)
        scores = np.zeros(count, dtype=np.float32)
        for index, chunk in enumerate(self._chunks):
            length = sum(chunk.terms.values())
            for term, query_frequency in query_terms.items():
                frequency = chunk.terms.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency[term]
                idf = math.log(1 + (count - document_frequency + 0.5) / (document_frequency + 0.5))
                denominator = frequency + k1 * (1 - b + b * length / max(self._average_length, 1.0))
                scores[index] += query_frequency * idf * (frequency * (k1 + 1) / denominator)
        return scores

    def _prepare_semantic(self) -> None:
        try:
            from fastembed import TextEmbedding
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            local_only = os.getenv("RETRIEVAL_LOCAL_FILES_ONLY", "true").casefold() == "true"
            cpu_threads = max(1, int(os.getenv("RETRIEVAL_CPU_THREADS", "2")))
            cpu_runtime = {"providers": ["CPUExecutionProvider"], "cuda": False, "threads": cpu_threads}
            self._embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", local_files_only=local_only, **cpu_runtime)
            self._reranker = TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2", local_files_only=local_only, **cpu_runtime)
            matrix = np.asarray(list(self._embedding_model.passage_embed([chunk.retrieval_text for chunk in self._chunks])), dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            self._dense_matrix = matrix / np.maximum(norms, 1e-12)
            self.semantic_ready = True
            self.semantic_error = None
        except Exception as error:
            self.semantic_ready = False
            self.semantic_error = f"{type(error).__name__}: {error}"

    def _allowed(self, path: Path) -> bool:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return False
        if not resolved.is_relative_to(self.root) or path.is_symlink() or not path.is_file():
            return False
        relative_parts = {part.casefold() for part in path.relative_to(self.root).parts}
        if relative_parts & EXCLUDED_NAMES or path.name.casefold() in EXCLUDED_NAMES:
            return False
        if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
            return False
        if path.stat().st_size > self.max_file_bytes:
            self.skipped.append(f"{path.name}: file too large")
            return False
        return True


def _extract(path: Path) -> Iterable[tuple[str, str]]:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        for page_number, page in enumerate(PdfReader(path).pages, start=1):
            yield page.extract_text() or "", f"page {page_number}"
    elif suffix == ".docx":
        document = Document(path)
        yield "\n".join(p.text for p in document.paragraphs), "document"
    elif suffix == ".xlsx":
        book = pd.ExcelFile(path)
        for sheet in book.sheet_names:
            frame = pd.read_excel(book, sheet_name=sheet)
            yield frame.to_csv(index=False), f"sheet {sheet}"
    elif suffix == ".csv":
        yield pd.read_csv(path).to_csv(index=False), "table"
    elif suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        yield json.dumps(value, ensure_ascii=False, indent=2), "document"
    else:
        yield path.read_text(encoding="utf-8", errors="replace"), "document"


def _chunk_text(text: str, chunk_size: int = 1400, overlap: int = 200) -> Iterable[str]:
    text = text.strip()
    start = 0
    while start < len(text):
        yield text[start:start + chunk_size]
        start += chunk_size - overlap


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text)]


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)
