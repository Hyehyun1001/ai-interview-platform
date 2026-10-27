"""개발·E2E 시드 데이터 (공고 작성 API 가 아직 없어 ORM 으로 직접 만든다).

  python scripts/seed_dev.py            # 현재 DATABASE_URL(.env)에 시드. 이미 있으면 건너뜀
계정(비밀번호 Passw0rd!): applicant@corp.local (지원자), hr@corp.local (담당자)
**개발 전용** — 운영 DB 에 실행하지 않는다.
"""
from __future__ import annotations

import asyncio
import math
import struct
import sys
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import create_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.interview.media_store import MediaStore  # noqa: E402
from app.models import (Application, Company, EvalWeight, EvaluationReport, FollowupRule, GazeEvent, InterviewSession, InterviewTurn,  # noqa: E402
                        JobPosting, JobQuestion, ReportScore, User, VoiceTimeline)
from app.models.base import utcnow  # noqa: E402
from app.models.enums import (AiPassPrediction, ApplicationStatus, GazeKind, JobStatus, QuestionSource, ReportStatus, SessionState,  # noqa: E402
                              Criterion, TimelineKind, TurnKind, UserRole)

PASSWORD = "Passw0rd!"
QUESTIONS = ["본인이 가장 자신 있는 프로젝트와 그 안에서 맡은 역할을 설명해 주세요.",
             "캐시나 인덱스를 사용해 성능을 개선해 본 경험이 있다면 구체적으로 말씀해 주세요.",
             "팀 안에서 의견이 충돌했을 때 어떻게 해결했는지 사례를 들어 설명해 주세요."]


def _sine_pcm(seconds: float, hz: int = 220) -> bytes:
    return b"".join(struct.pack("<h", int(2500 * math.sin(2 * math.pi * hz * i / 16000))) for i in range(int(16000 * seconds)))


async def seed(url: str, media_root: Path, *, demo_admin: bool = False, manual_questions: int = len(QUESTIONS), coding_job: bool = False) -> dict:
    engine, sm = create_db(url)
    out: dict = {}
    async with sm() as s:
        if (await s.execute(select(User.id).where(User.email == "hr@corp.local"))).first():
            await engine.dispose()
            return {"skipped": True}
        co = Company(name="다온커머스")
        s.add(co)
        await s.flush()
        hr = User(email="hr@corp.local", password_hash=hash_password(PASSWORD), role=UserRole.RECRUITER, company_id=co.id, name="박담당")
        applicant = User(email="applicant@corp.local", password_hash=hash_password(PASSWORD), role=UserRole.APPLICANT, name="김지원")
        s.add_all([hr, applicant])
        job = JobPosting(company_id=co.id, title="백엔드 개발자 (신입)", job_category="개발", status=JobStatus.OPEN, deadline_at=utcnow() + timedelta(days=5),
                         duties="주문·결제 API 설계와 개발, 성능 개선", requirements="Java 또는 Kotlin, RDBMS, 캐시(Redis) 사용 경험", preferred="대용량 트래픽 경험",
                         headcount=2, answer_time_limit_sec=60, coding_test_enabled=False)
        s.add(job)
        await s.flush()
        s.add_all([FollowupRule(job_id=job.id, max_followups=1), EvalWeight(job_id=job.id)])
        s.add_all([JobQuestion(job_id=job.id, source=QuestionSource.MANUAL, text=q, order_no=i + 1) for i, q in enumerate(QUESTIONS[:manual_questions])])
        out.update(company_id=str(co.id), job_id=str(job.id), applicant_id=str(applicant.id), recruiter_id=str(hr.id))
        if coding_job:  # 코딩테스트 E2E 용: 코딩테스트가 켜진 공고 (SANDBOX_ENABLED 스택에서만 의미가 있다)
            cj = JobPosting(company_id=co.id, title="알고리즘 엔지니어 (코딩테스트 포함)", job_category="개발", status=JobStatus.OPEN, deadline_at=utcnow() + timedelta(days=6),
                            duties="알고리즘 설계와 구현", requirements="Python 또는 Java, 자료구조", headcount=1, answer_time_limit_sec=60,
                            coding_test_enabled=True, coding_test_time_limit_sec=1800)
            s.add(cj)
            await s.flush()
            s.add_all([FollowupRule(job_id=cj.id, max_followups=1), EvalWeight(job_id=cj.id, concept_understanding=20, logic=20, delivery=10, attitude=10, job_expertise=10, code_quality=30)])
            s.add_all([JobQuestion(job_id=cj.id, source=QuestionSource.MANUAL, text=q, order_no=i + 1) for i, q in enumerate(QUESTIONS)])
            out["coding_job_id"] = str(cj.id)

        if demo_admin:  # 관리자 화면 확인용: 면접을 마친 지원자 3명 (음성·시선·하이라이트 포함). 마지막 1명은 리포트 생성 중
            store = MediaStore(media_root)
            demos = (("이도윤", 82.5, AiPassPrediction.LIKELY_PASS, ReportStatus.DONE), ("최서연", 61.0, AiPassPrediction.BORDERLINE, ReportStatus.DONE),
                     ("정하늘", None, AiPassPrediction.UNAVAILABLE, ReportStatus.RUNNING))
            for i, (name, score, pred, rstatus) in enumerate(demos):
                u = User(email=f"demo{i}@corp.local", password_hash=hash_password(PASSWORD), role=UserRole.APPLICANT, name=name)
                s.add(u)
                await s.flush()
                done = rstatus == ReportStatus.DONE
                app = Application(user_id=u.id, job_id=job.id, consent_at=utcnow(), ai_total_score=score, ai_pass_prediction=pred,
                                  status=ApplicationStatus.REPORT_READY if done else ApplicationStatus.INTERVIEW_DONE)
                s.add(app)
                await s.flush()
                sess = InterviewSession(application_id=app.id, state=SessionState.FINISHED, started_at=utcnow() - timedelta(hours=i + 1),
                                        ended_at=utcnow() - timedelta(minutes=30 * (i + 1)))
                s.add(sess)
                await s.flush()
                rep = EvaluationReport(session_id=sess.id, status=rstatus, total_score=score, gaze_away_ratio=0.04 + 0.03 * i if done else None,
                                       summary="결제 모듈 경험을 구체적으로 설명했으나 협업 사례는 보완이 필요합니다." if done else None,
                                       strengths=[{"rank": 1, "title": "정량적 성과 제시", "detail": "응답 시간 개선을 수치로 설명했습니다.", "evidence": [{"source": "answer", "ref": "seed", "quote": "결제 모듈을 맡아 장애를 줄였습니다."}]}] if done else None,
                                       improvements=[{"rank": 1, "title": "협업 경험 구체화", "detail": "팀 내 역할을 더 구체적으로 말해 보세요.", "evidence": []}] if done else None)
                s.add(rep)
                await s.flush()
                t = InterviewTurn(session_id=sess.id, turn_no=1, kind=TurnKind.MAIN, main_index=0, question_text=QUESTIONS[0],
                                  answer_text="결제 모듈을 맡아 장애를 줄였습니다.", answer_duration_ms=6000)
                s.add(t)
                await s.flush()
                s.add(GazeEvent(session_id=sess.id, turn_id=t.id, kind=GazeKind.GAZE_AWAY, start_ms=1500, end_ms=3200, occurred_at=utcnow()))
                if done:
                    for c, base in (("concept_understanding", 0), ("logic", -4), ("delivery", 3), ("attitude", -2), ("job_expertise", 5)):
                        s.add(ReportScore(report_id=rep.id, turn_id=None, criterion=Criterion(c), score=round(min(100, max(0, (score or 0) + base - 5 * i)), 1)))
                        s.add(ReportScore(report_id=rep.id, turn_id=t.id, criterion=Criterion(c), score=round(min(100, (score or 0) + base), 1), comment="질문에 맞게 설명했습니다.",
                                          evidence=[{"source": "answer", "ref": f"turn:{t.id}", "quote": "결제 모듈을 맡아 장애를 줄였습니다."}]))
                    words = [{"w": "결제", "s": 0.2, "e": 0.7, "p": 0.95}, {"w": "모듈을", "s": 0.8, "e": 1.4, "p": 0.9}]
                    s.add_all([VoiceTimeline(turn_id=t.id, start_ms=0, end_ms=1500, kind=TimelineKind.SPEECH, text="결제 모듈을", words=words),
                               VoiceTimeline(turn_id=t.id, start_ms=2000, end_ms=3500, kind=TimelineKind.HIGHLIGHT_BAD, text="음… 잘 기억이 안 나는데",
                                             ai_comment="구체적인 수치 없이 모호하게 답했습니다.", severity=2),
                               VoiceTimeline(turn_id=t.id, start_ms=4000, end_ms=5500, kind=TimelineKind.HIGHLIGHT_GOOD, text="응답 시간을 40% 줄였습니다",
                                             ai_comment="정량적 성과를 근거와 함께 제시했습니다.")])
                rec = store.open_answer(sess.id, t.id)
                rec.append(_sine_pcm(6.0))
                rec.close()
        await s.commit()
    await engine.dispose()
    return out


if __name__ == "__main__":
    from app.core.config import DatabaseSettings, Settings

    from app.core.crypto import init_crypto

    settings = Settings()  # type: ignore[call-arg]
    init_crypto(settings.data_encryption_key)  # PII 암호화 컬럼에 쓰려면 API 와 같은 키가 필요하다
    db_url = DatabaseSettings().database_url
    media = settings.media_root
    print(asyncio.run(seed(db_url, media, demo_admin="--demo-admin" in sys.argv)))
