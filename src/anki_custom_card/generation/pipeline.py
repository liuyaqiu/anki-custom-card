from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from anki_custom_card.domain.words import normalize_english_word
from anki_custom_card.generation.cache_keys import DictionaryCacheIdentity
from anki_custom_card.generation.ports import CardComposer, DictionaryProvider, GeneratedOutput
from anki_custom_card.generation.schemas import CardDraft, DictionaryOutput, DictionaryQuery
from anki_custom_card.generation.speech import SpeechGenerator
from anki_custom_card.persistence.dictionary_cache_repository import DictionaryCacheRepository
from anki_custom_card.persistence.generation_repository import GenerationRepository


class GenerationPipeline:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        dictionary_provider: DictionaryProvider,
        card_composer: CardComposer,
        speech_service: SpeechGenerator | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.dictionary_provider = dictionary_provider
        self.card_composer = card_composer
        self.speech_service = speech_service

    async def run(self, job_id: str, *, word_idx: int, domain: str, now: datetime) -> CardDraft:
        with self.session_factory() as session:
            repository = GenerationRepository(session)
            existing_draft = repository.load_draft(job_id)
            if existing_draft is None:
                repository.mark_running(job_id, now=now)
                job = repository.get_job(job_id)
                query = DictionaryQuery(
                    word=job.input_word,
                    normalized_word=normalize_english_word(job.input_word),
                    language=job.language,
                )
                dictionary_output = repository.load_dictionary_output(job_id)
            session.commit()

        if existing_draft is not None:
            return await self._generate_speech(job_id, existing_draft, now)

        try:
            if dictionary_output is None:
                dictionary_output = await self._obtain_dictionary(job_id, query, now)
            card_result = await self.card_composer.compose(
                dictionary_output, word_idx=word_idx, domain=domain
            )
            self._validate_card(dictionary_output, card_result.content, word_idx)
        except Exception as error:
            with self.session_factory() as session:
                GenerationRepository(session).mark_failed(job_id, error, now=now)
                session.commit()
            raise

        with self.session_factory() as session:
            draft = GenerationRepository(session).save_card_output(
                job_id,
                card_result,
                provider=self.card_composer.provider_name,
                prompt_version=self.card_composer.prompt_version,
                now=now,
            )
            content = CardDraft.model_validate(draft.content)
            session.commit()
        return await self._generate_speech(job_id, content, now)

    async def _generate_speech(self, job_id: str, draft: CardDraft, now: datetime) -> CardDraft:
        if self.speech_service is None:
            return draft
        try:
            await self.speech_service.generate(
                job_id, "word_audio", draft.speech.word_text, now=now
            )
            await self.speech_service.generate(
                job_id, "example_audio", draft.speech.example_text, now=now
            )
        except Exception as error:
            with self.session_factory() as session:
                GenerationRepository(session).mark_failed(job_id, error, now=now)
                session.commit()
            raise
        with self.session_factory() as session:
            GenerationRepository(session).mark_succeeded(job_id, now=now)
            session.commit()
        return draft

    async def _obtain_dictionary(
        self, job_id: str, query: DictionaryQuery, now: datetime
    ) -> DictionaryOutput:
        identity = DictionaryCacheIdentity(
            provider=self.dictionary_provider.provider_name,
            provider_dataset=self.dictionary_provider.provider_dataset,
            normalized_query=query.model_dump(mode="json"),
            provider_config_version=self.dictionary_provider.provider_config_version,
            prompt_version=self.dictionary_provider.prompt_version,
            schema_version=self.dictionary_provider.schema_version,
            model=self.dictionary_provider.model,
        )
        with self.session_factory() as session:
            cached = DictionaryCacheRepository(session).get(identity.request_key)
            if cached is not None:
                output = DictionaryOutput.model_validate(cached.response_payload)
                cached_result = GeneratedOutput(
                    content=output,
                    response_id="cache-hit",
                    model=cached.model or self.dictionary_provider.model,
                    raw_response="cache-hit",
                )
                GenerationRepository(session).save_dictionary_output(
                    job_id,
                    cached_result,
                    provider=cached.provider,
                    prompt_version=cached.prompt_version or "unknown",
                    dictionary_cache_id=cached.id,
                )
                session.commit()
                return output

        result = await self.dictionary_provider.lookup(query)
        with self.session_factory() as session:
            cache = DictionaryCacheRepository(session).put(
                identity,
                result.content.model_dump(mode="json", by_alias=True),
                source_entry_ids=[
                    sense.sense_id for entry in result.content.entries for sense in entry.senses
                ],
                now=now,
            )
            GenerationRepository(session).save_dictionary_output(
                job_id,
                result,
                provider=self.dictionary_provider.provider_name,
                prompt_version=self.dictionary_provider.prompt_version,
                dictionary_cache_id=cache.id,
            )
            session.commit()
        return result.content

    @staticmethod
    def _validate_card(
        dictionary_output: DictionaryOutput, card: CardDraft, expected_word_idx: int
    ) -> None:
        available_senses = {
            sense.sense_id for entry in dictionary_output.entries for sense in entry.senses
        }
        if card.word_idx != expected_word_idx:
            raise ValueError("CardDraft word_idx does not match the generation request")
        if not set(card.selected_sense_ids) <= available_senses:
            raise ValueError("CardDraft references unknown dictionary sense IDs")
