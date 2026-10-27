"""임베딩 (BAAI/bge-m3, TRD §1.1). 모델은 필요한 시점에만 로드하고 사용 후 해제한다 (TRD §2.2, NFR-R3)."""
from __future__ import annotations

import gc
from typing import Protocol

EMBED_DIM = 1024


class Embedder(Protocol):
    """벡터는 L2 정규화되어 있어야 한다 (코사인 거리 = 1 - 내적)."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def unload(self) -> None: ...


class BgeM3Embedder:
    """sentence-transformers 기반 bge-m3. 지연 로딩 + 명시적 해제(MPS 캐시 비우기)."""

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "mps", batch_size: int = 8):
        self.model_name, self.device, self.batch_size = model_name, device, batch_size
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self):  # noqa: ANN202
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # 무거운 의존성: requirements-ai.txt

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._load().encode(texts, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except ImportError:  # pragma: no cover
            pass


def should_keep_resident(mode: str, free_gb: float) -> bool:
    """EMBED_KEEP_RESIDENT=auto|true|false (TRD §2.3-4): auto 는 여유 메모리 3.5GB 이상일 때만 상주 허용."""
    if mode == "true":
        return True
    if mode == "false":
        return False
    return free_gb >= 3.5
