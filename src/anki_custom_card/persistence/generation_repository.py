from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from anki_custom_card.generation.ports import GeneratedOutput
from anki_custom_card.generation.schemas import CardDraft, DictionaryOutput
from anki_custom_card.persistence.models import Artifact, Draft, GenerationJob


class GenerationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(self, input_word: str, language: str, *, now: datetime) -> GenerationJob:
        job = GenerationJob(input_word=input_word, language=language, provider_config={})
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: str) -> GenerationJob:
        job = self.session.get(GenerationJob, job_id)
        if job is None:
            raise LookupError(f"Generation job {job_id} does not exist")
        return job

    def load_dictionary_output(self, job_id: str) -> DictionaryOutput | None:
        artifact = self.session.scalar(
            select(Artifact).where(
                Artifact.generation_job_id == job_id,
                Artifact.artifact_type == "dictionary_output",
            )
        )
        if artifact is None or artifact.structured_content is None:
            return None
        return DictionaryOutput.model_validate(artifact.structured_content)

    def load_draft(self, job_id: str) -> CardDraft | None:
        draft = self.session.scalar(select(Draft).where(Draft.generation_job_id == job_id))
        if draft is None:
            return None
        return CardDraft.model_validate(draft.content)

    def save_dictionary_output(
        self,
        job_id: str,
        output: GeneratedOutput[DictionaryOutput],
        *,
        provider: str,
        prompt_version: str,
        dictionary_cache_id: str,
    ) -> None:
        self.session.add(
            Artifact(
                generation_job_id=job_id,
                dictionary_cache_id=dictionary_cache_id,
                artifact_type="dictionary_output",
                provider=provider,
                provider_response_id=output.response_id,
                model=output.model,
                prompt_version=prompt_version,
                structured_content=output.content.model_dump(mode="json", by_alias=True),
                raw_content=output.raw_response,
            )
        )
        self.session.flush()

    def save_card_output(
        self,
        job_id: str,
        output: GeneratedOutput[CardDraft],
        *,
        provider: str,
        prompt_version: str,
        now: datetime,
    ) -> Draft:
        self.session.add(
            Artifact(
                generation_job_id=job_id,
                artifact_type="card_output",
                provider=provider,
                provider_response_id=output.response_id,
                model=output.model,
                prompt_version=prompt_version,
                structured_content=output.content.model_dump(mode="json", by_alias=True),
                raw_content=output.raw_response,
            )
        )
        draft = Draft(
            generation_job_id=job_id,
            content=output.content.model_dump(mode="json", by_alias=True),
        )
        self.session.add(draft)
        job = self.get_job(job_id)
        job.status = "succeeded"
        job.error_code = None
        job.error_message = None
        job.finished_at = now
        self.session.flush()
        return draft

    def mark_running(self, job_id: str, *, now: datetime) -> None:
        job = self.get_job(job_id)
        job.status = "running"
        job.started_at = job.started_at or now
        job.finished_at = None
        job.error_code = None
        job.error_message = None

    def mark_failed(self, job_id: str, error: Exception, *, now: datetime) -> None:
        job = self.get_job(job_id)
        job.status = "failed"
        job.error_code = getattr(error, "code", "generation_failed")
        job.error_message = str(error)
        job.finished_at = now

    def mark_succeeded(self, job_id: str, *, now: datetime) -> None:
        job = self.get_job(job_id)
        job.status = "succeeded"
        job.error_code = None
        job.error_message = None
        job.finished_at = now
