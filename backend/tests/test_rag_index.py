"""청킹 · 임베딩 인덱싱 · ChromaDB 검색/삭제 · 사전 검색 · 구조화 추출 (TRD §3.2, §3.3, §2.3, §3.1)."""
from __future__ import annotations

import pytest

from app.ai.rag.chunker import (EXPERIENCE_MAX, SELF_INTRO_MAX, SELF_INTRO_OVERLAP, chunk_jd, chunk_resume, recursive_split)
from app.ai.rag.embedder import BgeM3Embedder, should_keep_resident
from app.ai.rag.extractor import build_input, extract_resume, sanitize_against_source
from app.ai.rag.store import (JD_COLLECTION, MIN_RELEVANCE, RESUME_COLLECTION, VectorStore, build_precomputed_context,
                              create_chroma_client, index_resume_snapshot)
from app.schemas.resume import Education, Experience, Project, ResumeSchema, is_basic_info_complete
from tests.fakes import HashEmbedder, ScriptedFactory

RESUME = ResumeSchema(
    name="김지원",
    education=[Education(school="한빛대학교", major="컴퓨터공학", degree="학사", start="2018.03", end="2022.02")],
    experience=[Experience(company="(주)다온커머스", role="백엔드 개발자", start="2022.03", end="현재",
                           summary="주문 결제 API 개발, Redis 캐시 도입으로 조회 응답 시간 개선"),
                Experience(company="(주)새솔랩", role="인턴", start="2021.07", end="2021.12", summary="관리자 페이지 REST API 개발")],
    projects=[Project(title="주문 조회 성능 개선", role="리드", period="2023.04~2023.09", tech_stack=["Spring Boot", "Redis", "MySQL"],
                      description="조회 응답 800ms 를 200ms 로 단축, 캐시 무효화 전략 설계"),
              Project(title="이벤트 처리 파이프라인", tech_stack=["Kafka"], description="주문 상태 이벤트를 비동기로 처리하고 멱등성 키 적용")],
    skills=["Java", "Redis", "Kafka"], certifications=["정보처리기사"],
    self_intro="문제의 원인을 수치로 확인합니다. " * 60)


@pytest.fixture
def store():
    client = create_chroma_client(None)
    client.reset()
    return VectorStore(client, HashEmbedder())


# ── 기본 정보 규칙 (PRD 10장 #9) ─────────────────────────────────────────────
@pytest.mark.parametrize("data,ok", [
    ({"name": "홍", "education": [{"school": "한빛대"}]}, True), ({"name": "홍", "experience": [{"company": "다온"}]}, True),
    ({"name": "홍"}, False), ({"education": [{"school": "한빛대"}]}, False), ({"name": "  ", "education": [{"school": "x"}]}, False),
    ({"name": "홍", "education": [{"major": "컴공"}]}, False), ({"name": "홍", "self_intro": "자소서만"}, False), (None, False)])
def test_basic_info_complete_rule(data, ok):
    assert is_basic_info_complete(data) is ok


# ── 청킹 ─────────────────────────────────────────────────────────────────────
def test_chunk_resume_one_chunk_per_experience_and_project_with_ids_and_metadata():
    chunks = chunk_resume("snap1", RESUME)
    by_section = {}
    for c in chunks:
        by_section.setdefault(c.metadata["section"], []).append(c)
    assert len(by_section["experience"]) == 2 and len(by_section["project"]) == 2 and len(by_section["profile"]) == 1
    exp = by_section["experience"][0]
    assert exp.chunk_id == "snap1:experience:0" and exp.metadata["company"] == "(주)다온커머스" and "Redis" in exp.text
    proj = by_section["project"][0]
    assert proj.metadata["tech_stack"] == "Spring Boot,Redis,MySQL" and "기술스택" in proj.text  # 리스트 → 문자열 (Chroma 메타데이터는 원시값만)
    profile = by_section["profile"][0].text
    assert "한빛대학교" in profile and "정보처리기사" in profile and "Kafka" in profile
    assert len({c.chunk_id for c in chunks}) == len(chunks)  # chunk_id 는 질문 근거 인용에 쓰이므로 유일해야 한다
    assert all(isinstance(v, (str, int, float, bool)) for c in chunks for v in c.metadata.values())


def test_self_intro_is_split_into_overlapping_paragraph_chunks():
    intro = [c for c in chunk_resume("s", RESUME) if c.metadata["section"] == "self_intro"]
    assert len(intro) > 1 and all(len(c.text) <= SELF_INTRO_MAX for c in intro)
    assert [c.metadata["para_idx"] for c in intro] == list(range(len(intro)))
    assert intro[0].text[-SELF_INTRO_OVERLAP // 2:] in intro[1].text  # 인접 chunk 끼리 문맥이 겹친다


def test_long_experience_is_split_but_short_ones_are_not():
    long = ResumeSchema(experience=[Experience(company="큰회사", summary="상세한 업무 내용입니다. " * 200)])
    parts = [c for c in chunk_resume("s", long) if c.metadata["section"] == "experience"]
    assert len(parts) > 1 and all(len(c.text) <= EXPERIENCE_MAX for c in parts)
    assert len([c for c in chunk_resume("s", RESUME) if c.metadata["section"] == "experience"]) == 2


def test_chunk_resume_handles_minimal_and_empty_resume():
    assert chunk_resume("s", ResumeSchema()) == []
    only_name = chunk_resume("s", ResumeSchema(name="홍길동"))
    assert [c.metadata["section"] for c in only_name] == ["profile"]


def test_chunk_jd_sections():
    chunks = chunk_jd("job1", requirements="Java 경험 1년", preferred=None, duties="API 개발\n성능 개선")
    assert [(c.chunk_id, c.metadata["section"]) for c in chunks] == [("job1:jd_req:0", "jd_req"), ("job1:jd_duty:0", "jd_duty")]


def test_recursive_split_properties():
    text = "첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다. " * 30
    parts = recursive_split(text, 100, 20)
    assert all(0 < len(p) <= 100 for p in parts) and len(parts) > 3  # 겹침을 포함해도 상한을 넘지 않는다
    assert "".join(p for p in recursive_split("가" * 250, 100, 0)) == "가" * 250  # 구분자가 없으면 하드 분할, 손실 없음
    assert recursive_split("", 10) == [] and recursive_split("짧다", 10) == ["짧다"]


# ── 인덱싱 / 검색 (TRD §3.3) ─────────────────────────────────────────────────
def test_index_and_search_returns_most_relevant_chunk_first(store):
    n = store.index_resume("snap1", "app1", "user1", RESUME)
    assert n == len(chunk_resume("snap1", RESUME)) and store.client.get_collection(RESUME_COLLECTION).count() == n
    hits = store.search_resume("Redis 캐시 도입 주문 결제 API", "snap1", k=3, min_score=0.0)
    assert hits[0].chunk_id.startswith("snap1:experience") or hits[0].chunk_id.startswith("snap1:project")
    assert "Redis" in hits[0].text and hits[0].score > hits[-1].score >= 0
    m = hits[0].metadata
    assert (m["snapshot_id"], m["application_id"], m["user_id"], m["lang"]) == ("snap1", "app1", "user1", "ko")  # TRD 메타데이터 키


def test_search_is_scoped_to_snapshot_and_section(store):
    store.index_resume("snapA", "a", "u1", RESUME)
    store.index_resume("snapB", "b", "u2", ResumeSchema(name="박다른", experience=[Experience(company="다른회사", summary="Redis 캐시 운영")]))
    ids_a = {h.chunk_id for h in store.search_resume("Redis 캐시", "snapA", k=10, min_score=0.0)}
    assert ids_a and all(i.startswith("snapA:") for i in ids_a)  # 다른 지원자의 이력서가 섞이지 않는다 (NFR-S6)
    only_proj = store.search_resume("Redis 캐시", "snapA", k=10, section="project", min_score=0.0)
    assert only_proj and {h.metadata["section"] for h in only_proj} == {"project"}


def test_relevance_threshold_drops_unrelated_context(store):
    store.index_resume("snap1", "a", "u", RESUME)
    assert MIN_RELEVANCE == 0.35
    assert store.search_resume("zzzxqwv 완전히 무관한 영문 난수 문자열", "snap1") == []  # 근거 없는 컨텍스트 차단
    assert store.search_resume("Redis 캐시 도입 주문 결제 API", "snap1")  # 관련 질의는 통과


def test_search_on_empty_store_or_blank_query_returns_empty(store):
    assert store.search_resume("Redis", "none") == [] and store.search_jd("x", "job") == []
    store.index_resume("snap1", "a", "u", RESUME)
    assert store.search_resume("   ", "snap1") == []


def test_reindex_is_idempotent_and_replaces_old_chunks(store):
    store.index_resume("snap1", "a", "u", RESUME)
    first = store.client.get_collection(RESUME_COLLECTION).count()
    store.index_resume("snap1", "a", "u", ResumeSchema(name="김지원", skills=["Go"]))  # 수정본으로 재인덱싱
    col = store.client.get_collection(RESUME_COLLECTION)
    assert col.count() == 1 < first
    assert "Go" in col.get()["documents"][0] and not store.search_resume("Redis 캐시 도입", "snap1")


def test_delete_by_snapshot_user_and_job(store):
    store.index_resume("s1", "a1", "u1", RESUME)
    store.index_resume("s2", "a2", "u1", RESUME)
    store.index_resume("s3", "a3", "u2", RESUME)
    store.delete_snapshot("s1")
    assert not store.search_resume("Redis 캐시", "s1", min_score=0.0) and store.search_resume("Redis 캐시", "s2", min_score=0.0)
    store.delete_user("u1")  # 계정 삭제 요청 (NFR-S7)
    assert not store.search_resume("Redis 캐시", "s2", min_score=0.0) and store.search_resume("Redis 캐시", "s3", min_score=0.0)
    store.index_jd("job1", requirements="Java Spring 경험", preferred=None, duties="API 개발")
    assert store.search_jd("Java Spring", "job1", min_score=0.0)
    store.delete_job("job1")
    assert not store.search_jd("Java Spring", "job1", min_score=0.0)


def test_collections_use_cosine_space_and_versioned_names(store):
    store.index_resume("s", "a", "u", RESUME)
    store.index_jd("j", requirements="Java", preferred=None, duties=None)
    assert RESUME_COLLECTION.endswith("_bgem3_v1") and JD_COLLECTION.endswith("_bgem3_v1")
    assert store.client.get_collection(RESUME_COLLECTION).configuration["hnsw"]["space"] == "cosine"


async def test_index_snapshot_unloads_model_unless_kept_resident(store):
    await index_resume_snapshot(store, "s1", "a", "u", RESUME)
    assert store.embedder.unloaded == 1  # 인덱싱 직후 해제 (TRD §2.2, NFR-R3)
    await index_resume_snapshot(store, "s2", "a", "u", RESUME, keep_resident=True)
    assert store.embedder.unloaded == 1


@pytest.mark.parametrize("mode,free,expected", [("true", 0.1, True), ("false", 99, False), ("auto", 3.5, True), ("auto", 3.49, False)])
def test_should_keep_resident(mode, free, expected):
    assert should_keep_resident(mode, free) is expected


def test_bge_m3_embedder_is_lazy_and_unload_is_safe_before_load():
    e = BgeM3Embedder(device="cpu")
    assert not e.loaded and e.embed([]) == []  # 빈 입력은 모델을 로드하지 않는다
    e.unload()
    assert not e.loaded


# ── 면접 전 사전 검색 (TRD §2.3) ─────────────────────────────────────────────
def test_precomputed_context_per_slot_with_resume_and_jd(store):
    store.index_resume("snap1", "a", "u", RESUME)
    store.index_jd("job1", requirements="Redis 캐시 운영 경험", preferred=None, duties="주문 결제 API 개발")
    slots = build_precomputed_context(store, "snap1", "job1", ["Redis 캐시 도입 경험", "Kafka 이벤트 처리 멱등성"])
    assert [s["slot"] for s in slots] == [0, 1]
    assert slots[0]["resume"] and slots[0]["jd"] and slots[0]["resume"][0]["chunk_id"].startswith("snap1:")
    assert all(set(h) == {"chunk_id", "text", "score"} for h in slots[0]["resume"])


def test_precomputed_context_without_resume_uses_jd_only(store):
    store.index_jd("job1", requirements="Redis 캐시 운영 경험", preferred=None, duties=None)
    slots = build_precomputed_context(store, None, "job1", ["Redis 캐시"])
    assert slots[0]["resume"] == [] and slots[0]["jd"]  # 이력서 없이도 오류 없이 진행 (PRD 수용기준)


# ── 구조화 추출: 환각 제거 ───────────────────────────────────────────────────
SOURCE = "김지원\n학력\n한빛대학교 컴퓨터공학 학사\n경력\n(주)다온커머스 백엔드 개발자 Redis 캐시 도입\n프로젝트\n주문 조회 성능 개선 Spring Boot Redis\n기술\nJava Redis"


def test_sanitize_drops_entities_not_in_source_text():
    hallucinated = ResumeSchema(
        name="김지원", education=[Education(school="한빛대학교"), Education(school="서울대학교")],
        experience=[Experience(company="(주)다온커머스"), Experience(company="구글코리아")],
        projects=[Project(title="주문 조회 성능 개선", tech_stack=["Redis", "GraphQL"]), Project(title="없는 프로젝트")],
        skills=["Java", "Rust"], certifications=["정보처리기사"])
    clean, dropped = sanitize_against_source(hallucinated, SOURCE)
    assert [e.school for e in clean.education] == ["한빛대학교"] and [x.company for x in clean.experience] == ["(주)다온커머스"]
    assert [p.title for p in clean.projects] == ["주문 조회 성능 개선"] and clean.projects[0].tech_stack == ["Redis"]
    assert clean.skills == ["Java"] and clean.certifications == []
    assert dropped == 5  # 서울대학교 · 구글코리아 · 없는 프로젝트 · Rust · 정보처리기사 (프로젝트 내부 기술스택 GraphQL 은 항목 수에 포함하지 않음)


def test_sanitize_drops_hallucinated_name_but_keeps_legit_one():
    clean, dropped = sanitize_against_source(ResumeSchema(name="이몽룡"), SOURCE)
    assert clean.name is None and dropped == 1
    assert sanitize_against_source(ResumeSchema(name="김 지원"), SOURCE)[0].name == "김 지원"  # 띄어쓰기 변이는 허용


def test_build_input_applies_section_quotas_and_excludes_self_intro():
    sections = {"profile": "p" * 1000, "experience": "e" * 5000, "self_intro": "자소서 본문", "education": "학력"}
    text = build_input(sections)
    assert "자소서" not in text and len(text) <= 3000 and text.count("e") <= 1100 + 20


def _resume_json(**kw) -> str:
    import json

    base = {"name": "김지원", "education": [{"school": "한빛대학교"}], "experience": [{"company": "(주)다온커머스", "role": "백엔드 개발자"}],
            "projects": [], "skills": ["Java", "Rust"], "certifications": [], "self_intro": "LLM 이 만든 자소서"}
    return json.dumps({**base, **kw}, ensure_ascii=False)


async def test_extract_resume_sanitizes_and_uses_original_self_intro():
    llm = ScriptedFactory([_resume_json()])
    res = await extract_resume(llm, {"profile": "김지원", "education": "한빛대학교", "experience": "(주)다온커머스 백엔드 개발자 Java",
                                     "self_intro": "원문 그대로의 자소서입니다"})
    assert not res.fell_back and res.dropped == 1  # Rust 는 원문에 없다
    assert res.resume.skills == ["Java"] and res.resume.name == "김지원"
    assert res.resume.self_intro == "원문 그대로의 자소서입니다"  # LLM 이 만든 자소서는 버리고 원문 사용
    assert llm.temperatures == [0.0] and "<untrusted>" in llm.calls[0]["prompt"]  # 추출은 온도 0 (TRD §3.1)


async def test_extract_resume_falls_back_to_empty_resume_after_three_invalid_outputs():
    llm = ScriptedFactory(["이력서를 읽을 수 없습니다", "죄송합니다. 추출할 수 없어요", "no json here at all"])
    res = await extract_resume(llm, {"profile": "김지원", "self_intro": "자소서"})
    assert res.fell_back and res.resume.name is None and res.resume.education == []  # 지원자가 직접 작성하도록 전환
    assert res.resume.self_intro == "자소서" and len(llm.calls) == 3 and llm.temperatures == [0.0] * 3


@pytest.mark.parametrize("empty", ["{}", "[]", '{"name": null, "education": []}'])
async def test_extract_resume_treats_empty_but_schema_valid_output_as_failure(empty):
    res = await extract_resume(ScriptedFactory([empty]), {"profile": "김지원", "self_intro": "자소서"})
    assert res.fell_back and res.resume.self_intro == "자소서"
