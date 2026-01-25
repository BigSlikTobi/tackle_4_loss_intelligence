"""Image selection service orchestrating search, ranking, and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
import certifi

try:
    from duckduckgo_search import DDGS
except ImportError:  # pragma: no cover - fallback for renamed package
    from ddgs import DDGS  # type: ignore

from src.shared.db.connection import SupabaseConfig as SharedSupabaseConfig
from src.shared.db.connection import get_supabase_client

from .config import ImageSelectionRequest
from .llm import LLMClient, create_llm_client

logger = logging.getLogger(__name__)

BLACKLISTED_DOMAINS = {
    "lookaside.instagram.com",
    "gettyimages.com",
    "shutterstock.com",
    "istockphoto.com",
    "tiktok.com",
    "fanatics.com",
    "static.nike.com",
    "c8.alamy.com",
    "alamy.com",
    "fanatics.frgimages.com",
    "adobe.com",
    "dreamstime.com",
    "123rf.com",
    "depositphotos.com",
    "bigstock.com",
    "fotolia.com",
    "corbis.com",
    "masterfile.com",
    "superstock.com",
    "agefotostock.com",
    "stockphoto.com",
    "stockvault.net",
    "crestock.com",
    "canstockphoto.com",
    "wallpaperflare.com",
    "cdn.pixabay.com",
    "reddit.com",
    "i.redd.it",
    "youtube.com",
}

IRRELEVANCE_TERMS = {
    "logo",
    "icon",
    "banner",
    "stock",
    "watermark",
    "placeholder",
    "thumbnail",
    "graphic",
    "chart",
    "screenshot",
}

MIN_WIDTH = 640
MIN_HEIGHT = 360
MIN_BYTES = 50_000

GOOGLE_SEARCH_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


@dataclass
class ImageCandidate:
    """Represents an image returned by search providers."""

    url: str
    title: str
    context_url: Optional[str]
    source: Optional[str]
    author: Optional[str]
    width: Optional[int]
    height: Optional[int]
    byte_size: Optional[int]
    mime_type: Optional[str]
    license: Optional[str]
    original_data: Dict


@dataclass
class ProcessedImage:
    """Result of processing and storing an image."""

    public_url: str
    original_url: str
    author: Optional[str]
    source: Optional[str]
    width: Optional[int]
    height: Optional[int]
    title: str
    record_id: Optional[str] = None


class ImageSelectionService:
    """Service orchestrating the image selection workflow."""

    def __init__(self, request: ImageSelectionRequest) -> None:
        request.validate()
        self.request = request
        self.llm_client: Optional[LLMClient] = None
        if request.enable_llm and request.llm_config:
            self.llm_client = create_llm_client(request.llm_config)

        self.supabase: Optional[Any] = None
        self.supabase_bucket: Optional[str] = None
        self.supabase_table: Optional[str] = None
        self.supabase_schema: Optional[str] = None
        supabase_cfg = request.supabase_config
        if supabase_cfg:
            shared_cfg = SharedSupabaseConfig(
                url=supabase_cfg.url,
                key=supabase_cfg.key,
                schema=supabase_cfg.schema,
            )
            self.supabase = get_supabase_client(shared_cfg)
            self.supabase_bucket = supabase_cfg.bucket
            self.supabase_table = supabase_cfg.table
            self.supabase_schema = supabase_cfg.schema
        else:
            logger.info("Supabase disabled; images will not be uploaded or persisted.")

        self.resolved_query: Optional[str] = None
        self._http_timeout = aiohttp.ClientTimeout(total=12)
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def process(self) -> List[ProcessedImage]:
        """Main entry point returning processed image metadata."""

        query = await self._build_query()
        self.resolved_query = query
        logger.info("Searching images using query: %s", query)

        connector = aiohttp.TCPConnector(ssl=self._ssl_context)
        try:
            async with aiohttp.ClientSession(
                timeout=self._http_timeout,
                connector=connector,
                connector_owner=False,
            ) as session:
                candidates: List[ImageCandidate] = []
                if self.request.search_config:
                    candidates.extend(await self._search_google(session, query))
                else:
                    logger.info(
                        "Google Custom Search configuration missing; skipping primary provider"
                    )

                if not candidates:
                    if self.request.search_config:
                        logger.warning(
                            "Primary search returned no candidates, using fallback"
                        )
                    else:
                        logger.info("Using DuckDuckGo fallback for image discovery")
                    candidates = await self._search_duckduckgo(query)

                ranked = self._rank_candidates(candidates, query)
                
                # Pre-filter candidates in parallel using HEAD requests
                # This prevents rejected images from counting toward the tries
                logger.info("Pre-filtering %d candidates with HEAD requests...", len(ranked))
                prefiltered = await self._prefilter_candidates(session, ranked)
                logger.info("After pre-filtering: %d candidates remain", len(prefiltered))
                
                results: List[ProcessedImage] = []

                for candidate in prefiltered:
                    if len(results) >= self.request.num_images:
                        break
                    try:
                        if not await self._validate_candidate(session, candidate):
                            continue
                        public_url = candidate.url
                        record: Optional[Dict[str, Any]] = None
                        if self.supabase is not None:
                            image_bytes = await self._download_image(
                                session, candidate.url
                            )
                            public_url = await self._upload_image(
                                image_bytes, candidate
                            )
                            record = await self._record_image(public_url, candidate)
                        results.append(
                            ProcessedImage(
                                public_url=public_url,
                                original_url=candidate.url,
                                author=candidate.author,
                                source=candidate.source,
                                width=candidate.width,
                                height=candidate.height,
                                title=candidate.title,
                                record_id=self._extract_record_id(record),
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Failed to process candidate %s: %s", candidate.url, exc
                        )
                        continue

                return results
        finally:
            await connector.close()

    async def _build_query(self) -> str:
        if self.request.explicit_query:
            return self.request.explicit_query

        article_text = self.request.article_text or ""
        if self.llm_client:
            try:
                logger.info("Using LLM provider %s", self.request.llm_config.provider)  # type: ignore[arg-type]
                return await self.llm_client.generate_query(article_text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM query optimization failed: %s", exc)

        return self._heuristic_query(article_text)

    def _heuristic_query(self, text: str) -> str:
        cleaned = re.sub(r"<[^>]+>", "", text).strip()
        words = cleaned.split()
        if len(words) <= 8:
            return cleaned[:120]

        entities = self._extract_entities(words)
        if entities:
            return " ".join(entities[:8])

        return " ".join(words[:8])

    @staticmethod
    def _extract_entities(words: List[str]) -> List[str]:
        entities: List[str] = []
        previous_word = ""
        for index, word in enumerate(words):
            token = word.strip(",.!?:;()[]{}\"'-\u2019")
            if not token:
                continue
            if token[0].isupper() and index > 0 and previous_word:
                entities.append(f"{previous_word} {token}")
            if token[0].isupper():
                entities.append(token)
            previous_word = token
        deduplicated = list(dict.fromkeys([entity for entity in entities if len(entity) > 2]))
        return deduplicated

    async def _search_google(self, session: aiohttp.ClientSession, query: str) -> List[ImageCandidate]:
        search_cfg = self.request.search_config
        if search_cfg is None:
            return []
        params = {
            "key": search_cfg.api_key,
            "cx": search_cfg.engine_id,
            "q": query,
            "searchType": "image",
            "rights": search_cfg.rights_filter,
            "safe": search_cfg.safe_search,
            "imgType": search_cfg.image_type,
            "imgSize": search_cfg.image_size,
            "num": min(search_cfg.max_candidates, 10),
        }

        async with session.get(GOOGLE_SEARCH_ENDPOINT, params=params) as response:
            if response.status != 200:
                text = await response.text()
                logger.warning("Google search failed (%s): %s", response.status, text)
                return []
            payload = await response.json()

        items = payload.get("items", [])
        candidates: List[ImageCandidate] = []
        for item in items:
            image = item.get("image", {})
            url = item.get("link")
            if not url:
                continue
            candidate = self._build_candidate_from_google(item, image)
            if candidate:
                candidates.append(candidate)
        return candidates

    async def _search_duckduckgo(self, query: str) -> List[ImageCandidate]:
        def _search() -> List[ImageCandidate]:
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            results: List[ImageCandidate] = []
            # Fetch more candidates to account for pre-filtering losses
            max_results = max(self.request.num_images * 10, 20)
            try:
                with DDGS() as ddgs:
                    for image in ddgs.images(
                        query,
                        safesearch="moderate",
                        max_results=max_results,
                    ):
                        url = image.get("image") or image.get("thumbnail")
                        if not url:
                            continue

                        license_text = (
                            image.get("license")
                            or image.get("license_id")
                            or image.get("license_info")
                            or ""
                        ).lower()
                        if not self._is_allowed_license(license_text):
                            continue

                        published = image.get("published")
                        if published:
                            try:
                                published_dt = datetime.fromisoformat(
                                    published.replace("Z", "+00:00")
                                )
                                if published_dt.tzinfo is None:
                                    published_dt = published_dt.replace(
                                        tzinfo=timezone.utc
                                    )
                                else:
                                    published_dt = published_dt.astimezone(
                                        timezone.utc
                                    )
                                if published_dt < cutoff:
                                    continue
                            except ValueError:
                                pass
                        context_url = image.get("url") or image.get("source_url")
                        source_domain = urlparse(context_url).netloc if context_url else None
                        candidate = ImageCandidate(
                            url=url,
                            title=image.get("title", ""),
                            context_url=context_url,
                            source=source_domain or image.get("source"),
                            author=image.get("publisher") or image.get("title_source"),
                            width=image.get("width"),
                            height=image.get("height"),
                            byte_size=None,
                            mime_type=None,
                            license=license_text,
                            original_data=image,
                        )
                        if self._passes_basic_filters(candidate):
                            results.append(candidate)
            except Exception as exc:  # noqa: BLE001
                message = str(exc).lower()
                if "ratelimit" in message or "rate limit" in message:
                    logger.warning("DuckDuckGo rate limit encountered: %s", exc)
                    return []
                raise
            return results

        return await asyncio.to_thread(_search)

    def _build_candidate_from_google(self, item: Dict, image: Dict) -> Optional[ImageCandidate]:
        url = item.get("link")
        context_url = image.get("contextLink")
        title = item.get("title", "")
        width = image.get("width")
        height = image.get("height")
        byte_size = image.get("byteSize")
        mime_type = image.get("mime")
        license_info = image.get("license")
        source = None
        if context_url:
            source = urlparse(context_url).netloc
        elif url:
            source = urlparse(url).netloc

        candidate = ImageCandidate(
            url=url,
            title=title,
            context_url=context_url,
            source=source,
            author=image.get("displayLink"),
            width=width,
            height=height,
            byte_size=byte_size,
            mime_type=mime_type,
            license=(license_info or "").lower() if license_info else license_info,
            original_data=item,
        )

        if not self._passes_basic_filters(candidate):
            return None
        return candidate

    def _passes_basic_filters(self, candidate: ImageCandidate) -> bool:
        domain = urlparse(candidate.url).netloc.lower()
        if any(blocked in domain for blocked in BLACKLISTED_DOMAINS):
            logger.info("Skipping %s due to blacklisted domain", candidate.url)
            return False

        title_lower = candidate.title.lower()
        if any(term in title_lower for term in IRRELEVANCE_TERMS):
            logger.info("Skipping %s due to irrelevance term in title", candidate.url)
            return False

        if candidate.width and candidate.height:
            if candidate.width < MIN_WIDTH or candidate.height < MIN_HEIGHT:
                logger.info("Skipping %s due to low resolution", candidate.url)
                return False

        if candidate.byte_size and candidate.byte_size < MIN_BYTES:
            logger.info("Skipping %s due to small byte size", candidate.url)
            return False

        license_info = (candidate.license or "").lower()
        if license_info:
            if not self._is_allowed_license(license_info):
                logger.info(
                    "Skipping %s due to disallowed license metadata: %s",
                    candidate.url,
                    license_info,
                )
                return False
        elif self.request.search_config is None:
            logger.info("Skipping %s due to missing license metadata", candidate.url)
            return False

        return True

    @staticmethod
    def _is_allowed_license(license_text: str) -> bool:
        if not license_text:
            return False
        disallowed = {
            "all rights reserved",
            "copyright",
            "\u00a9",
            "getty",
            "shutterstock",
            "stock",
        }
        if any(term in license_text for term in disallowed):
            return False
        allowed = {
            "creative commons",
            "cc",
            "public domain",
            "public",
            "sharealike",
            "share alike",
            "attribution",
            "wikimedia",
        }
        return any(term in license_text for term in allowed)

    def _rank_candidates(self, candidates: List[ImageCandidate], query: str) -> List[ImageCandidate]:
        if not candidates:
            return []
        content_words = set()
        if self.request.article_text:
            content_words = set(re.findall(r"\b\w+\b", self.request.article_text.lower()))
        query_words = set(query.lower().split())

        scored: List[tuple[ImageCandidate, float]] = []
        for candidate in candidates:
            title_words = set(re.findall(r"\b\w+\b", candidate.title.lower()))
            score = 0.0
            score += len(title_words & content_words) * 3.5
            score += len(title_words & query_words) * 6.0

            for term in query_words:
                if term in candidate.title.lower():
                    score += 3.0

            if candidate.width and candidate.height:
                if candidate.width >= MIN_WIDTH and candidate.height >= MIN_HEIGHT:
                    score += 2.0
                aspect_ratio = candidate.width / max(candidate.height, 1)
                if 1.3 <= aspect_ratio <= 2.5:
                    score += 0.5

            if "news" in candidate.title.lower():
                score += 0.5

            if score <= 0:
                score -= 5.0

            scored.append((candidate, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [candidate for candidate, _ in scored]

    async def _validate_candidate(
        self, session: aiohttp.ClientSession, candidate: ImageCandidate
    ) -> bool:
        domain = urlparse(candidate.url).netloc.lower()
        if any(blocked in domain for blocked in BLACKLISTED_DOMAINS):
            return False
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            }
            async with session.get(candidate.url, headers=headers) as response:
                if response.status != 200:
                    logger.warning("Validation failed for %s (status %s)", candidate.url, response.status)
                    return False
                content_type = response.headers.get("Content-Type", "").lower()
                if "image" not in content_type:
                    logger.warning("Validation failed for %s due to content type %s", candidate.url, content_type)
                    return False
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Validation error for %s: %s", candidate.url, exc)
            return False

    async def _prefilter_candidates(
        self, session: aiohttp.ClientSession, candidates: List[ImageCandidate]
    ) -> List[ImageCandidate]:
        """Pre-filter candidates using HEAD requests to check size/type before processing.
        
        This prevents rejected images from counting toward the processing limit.
        Uses parallel requests for efficiency.
        """
        if not candidates:
            return []

        async def check_candidate(candidate: ImageCandidate) -> Optional[ImageCandidate]:
            """Check a single candidate via HEAD request and return it if valid."""
            # Skip if already filtered by basic filters with known metadata
            if candidate.width and candidate.height:
                if candidate.width < MIN_WIDTH or candidate.height < MIN_HEIGHT:
                    logger.info("Pre-filter: Skipping %s due to low resolution (%dx%d)", 
                               candidate.url, candidate.width, candidate.height)
                    return None
            if candidate.byte_size and candidate.byte_size < MIN_BYTES:
                logger.info("Pre-filter: Skipping %s due to small byte size (%d bytes)", 
                           candidate.url, candidate.byte_size)
                return None

            # For candidates without metadata, use HEAD request to check
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                }
                # Use HEAD request first (faster, no body download)
                async with session.head(candidate.url, headers=headers, allow_redirects=True) as response:
                    if response.status != 200:
                        # Some servers don't support HEAD, fall back to GET with range
                        async with session.get(candidate.url, headers={**headers, "Range": "bytes=0-0"}) as get_response:
                            if get_response.status not in (200, 206):
                                logger.info("Pre-filter: Skipping %s - not accessible (status %d)", 
                                           candidate.url, get_response.status)
                                return None
                            content_length = get_response.headers.get("Content-Length") or get_response.headers.get("Content-Range", "").split("/")[-1]
                            content_type = get_response.headers.get("Content-Type", "").lower()
                    else:
                        content_length = response.headers.get("Content-Length")
                        content_type = response.headers.get("Content-Type", "").lower()

                    # Check content type
                    if content_type and "image" not in content_type:
                        logger.info("Pre-filter: Skipping %s - not an image (%s)", 
                                   candidate.url, content_type)
                        return None

                    # Check byte size from Content-Length header
                    if content_length:
                        try:
                            byte_size = int(content_length)
                            if byte_size < MIN_BYTES:
                                logger.info("Pre-filter: Skipping %s due to small byte size (%d bytes)", 
                                           candidate.url, byte_size)
                                return None
                            # Update candidate with discovered byte size
                            candidate.byte_size = byte_size
                        except ValueError:
                            pass

                return candidate
            except asyncio.TimeoutError:
                logger.info("Pre-filter: Skipping %s - timeout", candidate.url)
                return None
            except Exception as exc:  # noqa: BLE001
                logger.info("Pre-filter: Skipping %s - error: %s", candidate.url, exc)
                return None

        # Run checks in parallel with a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(10)  # Max 10 concurrent HEAD requests

        async def limited_check(candidate: ImageCandidate) -> Optional[ImageCandidate]:
            async with semaphore:
                return await check_candidate(candidate)

        tasks = [limited_check(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out None results and exceptions
        valid_candidates = [
            r for r in results 
            if r is not None and not isinstance(r, Exception)
        ]
        return valid_candidates

    async def _download_image(
        self, session: aiohttp.ClientSession, url: str, max_retries: int = 3
    ) -> bytes:
        attempt = 0
        backoff = 1.5
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
        while attempt <= max_retries:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Unexpected status {response.status}")
                    data = await response.read()
                    if not data:
                        raise RuntimeError("Empty response body")
                    return data
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                logger.warning("Download failed for %s (%s) attempt %s", url, exc, attempt)
                await asyncio.sleep(backoff * attempt)
        raise RuntimeError(f"Failed to download image from {url}")

    async def _upload_image(self, image_bytes: bytes, candidate: ImageCandidate) -> str:
        if self.supabase is None or not self.supabase_bucket:
            raise RuntimeError("Supabase storage is not configured")

        def _upload() -> str:
            path = self._build_destination_path(candidate.url)
            extension = self._guess_extension(candidate.mime_type, candidate.url)
            destination = f"{path}{extension}"
            content_type = self._content_type(extension)
            logger.info("Uploading image to Supabase path %s", destination)
            response = self.supabase.storage.from_(self.supabase_bucket).upload(
                path=destination,
                file=image_bytes,
                file_options={"contentType": content_type},
            )
            if isinstance(response, dict) and response.get("error"):
                raise RuntimeError(str(response["error"]))
            supabase_url = self.supabase_url()
            return f"{supabase_url}/storage/v1/object/public/{self.supabase_bucket}/{destination}"

        return await asyncio.to_thread(_upload)

    def supabase_url(self) -> str:
        config = self.request.supabase_config
        if config is None:
            raise RuntimeError("Supabase URL requested but Supabase is disabled")
        return config.url.rstrip("/")

    async def _record_image(self, public_url: str, candidate: ImageCandidate) -> Optional[Dict[str, Any]]:
        if self.supabase is None or not self.supabase_table:
            raise RuntimeError("Supabase persistence is not configured")

        def _insert() -> Optional[Dict[str, Any]]:
            payload = {
                "image_url": public_url,
                "original_url": candidate.context_url or candidate.url,
                "author": candidate.author or "",
                "source": candidate.source or "",
            }
            table = self.supabase.table(self.supabase_table)
            response = table.insert(payload).execute()
            error = getattr(response, "error", None)
            if error:
                message = str(error).lower()
                if "duplicate" in message or "unique" in message:
                    existing = (
                        table.select("id,image_url,original_url")
                        .eq("image_url", payload["image_url"])
                        .limit(1)
                        .execute()
                    )
                    existing_data = getattr(existing, "data", None) or []
                    if existing_data:
                        logger.info("Reusing existing image record for %s", payload["image_url"])
                        return existing_data[0]
                raise RuntimeError(error)  # type: ignore[arg-type]
            data = getattr(response, "data", None) or []
            if data:
                return data[0]
            existing = (
                table.select("id,image_url,original_url")
                .eq("image_url", payload["image_url"])
                .limit(1)
                .execute()
            )
            existing_data = getattr(existing, "data", None) or []
            if existing_data:
                return existing_data[0]
            return payload

        return await asyncio.to_thread(_insert)

    @staticmethod
    def _extract_record_id(record: Optional[Dict[str, Any]]) -> Optional[str]:
        if not record or not isinstance(record, dict):
            return None
        for key in ("id", "image_id", "uuid", "record_id"):
            value = record.get(key)
            if value:
                return str(value)
        return None

    def _build_destination_path(self, original_url: str) -> str:
        digest = hashlib.md5(original_url.encode("utf-8")).hexdigest()
        timestamp = int(time.time())
        path = PurePosixPath("public") / f"{digest}_{timestamp}"
        return str(path)

    @staticmethod
    def _guess_extension(mime_type: Optional[str], url: str) -> str:
        if mime_type == "image/png" or url.lower().endswith(".png"):
            return ".png"
        if mime_type == "image/webp" or url.lower().endswith(".webp"):
            return ".webp"
        return ".jpg"

    @staticmethod
    def _content_type(extension: str) -> str:
        if extension == ".png":
            return "image/png"
        if extension == ".webp":
            return "image/webp"
        return "image/jpeg"
