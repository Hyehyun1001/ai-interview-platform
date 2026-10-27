"""ChromaDB 임베디드 저장소: 인덱싱·검색·삭제 (TRD §3.3).

컬렉션 이름에 임베딩 모델 버전을 포함하고(교체 대비), 코사인 거리 + 정규화 벡터를 사용한다.
`similarity_search_with_relevance_scores` 와 같은 의미로 relevance = 1 - cosine_distance 를 계산하고,
임계값(0.35) 미만 결과는 버린다 — 근거 없는 컨텍스트가 질문 생성에 섞이지 않도록 한다.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.ai.rag.chunker import Chunk, chunk_jd, chunk_resume
from app.ai.rag.embedder import Embedder
from app.schemas.resume import ResumeSchema

RESUME_COLLECTION = "resume_chunks_bgem3_v1"
JD_COLLECTION = "jd_chunks_bgem3_v1"
MIN_RELEVANCE = 0.35
EMBED_BATCH = 32


def create_chroma_client(path: Path | None) -> Any:
    """path=None 이면 메모리(테스트). 텔레메트리는 항상 끈다 (TRD §8.1 외부 전송 0건)."""
    cfg = ChromaSettings(anonymized_telemetry=False, allow_reset=True)
    if path is None:
        return chromadb.EphemeralClient(cfg)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=cfg)


@dataclass
class SearchHit:
    chunk_id: str
    text: str
    score: float  # 1 - cosine distance
    metadata: dict[str, Any]


class VectorStore:
    def __init__(self, client: Any, embedder: Embedder):
        self.client, self.embedder = client, embedder

    def _collection(self, name: str) -> Any:
        return self.client.get_or_create_collection(name, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None)

    def _upsert(self, collection: str, chunks: Sequence[Chunk], base_meta: dict[str, Any]) -> int:
        col = self._collection(collection)
        for i in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[i:i + EMBED_BATCH]
            col.upsert(
                ids=[c.chunk_id for c in batch], documents=[c.text for c in batch],
                embeddings=self.embedder.embed([c.text for c in batch]),
                metadatas=[{**base_meta, **c.metadata, "chunk_id": c.chunk_id} for c in batch])
        return len(chunks)

    # ── 인덱싱 ──
    def index_resume(self, snapshot_id: str, application_id: str, user_id: str, resume: ResumeSchema, lang: str = "ko") -> int:
        """재인덱싱은 멱등: 같은 snapshot 의 기존 chunk 를 지우고 다시 넣는다."""
        self.delete_snapshot(snapshot_id)
        base = {"snapshot_id": snapshot_id, "application_id": application_id, "user_id": user_id, "lang": lang}
        return self._upsert(RESUME_COLLECTION, chunk_resume(snapshot_id, resume), base)

    def index_jd(self, job_id: str, *, requirements: str | None, preferred: str | None, duties: str | None) -> int:
        self.delete_job(job_id)
        return self._upsert(JD_COLLECTION, chunk_jd(job_id, requirements=requirements, preferred=preferred, duties=duties),
                            {"job_id": job_id})

    # ── 검색 ──
    def _search(self, collection: str, query: str, where: dict[str, Any], k: int, min_score: float) -> list[SearchHit]:
        col = self._collection(collection)
        if col.count() == 0 or not query.strip():
            return []
        res = col.query(query_embeddings=self.embedder.embed([query]), n_results=k, where=where,
                        include=["documents", "metadatas", "distances"])
        hits = [SearchHit(cid, doc, 1.0 - dist, dict(meta)) for cid, doc, meta, dist in
                zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True)]
        return [h for h in hits if h.score >= min_score]  # 근거 없는 컨텍스트 차단

    def search_resume(self, query: str, snapshot_id: str, k: int = 4, section: str | None = None,
                      min_score: float = MIN_RELEVANCE) -> list[SearchHit]:
        where: dict[str, Any] = {"snapshot_id": snapshot_id}
        if section:
            where = {"$and": [where, {"section": section}]}
        return self._search(RESUME_COLLECTION, query, where, k, min_score)

    def search_jd(self, query: str, job_id: str, k: int = 3, min_score: float = MIN_RELEVANCE) -> list[SearchHit]:
        return self._search(JD_COLLECTION, query, {"job_id": job_id}, k, min_score)

    # ── 삭제 (보관 기간 경과·계정 삭제, NFR-S7) ──
    def delete_snapshot(self, snapshot_id: str) -> None:
        self._collection(RESUME_COLLECTION).delete(where={"snapshot_id": snapshot_id})

    def delete_job(self, job_id: str) -> None:
        self._collection(JD_COLLECTION).delete(where={"job_id": job_id})

    def delete_user(self, user_id: str) -> None:
        self._collection(RESUME_COLLECTION).delete(where={"user_id": user_id})


async def index_resume_snapshot(store: VectorStore, snapshot_id: str, application_id: str, user_id: str, resume: ResumeSchema,
                                *, keep_resident: bool = False) -> int:
    """비동기 래퍼: 임베딩/Chroma 호출은 스레드에서 실행하고, 끝나면 모델을 해제한다 (TRD §2.2: 인덱싱 직후 해제)."""
    try:
        return await asyncio.to_thread(store.index_resume, snapshot_id, application_id, user_id, resume)
    finally:
        if not keep_resident:
            store.embedder.unload()


def build_precomputed_context(store: VectorStore, snapshot_id: str | None, job_id: str, slot_queries: Sequence[str],
                              k: int = 3) -> list[dict[str, Any]]:
    """면접 시작 전 질문 슬롯별 검색을 선계산한다 (TRD §2.3) — 면접 중에는 bge-m3 없이 이 결과만 사용.

    이력서가 없거나(기본 정보만) 관련도 임계값 미만이면 resume 는 빈 목록 → JD 기반 일반 질문으로 진행 (환각 차단, TRD §3.3).
    """
    slots = []
    for i, query in enumerate(slot_queries):
        resume_hits = store.search_resume(query, snapshot_id, k=k) if snapshot_id else []
        jd_hits = store.search_jd(query, job_id, k=2)
        slots.append({
            "slot": i, "query": query,
            "resume": [{"chunk_id": h.chunk_id, "text": h.text, "score": round(h.score, 3)} for h in resume_hits],
            "jd": [{"chunk_id": h.chunk_id, "text": h.text, "score": round(h.score, 3)} for h in jd_hits],
        })
    return slots
