"""Command-line tool for exercising the article validation pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.db import SupabaseConfig as SharedSupabaseConfig
from src.shared.db import get_supabase_client
from src.shared.utils.env import get_env, load_env
from src.shared.utils.logging import get_logger, setup_logging

from src.functions.article_validation.core.factory import request_from_payload
from src.functions.article_validation.core.service import ArticleValidationService

LOGGER = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run article validation against generated content.",
    )

    parser.add_argument(
        "--payload",
        type=Path,
        help="Path to JSON document containing a full validation payload.",
    )

    article_group = parser.add_mutually_exclusive_group()
    article_group.add_argument(
        "--article-file",
        type=Path,
        help="JSON file containing the article payload (merged into the request).",
    )
    article_group.add_argument(
        "--article-inline",
        help="Inline JSON string for the article payload.",
    )
    article_group.add_argument(
        "--db-team-article",
        help="Supabase team_article row ID to fetch and validate (requires Supabase credentials).",
    )

    parser.add_argument(
        "--article-type",
        help="Article type identifier (defaults to payload value if present).",
    )

    parser.add_argument(
        "--db-team-table",
        help="Supabase table to query when using --db-team-article (default: team_article).",
    )
    parser.add_argument(
        "--teams-table",
        help="Supabase table containing team metadata for context enrichment (default: teams).",
    )

    team_group = parser.add_mutually_exclusive_group()
    team_group.add_argument(
        "--team-context-file",
        type=Path,
        help="JSON file containing team context metadata.",
    )
    team_group.add_argument(
        "--team-context-inline",
        help="Inline JSON string with team context metadata.",
    )

    parser.add_argument(
        "--source-summaries-file",
        type=Path,
        help="JSON file containing a list of source summaries.",
    )
    parser.add_argument(
        "--source-summary",
        action="append",
        help="Add an individual source summary (may be supplied multiple times).",
    )

    parser.add_argument(
        "--quality-standards-file",
        type=Path,
        help="JSON file with validation quality standards to override defaults.",
    )
    parser.add_argument(
        "--quality-standards-inline",
        help="Inline JSON for quality standards override.",
    )

    parser.add_argument(
        "--validation-config-file",
        type=Path,
        help="JSON file with validation configuration overrides.",
    )
    parser.add_argument(
        "--validation-config-inline",
        help="Inline JSON for validation configuration overrides.",
    )

    parser.add_argument(
        "--standards-file",
        type=Path,
        help="JSON file containing validation standards bundle (quality rules and optional overrides).",
    )
    parser.add_argument(
        "--standards-inline",
        help="Inline JSON string for validation standards bundle overrides.",
    )

    parser.add_argument(
        "--llm-config-file",
        type=Path,
        help="JSON file with LLM configuration overrides (api_key, model, etc.).",
    )
    parser.add_argument(
        "--llm-config-inline",
        help="Inline JSON for LLM configuration overrides.",
    )
    parser.add_argument(
        "--model",
        help="Override the LLM model used during validation.",
    )
    parser.add_argument(
        "--enable-web-search",
        help="Enable or disable web search support for the LLM (accepts true/false).",
    )
    parser.add_argument(
        "--llm-timeout-seconds",
        type=int,
        help="Override LLM request timeout in seconds.",
    )

    parser.add_argument(
        "--supabase-config-file",
        type=Path,
        help="JSON file with Supabase configuration block (url, key, table).",
    )
    parser.add_argument(
        "--supabase-config-inline",
        help="Inline JSON for Supabase configuration block.",
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional .env file to load before validation.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level for the CLI (default: INFO).",
    )
    parser.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Disable timestamps in log output.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Write the validation report JSON to this file instead of stdout.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a condensed summary alongside the full report.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout output when --output is used (except summaries).",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(level=args.log_level, include_timestamp=not args.no_timestamp)
    LOGGER.debug("Arguments parsed", extra={"args": vars(args)})

    if args.env_file:
        load_env(str(args.env_file))
    else:
        load_env()

    try:
        payload = _assemble_payload(args)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        request = request_from_payload(payload)
    except Exception as exc:  # pragma: no cover - defensive
        parser.error(f"Failed to build validation request: {exc}")

    report = asyncio.run(ArticleValidationService(request).validate())
    _emit_output(report, args)
    return 0


# ---------------------------------------------------------------------------
# Payload assembly helpers
# ---------------------------------------------------------------------------

def _assemble_payload(args: argparse.Namespace) -> Dict[str, Any]:
    base_payload: Dict[str, Any] = {}
    if args.payload:
        base_payload = _ensure_mapping(_load_json_file(args.payload, "--payload"), "--payload")

    payload = dict(base_payload)

    standards_bundle = _resolve_mapping_input(
        args.standards_file,
        args.standards_inline,
        "--standards",
    )
    if standards_bundle is not None:
        _apply_standards_bundle(payload, standards_bundle)

    supabase_config = _resolve_supabase_config(payload, args)

    if args.db_team_article:
        article_payload, derived_context = _load_article_from_database(
            args.db_team_article,
            supabase_config,
            args.db_team_table,
            args.teams_table,
        )
        payload["article"] = article_payload
        if derived_context and not payload.get("team_context"):
            payload["team_context"] = derived_context
        payload.setdefault("article_type", "team_article")

    article_payload = _resolve_mapping_input(
        args.article_file,
        args.article_inline,
        "--article",
    )
    if article_payload is not None:
        payload["article"] = article_payload

    if "article" not in payload:
        raise ValueError("Article content is required. Provide --payload, database id, file, or inline payload.")

    article_type = args.article_type or payload.get("article_type")
    if article_type:
        payload["article_type"] = str(article_type).strip()
    if not payload.get("article_type"):
        raise ValueError("article_type must be supplied via --article-type or within the payload.")

    team_context = _resolve_mapping_input(
        args.team_context_file,
        args.team_context_inline,
        "--team-context",
    )
    if team_context is not None:
        payload["team_context"] = team_context

    quality_standards = _resolve_mapping_input(
        args.quality_standards_file,
        args.quality_standards_inline,
        "--quality-standards",
    )
    if quality_standards is not None:
        payload["quality_standards"] = quality_standards

    validation_config = _resolve_mapping_input(
        args.validation_config_file,
        args.validation_config_inline,
        "--validation-config",
    )
    if validation_config is not None:
        current_validation = (
            _ensure_mapping(payload["validation_config"], "payload.validation_config")
            if "validation_config" in payload
            else {}
        )
        current_validation.update(validation_config)
        payload["validation_config"] = current_validation

    llm_config = _resolve_mapping_input(
        args.llm_config_file,
        args.llm_config_inline,
        "--llm-config",
    )
    llm_overrides = _build_llm_overrides(args)

    llm_payload: Dict[str, Any] = {}
    if "llm" in payload:
        llm_payload.update(_ensure_mapping(payload["llm"], "payload.llm"))
    if llm_config is not None:
        llm_payload.update(llm_config)
    if llm_overrides:
        llm_payload.update(llm_overrides)
    if llm_payload:
        payload["llm"] = llm_payload
    else:
        payload.pop("llm", None)

    if supabase_config is not None:
        payload["supabase"] = supabase_config
    else:
        payload.pop("supabase", None)

    payload["source_summaries"] = _collect_source_summaries(payload, args)
    if not payload["source_summaries"]:
        payload.pop("source_summaries", None)

    return payload


def _resolve_supabase_config(
    payload: MutableMapping[str, Any],
    args: argparse.Namespace,
) -> Optional[MutableMapping[str, Any]]:
    existing: Optional[MutableMapping[str, Any]] = None
    if "supabase" in payload:
        existing = _ensure_mapping(payload["supabase"], "payload.supabase")

    override = _resolve_mapping_input(
        args.supabase_config_file,
        args.supabase_config_inline,
        "--supabase-config",
    )

    if override is not None:
        payload["supabase"] = override
        return override
    if existing is not None:
        payload["supabase"] = existing
    return existing


def _resolve_mapping_input(
    file_path: Optional[Path],
    inline_json: Optional[str],
    label: str,
) -> Optional[MutableMapping[str, Any]]:
    data: Optional[MutableMapping[str, Any]] = None
    if file_path:
        data = _ensure_mapping(_load_json_file(file_path, label), label)
    if inline_json:
        data = _ensure_mapping(_parse_json_string(inline_json, label), label)
    return data


def _collect_source_summaries(
    payload: Mapping[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    summaries: list[str] = []

    if "source_summaries" in payload:
        try:
            summaries.extend(_coerce_string_list(payload["source_summaries"], "payload.source_summaries"))
        except ValueError as exc:
            raise ValueError(str(exc))

    if args.source_summaries_file:
        file_data = _load_json_file(args.source_summaries_file, "--source-summaries-file")
        summaries.extend(_coerce_string_list(file_data, "--source-summaries-file"))

    if args.source_summary:
        for entry in args.source_summary:
            if entry is None:
                continue
            text = entry.strip()
            if text:
                summaries.append(text)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for item in summaries:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _apply_standards_bundle(
    payload: MutableMapping[str, Any],
    bundle: MutableMapping[str, Any],
) -> None:
    data = dict(bundle)

    quality_payload: Optional[MutableMapping[str, Any]] = None
    if "quality_standards" in data and isinstance(data["quality_standards"], Mapping):
        quality_payload = _ensure_mapping(data["quality_standards"], "standards.quality_standards")
    elif _looks_like_standards(data):
        quality_payload = _ensure_mapping(data, "standards.quality_standards")

    if quality_payload is not None and "quality_standards" not in payload:
        payload["quality_standards"] = quality_payload
        article_type = quality_payload.get("article_type") if isinstance(quality_payload, Mapping) else None
        if article_type and "article_type" not in payload:
            payload["article_type"] = article_type

    if "article_type" not in payload and isinstance(data.get("article_type"), str):
        payload["article_type"] = data["article_type"].strip()

    if "validation_config" not in payload and isinstance(data.get("validation_config"), Mapping):
        payload["validation_config"] = _ensure_mapping(data["validation_config"], "standards.validation_config")

    if "llm" not in payload and isinstance(data.get("llm"), Mapping):
        payload["llm"] = _ensure_mapping(data["llm"], "standards.llm")

    if "supabase" not in payload and isinstance(data.get("supabase"), Mapping):
        payload["supabase"] = _ensure_mapping(data["supabase"], "standards.supabase")

    if "team_context" not in payload and isinstance(data.get("team_context"), Mapping):
        payload["team_context"] = _ensure_mapping(data["team_context"], "standards.team_context")

    if "source_summaries" not in payload and data.get("source_summaries") is not None:
        payload["source_summaries"] = data["source_summaries"]


def _looks_like_standards(candidate: Mapping[str, Any]) -> bool:
    indicator_keys = {"quality_rules", "contextual_requirements", "factual_verification"}
    return any(key in candidate for key in indicator_keys)


def _build_llm_overrides(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    overrides: Dict[str, Any] = {}

    if args.model:
        model = args.model.strip()
        if model:
            overrides["model"] = model

    if args.enable_web_search is not None:
        value = args.enable_web_search.strip().lower()
        truthy = {"true", "1", "yes", "on"}
        falsy = {"false", "0", "no", "off"}
        if value in truthy:
            overrides["enable_web_search"] = True
        elif value in falsy:
            overrides["enable_web_search"] = False
        else:
            raise ValueError("--enable-web-search must be one of true/false/yes/no/1/0")

    if args.llm_timeout_seconds is not None:
        overrides["timeout_seconds"] = int(args.llm_timeout_seconds)

    return overrides or None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _enrich_team_context(
    client,
    article_record: Mapping[str, Any],
    base_context: Optional[MutableMapping[str, Any]],
    teams_table_override: Optional[str],
) -> Optional[MutableMapping[str, Any]]:
    if client is None:
        return base_context

    teams_table = teams_table_override or get_env("TEAM_METADATA_TABLE", "teams")
    if not teams_table:
        return base_context

    candidate_abbrs: list[str] = []
    candidate_slugs: list[str] = []

    def _add_abbr(value: Any) -> None:
        text = _clean_string(value)
        if text:
            upper = text.upper()
            if upper not in candidate_abbrs:
                candidate_abbrs.append(upper)

    def _add_slug(value: Any) -> None:
        text = _clean_string(value)
        if text:
            lower = text.lower()
            if lower not in candidate_slugs:
                candidate_slugs.append(lower)

    _add_abbr(article_record.get("team_abbr"))
    _add_abbr(article_record.get("team"))
    _add_slug(article_record.get("team_slug"))
    _add_slug(article_record.get("team_key"))

    if base_context:
        _add_abbr(base_context.get("team_abbr"))
        _add_abbr(base_context.get("team"))
        _add_slug(base_context.get("team_slug"))

    if not candidate_abbrs and not candidate_slugs:
        return base_context

    row: Optional[Mapping[str, Any]] = None

    for abbr in candidate_abbrs:
        try:
            response = (
                client.table(teams_table)
                .select("*")
                .eq("team_abbr", abbr)
                .limit(1)
                .execute()
            )
        except Exception as exc:  # pragma: no cover - Supabase SDK runtime
            LOGGER.warning("Failed to load team metadata for %s: %s", abbr, exc)
            return base_context

        rows = getattr(response, "data", None) or []
        if rows:
            row = rows[0]
            break

    if row is None:
        for slug in candidate_slugs:
            try:
                response = (
                    client.table(teams_table)
                    .select("*")
                    .eq("team_slug", slug)
                    .limit(1)
                    .execute()
                )
            except Exception as exc:  # pragma: no cover - Supabase SDK runtime
                LOGGER.warning("Failed to load team metadata for slug %s: %s", slug, exc)
                return base_context

            rows = getattr(response, "data", None) or []
            if rows:
                row = rows[0]
                break

    if row is None:
        LOGGER.debug("No team metadata found for article; using derived team context if available.")
        return base_context

    row_data = {
        key: value
        for key, value in dict(row).items()
        if value not in (None, "", [])
    }

    aliases = row_data.get("aliases")
    if isinstance(aliases, str):
        split_aliases = [alias.strip() for alias in aliases.split(",") if alias.strip()]
        row_data["aliases"] = split_aliases

    merged_context: Dict[str, Any] = dict(row_data)
    if base_context:
        merged_context.update(base_context)

    if "team" not in merged_context:
        merged_context["team"] = merged_context.get("team_abbr") or merged_context.get("team_name")

    if "team_abbr" not in merged_context and row_data.get("team_abbr"):
        merged_context["team_abbr"] = row_data["team_abbr"]

    cleaned = {
        key: value
        for key, value in merged_context.items()
        if value not in (None, "", [])
    }

    return cleaned or base_context

def _load_article_from_database(
    article_id: str,
    supabase_config: Optional[MutableMapping[str, Any]],
    table_override: Optional[str],
    teams_table_override: Optional[str],
) -> Tuple[MutableMapping[str, Any], Optional[MutableMapping[str, Any]]]:
    client = _create_supabase_client(supabase_config)
    table_name = table_override or get_env("TEAM_ARTICLE_TABLE", "team_article")

    try:
        response = (
            client.table(table_name)
            .select("*")
            .eq("id", article_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # pragma: no cover - Supabase SDK runtime
        raise ValueError(
            f"Failed to fetch article {article_id!r} from Supabase table {table_name!r}: {exc}"
        ) from exc

    rows = getattr(response, "data", None) or []
    if not rows:
        raise ValueError(
            f"Supabase returned no article for id {article_id!r} in table {table_name!r}."
        )

    record = rows[0] or {}
    article_payload, team_context = _normalise_article_record(record, table_name)
    team_context = _enrich_team_context(
        client,
        record,
        team_context,
        teams_table_override,
    )
    LOGGER.info("Loaded article %s from Supabase table %s", article_id, table_name)
    return article_payload, team_context


def _create_supabase_client(
    config: Optional[MutableMapping[str, Any]],
):
    if config is not None and not isinstance(config, MutableMapping):
        config = dict(config)

    url = None
    key = None
    schema = None

    if isinstance(config, Mapping):
        url = config.get("url") or config.get("SUPABASE_URL")
        key = config.get("key") or config.get("SUPABASE_KEY")
        schema = config.get("schema") or config.get("SUPABASE_SCHEMA")

    url = url or get_env("SUPABASE_URL")
    key = key or get_env("SUPABASE_KEY")
    schema = schema or get_env("SUPABASE_SCHEMA") or "public"

    if not url or not key:
        raise ValueError(
            "Supabase credentials are required for --db-team-article. "
            "Provide them via a supabase block, CLI overrides, or SUPABASE_URL/SUPABASE_KEY environment variables."
        )

    shared_config = SharedSupabaseConfig(url=url, key=key, schema=schema)
    return get_supabase_client(shared_config)


def _normalise_article_record(
    record: Mapping[str, Any],
    table_name: str,
) -> Tuple[MutableMapping[str, Any], Optional[MutableMapping[str, Any]]]:
    headline = _clean_string(record.get("headline"))
    sub_header = _clean_string(
        record.get("sub_header")
        or record.get("sub_headline")
        or record.get("subHeadline")
    )
    introduction = _clean_string(
        record.get("introduction_paragraph")
        or record.get("introduction")
        or record.get("intro")
    )

    paragraphs = _normalise_article_content(record.get("content"))
    if not paragraphs and introduction:
        paragraphs = [introduction]

    article: Dict[str, Any] = {
        "headline": headline,
        "sub_header": sub_header,
        "introduction_paragraph": introduction,
        "content": paragraphs,
    }

    metadata = {
        "source": "supabase",
        "supabase_table": table_name,
        "supabase_id": str(record.get("id")) if record.get("id") is not None else None,
        "team": record.get("team"),
        "language": record.get("language"),
        "created_at": record.get("created_at"),
    }
    article_metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
    if article_metadata:
        article["metadata"] = article_metadata

    team_context: Optional[MutableMapping[str, Any]] = None
    team_value = record.get("team")
    language = record.get("language")
    if team_value or language or record.get("team_name") or record.get("team_abbr"):
        context_payload: Dict[str, Any] = {
            "team": team_value,
            "language": language,
            "team_name": record.get("team_name") or record.get("team_display_name"),
            "team_abbr": record.get("team_abbr") or team_value,
            "supabase_id": str(record.get("id")) if record.get("id") is not None else None,
        }
        team_context = {
            key: value
            for key, value in context_payload.items()
            if value not in (None, "")
        }

    return article, team_context


def _normalise_article_content(value: Any) -> list[str]:
    paragraphs: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = _clean_string(item)
            if text:
                paragraphs.append(text)
    elif isinstance(value, str):
        normalised = value.replace("\r\n", "\n")
        segments = [segment.strip() for segment in normalised.split("\n\n") if segment.strip()]
        if not segments:
            segments = [segment.strip() for segment in normalised.split("\n") if segment.strip()]
        paragraphs.extend(segments)
    return paragraphs


def _clean_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


# ---------------------------------------------------------------------------
# JSON loading utilities
# ---------------------------------------------------------------------------

def _load_json_file(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} file contains invalid JSON: {path} (line {exc.lineno})") from exc
    except OSError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unable to read {label} file: {path}") from exc


def _parse_json_string(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must contain valid JSON (column {exc.colno}).") from exc


def _ensure_mapping(value: Any, label: str) -> MutableMapping[str, Any]:
    if isinstance(value, MutableMapping):
        return dict(value)
    if isinstance(value, Mapping):
        return dict(value.items())
    raise ValueError(f"{label} must resolve to a JSON object")


def _coerce_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    if isinstance(value, tuple):
        return _coerce_string_list(list(value), label)
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    raise ValueError(f"{label} must be a list of strings")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _emit_output(report, args: argparse.Namespace) -> None:
    indent = None if args.compact else 2
    report_json = json.dumps(report.to_dict(), indent=indent, ensure_ascii=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_json + "\n", encoding="utf-8")
        if not args.quiet:
            print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report_json)

    if args.summary:
        summary_json = json.dumps(report.summary(), indent=indent, ensure_ascii=False)
        if args.output and args.quiet:
            print(summary_json)
        elif args.output:
            print("\nSummary:\n" + summary_json)
        else:
            print("\nSummary:\n" + summary_json)


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    run()
