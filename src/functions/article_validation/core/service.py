"""Article validation orchestration service."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from src.shared.db import SupabaseConfig as SharedSupabaseConfig
from src.shared.db import get_supabase_client
from src.shared.utils.env import get_env
from src.shared.utils.logging import get_logger

from .config import LLMConfig, SupabaseConfig, ValidationConfig
from .contracts import ValidationRequest, ValidationReport
from .contracts.validation_report import ValidationDimension, ValidationIssue
from .contracts.validation_standards import ValidationStandards
from .llm import GeminiClient, GeminiClientError
from .processors import (
    ContextValidator,
    DecisionEngine,
    FactChecker,
    QualityValidator,
    resolve_quality_standards,
)


@dataclass
class ArticleValidationService:
    """Coordinates fact, context, and quality validation for articles."""

    request: ValidationRequest

    def __post_init__(self) -> None:
        self._logger = get_logger(__name__)
        self._validation_config = self._ensure_validation_config()
        self._llm_client = GeminiClient(self._ensure_llm_config())
        self._fact_checker = FactChecker(self._llm_client)
        self._context_validator = ContextValidator(self._llm_client)
        self._quality_validator = QualityValidator(self._llm_client)
        self._decision_engine = DecisionEngine(self._validation_config)
        self._supabase_config = self.request.supabase_config
        self._supabase_client = self._initialise_supabase_client(self._supabase_config)

    async def validate(self) -> ValidationReport:
        start_time = time.perf_counter()
        try:
            standards = self._resolve_standards()
            dimensions, timed_out = await self._run_validation_dimensions(standards)
            factual = dimensions.get("factual", self._disabled_dimension(enabled=False))
            contextual = dimensions.get(
                "contextual",
                self._disabled_dimension(enabled=False),
            )
            quality = dimensions.get("quality", self._disabled_dimension(enabled=False))

            decision, is_releasable, rejection_reasons, review_reasons = (
                self._decision_engine.make_decision(factual, contextual, quality)
            )

            status = "partial" if timed_out else "success"
            if timed_out:
                review_reasons = list(dict.fromkeys(
                    list(review_reasons)
                    + ["Validation timed out before all checks completed."]
                ))
                is_releasable = False
                if decision == "release":
                    decision = "review_required"

            report = ValidationReport(
                status=status,
                decision=decision,
                is_releasable=is_releasable,
                factual=factual,
                contextual=contextual,
                quality=quality,
                rejection_reasons=rejection_reasons,
                review_reasons=review_reasons,
                article_type=self.request.article_type,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.exception("Validation failed unexpectedly")
            report = self._error_report(str(exc))

        report.processing_time_ms = int((time.perf_counter() - start_time) * 1000)

        if self._supabase_client and self._supabase_config and report.status != "error":
            await self._store_report(report)

        return report

    def _ensure_llm_config(self) -> LLMConfig:
        if self.request.llm_config:
            self.request.llm_config.validate()
            return self.request.llm_config

        api_key = (
            get_env("GEMINI_API_KEY")
            or get_env("GOOGLE_API_KEY")
            or get_env("OPENAI_API_KEY")
        )
        if not api_key:
            raise ValueError(
                "Gemini API key must be provided via request or GEMINI_API_KEY/GOOGLE_API_KEY env"
            )

        config = LLMConfig(api_key=api_key)

        model = (
            get_env("GEMINI_MODEL")
            or get_env("GOOGLE_MODEL")
            or get_env("OPENAI_MODEL")
        )
        if model:
            config.model = model

        enable_web_search = (
            get_env("GEMINI_ENABLE_WEB_SEARCH")
            or get_env("GOOGLE_ENABLE_WEB_SEARCH")
            or get_env("OPENAI_ENABLE_WEB_SEARCH")
        )
        if enable_web_search is not None:
            lowered = enable_web_search.strip().lower()
            if lowered in {"true", "1", "yes"}:
                config.enable_web_search = True
            elif lowered in {"false", "0", "no"}:
                config.enable_web_search = False
            else:
                raise ValueError("llm.enable_web_search must be boolean-like")

        timeout_seconds = (
            get_env("GEMINI_TIMEOUT_SECONDS")
            or get_env("GOOGLE_TIMEOUT_SECONDS")
            or get_env("OPENAI_TIMEOUT_SECONDS")
        )
        if timeout_seconds is not None:
            try:
                config.timeout_seconds = int(timeout_seconds)
            except ValueError as exc:
                raise ValueError("llm.timeout_seconds must be an integer") from exc

        config.validate()
        return config

    def _ensure_validation_config(self) -> ValidationConfig:
        if self.request.validation_config:
            return self.request.validation_config

        config = ValidationConfig()
        config.validate()
        return config

    def _initialise_supabase_client(
        self,
        config: Optional[SupabaseConfig],
    ):
        if not config:
            return None

        try:
            shared_config = SharedSupabaseConfig(
                url=config.url,
                key=config.key,
                schema=config.schema or "public",
            )
            return get_supabase_client(shared_config)
        except Exception as exc:  # pragma: no cover - best effort
            self._logger.warning("Failed to initialise Supabase client: %s", exc)
            return None

    async def _run_validation_dimensions(
        self,
        standards: ValidationStandards,
    ) -> Tuple[Dict[str, ValidationDimension], bool]:
        dimensions: Dict[str, ValidationDimension] = {}
        tasks: Dict[str, asyncio.Task[ValidationDimension]] = {}

        if self._validation_config.enable_factual:
            tasks["factual"] = asyncio.create_task(self._run_factual_validation())
        else:
            dimensions["factual"] = self._disabled_dimension(enabled=False)

        if self._validation_config.enable_contextual:
            tasks["contextual"] = asyncio.create_task(
                self._run_contextual_validation(standards.to_dict())
            )
        else:
            dimensions["contextual"] = self._disabled_dimension(enabled=False)

        if self._validation_config.enable_quality:
            tasks["quality"] = asyncio.create_task(
                self._run_quality_validation(standards)
            )
        else:
            dimensions["quality"] = self._disabled_dimension(enabled=False)

        if not tasks:
            return dimensions, False

        timeout_seconds = self._validation_config.timeout_seconds
        done, pending = await asyncio.wait(
            tasks.values(),
            timeout=timeout_seconds,
            return_when=asyncio.ALL_COMPLETED,
        )

        timed_out = bool(pending)
        if pending:
            pending_tasks = list(pending)
            for task in pending_tasks:
                task.cancel()
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        for name, task in tasks.items():
            if task in done and not task.cancelled():
                try:
                    dimensions[name] = task.result()
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.exception("%s validation failed", name)
                    dimensions[name] = self._dimension_error(
                        name,
                        "Validation failed due to internal error.",
                        severity="critical",
                    )
            else:
                dimensions[name] = self._timeout_dimension(name)

        return dimensions, timed_out

    async def _run_factual_validation(self) -> ValidationDimension:
        try:
            return await self._fact_checker.verify_facts(
                self.request.article,
                team_context=self.request.team_context,
                source_summaries=self.request.source_summaries,
            )
        except GeminiClientError as exc:
            self._logger.warning("Factual validation encountered client error: %s", exc)
            return self._dimension_error(
                "factual",
                "Factual validation could not complete due to LLM error.",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.exception("Factual validation failed")
            return self._dimension_error(
                "factual",
                "Factual validation failed due to internal error.",
                severity="critical",
            )

    async def _run_contextual_validation(
        self,
        standards_payload: Dict[str, Any],
    ) -> ValidationDimension:
        try:
            return await self._context_validator.validate_context(
                self.request.article,
                team_context=self.request.team_context,
                standards=standards_payload,
            )
        except GeminiClientError as exc:
            self._logger.warning("Contextual validation encountered client error: %s", exc)
            return self._dimension_error(
                "contextual",
                "Contextual validation could not complete due to LLM error.",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.exception("Contextual validation failed")
            return self._dimension_error(
                "contextual",
                "Contextual validation failed due to internal error.",
                severity="critical",
            )

    async def _run_quality_validation(
        self,
        standards: ValidationStandards,
    ) -> ValidationDimension:
        try:
            return await self._quality_validator.validate_quality(
                self.request.article,
                standards=standards,
                article_type=self.request.article_type,
            )
        except GeminiClientError as exc:
            self._logger.warning("Quality validation encountered client error: %s", exc)
            return self._dimension_error(
                "quality",
                "Quality validation could not complete due to LLM error.",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.exception("Quality validation failed")
            return self._dimension_error(
                "quality",
                "Quality validation failed due to internal error.",
                severity="critical",
            )

    def _resolve_standards(self) -> ValidationStandards:
        if self.request.quality_standards is not None:
            return resolve_quality_standards(
                self.request.article_type,
                override=self.request.quality_standards,
            )
        return resolve_quality_standards(self.request.article_type)

    async def _store_report(self, report: ValidationReport) -> None:
        if not self._supabase_client or not self._supabase_config:
            return

        payload = self._serialise_report_for_storage(report)

        try:
            await asyncio.to_thread(self._insert_report, payload)
        except Exception as exc:  # pragma: no cover - best effort
            self._logger.warning("Failed to store validation report: %s", exc)

    def _insert_report(self, payload: Dict[str, Any]) -> None:
        self._supabase_client.table(self._supabase_config.table).insert(payload).execute()

    def _serialise_report_for_storage(self, report: ValidationReport) -> Dict[str, Any]:
        return report.to_dict()

    def _disabled_dimension(self, *, enabled: bool) -> ValidationDimension:
        return ValidationDimension(
            enabled=enabled,
            score=1.0 if not enabled else 0.0,
            confidence=1.0 if not enabled else 0.0,
            passed=not enabled,
            issues=[],
            details={"status": "disabled"} if not enabled else {},
        )

    def _timeout_dimension(self, name: str) -> ValidationDimension:
        return ValidationDimension(
            enabled=True,
            score=0.0,
            confidence=0.0,
            passed=False,
            issues=[
                ValidationIssue(
                    severity="warning",
                    category=name,
                    message="Validation timed out before completion.",
                )
            ],
            details={"status": "timeout"},
        )

    def _dimension_error(
        self,
        name: str,
        message: str,
        *,
        severity: str = "warning",
    ) -> ValidationDimension:
        return ValidationDimension(
            enabled=True,
            score=0.0,
            confidence=0.0,
            passed=False,
            issues=[
                ValidationIssue(
                    severity=severity,
                    category=name,
                    message=message,
                )
            ],
            details={"status": "error"},
        )

    def _error_report(self, error_message: str) -> ValidationReport:
        return ValidationReport(
            status="error",
            decision="review_required",
            is_releasable=False,
            factual=self._dimension_error(
                "factual",
                "Validation failed before factual checks could run.",
                severity="critical",
            ),
            contextual=self._dimension_error(
                "contextual",
                "Validation failed before contextual checks could run.",
                severity="critical",
            ),
            quality=self._dimension_error(
                "quality",
                "Validation failed before quality checks could run.",
                severity="critical",
            ),
            rejection_reasons=["Validation encountered an unexpected error."],
            review_reasons=[],
            article_type=self.request.article_type,
            error=error_message,
        )
