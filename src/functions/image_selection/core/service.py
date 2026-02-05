"""Image selection service orchestrating search, ranking, and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urljoin

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
from .prompts import build_image_query
from .vision_validator import VisionValidator
from .source_reputation import get_source_score_from_url

logger = logging.getLogger(__name__)

BLACKLISTED_DOMAINS = {
    # Stock photo sites
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
    # Generic lookaside crawlers
    "lookaside",
    # Trading cards & collectibles
    "panini.com",
    "paniniamerica.net",
    "topps.com",
    "tradingcarddb.com",
    "beckett.com",
    "comc.com",
    "sportscardspro.com",
    "psacard.com",
    # Fantasy sports
    "espn.com/fantasy",
    "yahoo.com/fantasy",
    "draftkings.com",
    "fanduel.com",
    "fantasypros.com",
    "rotowire.com",
    # Video platforms (thumbnails)
    "i.ytimg.com",
    "vimeo.com",
    # Social/aggregator sites
    "pinterest.com",
    "tumblr.com",
    "blogspot.com",
    "wordpress.com",
    "medium.com",
    "watson.ch",
    "lookaside.fbsbx.com",
}

TRUSTED_SITE_SEARCH_DOMAINS = [
    "nfl.com",
    "nflcdn.com",
    "espn.com",
    "cbssports.com",
    "nbcsports.com",
    "foxsports.com",
    "theathletic.com",
    "usatoday.com",
    "apnews.com",
    "reuters.com",
    "si.com",
    "bleacherreport.com",
    "profootballtalk.com",
    "yahoo.com",
    "sports.yahoo.com",
]


IRRELEVANCE_TERMS = {
    # Graphics/overlays
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
    "overlay",
    "template",
    "mockup",
    # Trading cards
    "card",
    "trading",
    "rookie",
    "autograph",
    "panini",
    "topps",
    "prizm",
    "optic",
    # Fantasy/stats
    "fantasy",
    "stat",
    "stats",
    "score",
    "lineup",
    "projection",
    "ranking",
    "dfs",
    # Video content
    "highlight",
    "highlights",
    "replay",
    "clip",
    "video",
    "watch",
    # Merchandise
    "jersey",
    "merchandise",
    "shop",
    "buy",
    "sale",
    "store",
}

# URL patterns to block (regex)
BLOCKED_URL_PATTERNS = [
    r"\?text=",
    r"overlay",
    r"composite",
    r"/thumb/",
    r"/small/",
    r"_thumb\.",
    r"-card-",
    r"trading.card",
    r"_thumbnail",
    r"/preview/",
    r"watermark",
    r"/draft/",
    r"fantasy",
]

DEFAULT_MIN_WIDTH = 1024
DEFAULT_MIN_HEIGHT = 576
DEFAULT_MIN_BYTES = 50_000

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

        # Vision-based validation (OCR + CLIP)
        self.vision_validator: Optional[VisionValidator] = None
        if request.vision_config and request.vision_config.enabled:
            self.vision_validator = VisionValidator(request.vision_config)
            logger.info("Vision validation enabled (OCR: %s, CLIP: %s)",
                       request.vision_config.enable_ocr,
                       request.vision_config.enable_clip)
        else:
            logger.info("Vision validation disabled")

    async def process(self) -> List[ProcessedImage]:
        """Main entry point returning processed image metadata."""

        connector = aiohttp.TCPConnector(ssl=self._ssl_context)
        try:
            async with aiohttp.ClientSession(
                timeout=self._http_timeout,
                connector=connector,
                connector_owner=False,
            ) as session:
                if self.request.source_url:
                    logger.info("Checking source URL for Creative Commons image before search")
                    source_results = await self._source_url_fallback(session)
                    if source_results:
                        return source_results

                raw_query = await self._build_query()
                primary_query = build_image_query(raw_query)
                required_terms = self._resolve_required_terms(primary_query)
                if required_terms:
                    logger.info("Derived required terms: %s", ", ".join(required_terms))
                fallback_terms_query = None
                if required_terms:
                    fallback_terms_query = build_image_query(" ".join(required_terms[:6]))

                ranked: List[ImageCandidate] = []
                for attempt, query in enumerate(
                    [primary_query, fallback_terms_query]
                ):
                    if not query:
                        continue
                    self.resolved_query = query
                    logger.info("Searching images using query: %s", query)

                    candidates: List[ImageCandidate] = []
                    if self.request.search_config:
                        candidates.extend(await self._search_google(session, query))
                    else:
                        logger.info(
                            "Google Custom Search configuration missing; skipping primary provider"
                        )

                    if not candidates:
                        if self.request.search_config:
                            trusted_query = self._build_trusted_query(query)
                            if trusted_query:
                                logger.info(
                                    "No candidates; retrying Google search restricted to trusted sources"
                                )
                                candidates = await self._search_google(session, trusted_query)

                    if not candidates:
                        if self.request.strict_mode:
                            logger.warning(
                                "Strict mode enabled; skipping DuckDuckGo fallback"
                            )
                            candidates = []
                        elif self.request.search_config:
                            logger.warning(
                                "Primary search returned no candidates, using fallback"
                            )
                            candidates = await self._search_duckduckgo(query)
                        else:
                            logger.info("Using DuckDuckGo fallback for image discovery")
                            candidates = await self._search_duckduckgo(query)

                    candidates = self._filter_by_source_score(candidates)
                    apply_terms_filter = attempt == 0 or self.request.strict_mode
                    if apply_terms_filter:
                        candidates = self._filter_by_required_terms(candidates, required_terms)

                    scored = self._score_candidates(candidates, query)
                    ranked = [candidate for candidate, _ in scored]

                    if self.request.min_relevance_score > 0:
                        filtered = [
                            candidate
                            for candidate, score in scored
                            if score >= self.request.min_relevance_score
                        ]
                        logger.info(
                            "Applied min relevance score %.2f: %d -> %d candidates",
                            self.request.min_relevance_score,
                            len(ranked),
                            len(filtered),
                        )
                        ranked = filtered

                    if ranked:
                        break

                    if attempt == 0 and fallback_terms_query:
                        logger.info(
                            "No candidates after required-term filtering; retrying with terms-only query."
                        )

                # Pre-filter candidates in parallel using HEAD requests
                # This prevents rejected images from counting toward the tries
                logger.info("Pre-filtering %d candidates with HEAD requests...", len(ranked))
                prefiltered = await self._prefilter_candidates(session, ranked)
                logger.info("After pre-filtering: %d candidates remain", len(prefiltered))
                
                results = await self._process_candidates(session, prefiltered)
                return results
        finally:
            await connector.close()

    async def _process_candidates(
        self, session: aiohttp.ClientSession, candidates: List[ImageCandidate]
    ) -> List[ProcessedImage]:
        results: List[ProcessedImage] = []
        for candidate in candidates:
            if len(results) >= self.request.num_images:
                break
            try:
                if not await self._validate_candidate(session, candidate):
                    continue

                image_bytes = await self._download_image(session, candidate.url)

                if self.vision_validator:
                    validation = await self.vision_validator.validate_image(
                        image_bytes, self.resolved_query or ""
                    )
                    if not validation.passed:
                        logger.info(
                            "Rejecting %s via vision validation: %s",
                            candidate.url,
                            validation.reason,
                        )
                        continue
                    if validation.clip_similarity:
                        logger.debug(
                            "Image %s CLIP score: %.2f",
                            candidate.url,
                            validation.clip_similarity,
                        )

                public_url = candidate.url
                record: Optional[Dict[str, Any]] = None
                if self.supabase is not None:
                    # Check for existing image by original_url to avoid duplicates
                    existing = await self._find_existing_image(candidate)
                    if existing:
                        public_url = existing.get("image_url") or candidate.url
                        record = existing
                        logger.info(
                            "Reusing existing image for original_url %s",
                            candidate.url,
                        )
                    else:
                        public_url = await self._upload_image(image_bytes, candidate)
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

    async def _source_url_fallback(
        self, session: aiohttp.ClientSession
    ) -> List[ProcessedImage]:
        source_url = self.request.source_url
        if not source_url:
            return []

        source_domain = self._extract_domain(source_url)
        if not source_domain:
            return []

        html = await self._fetch_source_html(session, source_url)
        if not html:
            return []

        image_url = self._extract_og_image(html, source_url)
        if not image_url:
            logger.info("Source URL missing og:image: %s", source_url)
            return []

        image_domain = self._extract_domain(image_url)
        if not image_domain:
            return []

        candidate = ImageCandidate(
            url=image_url,
            title="",
            context_url=source_url,
            source=source_domain,
            author=None,
            width=None,
            height=None,
            byte_size=None,
            mime_type=None,
            license=None,
            original_data={"source_url": source_url},
        )

        if not self._passes_basic_filters(candidate):
            return []

        prefiltered = await self._prefilter_candidates(session, [candidate])
        if not prefiltered:
            return []

        logger.info("Using source URL fallback image from %s", source_url)
        return await self._process_candidates(session, prefiltered)

    @staticmethod
    def _extract_domain(url: str) -> Optional[str]:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain or None

    async def _fetch_source_html(
        self, session: aiohttp.ClientSession, source_url: str
    ) -> Optional[str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
        try:
            async with session.get(source_url, headers=headers) as response:
                if response.status != 200:
                    logger.info(
                        "Source URL request failed (%s): %s",
                        response.status,
                        source_url,
                    )
                    return None
                return await response.text(errors="ignore")
        except Exception as exc:  # noqa: BLE001
            logger.info("Source URL request error for %s: %s", source_url, exc)
            return None

    @staticmethod
    def _has_creative_commons_license(html: str) -> bool:
        lowered = html.lower()
        if "creativecommons.org/licenses" in lowered:
            return True
        if "creative commons" in lowered:
            return True
        return False

    @staticmethod
    def _extract_og_image(html: str, source_url: str) -> Optional[str]:
        patterns = [
            r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                url = match.group(1).strip()
                if url:
                    return urljoin(source_url, url)
        return None

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

    def _resolve_required_terms(self, query: Optional[str] = None) -> List[str]:
        if self.request.required_terms:
            return [term.lower() for term in self.request.required_terms if term]

        if query:
            extracted = self._extract_terms_from_query(query)
            if extracted:
                return extracted

        if not self.request.article_text:
            return []

        cleaned = re.sub(r"<[^>]+>", "", self.request.article_text).strip()
        words = cleaned.split()
        entities = self._extract_entities(words)
        if not entities:
            return []
        return [entity.lower() for entity in entities[:8]]

    @staticmethod
    def _extract_terms_from_query(query: str) -> List[str]:
        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "into",
            "der", "die", "das", "und", "mit", "für", "vom", "von", "dass",
            "nfl", "american", "football", "headshot", "photo", "image",
        }
        terms: List[str] = []
        for token in query.split():
            if token.startswith("-") or "site:" in token:
                continue
            cleaned = re.sub(r"[^a-zA-Z0-9]", "", token).lower()
            if len(cleaned) < 3:
                continue
            if cleaned in stopwords:
                continue
            terms.append(cleaned)
        return list(dict.fromkeys(terms))[:8]

    @staticmethod
    def _build_trusted_query(base_query: str, limit: int = 8) -> Optional[str]:
        if not base_query:
            return None
        domains = TRUSTED_SITE_SEARCH_DOMAINS[:limit]
        if not domains:
            return None
        site_filters = " OR ".join(f"site:{domain}" for domain in domains)
        return f"{base_query} ({site_filters})"

    def _filter_by_required_terms(
        self, candidates: List[ImageCandidate], terms: List[str]
    ) -> List[ImageCandidate]:
        if not candidates or not terms:
            return candidates

        def _matches(candidate: ImageCandidate) -> bool:
            haystack = " ".join(
                [
                    candidate.title or "",
                    candidate.url or "",
                    candidate.context_url or "",
                ]
            ).lower()
            return any(term in haystack for term in terms)

        filtered = [candidate for candidate in candidates if _matches(candidate)]
        logger.info(
            "Applied required terms filter (%d terms): %d -> %d candidates",
            len(terms),
            len(candidates),
            len(filtered),
        )
        return filtered

    def _filter_by_source_score(
        self, candidates: List[ImageCandidate]
    ) -> List[ImageCandidate]:
        threshold = self.request.min_source_score
        if threshold <= 0:
            return candidates

        def _score(candidate: ImageCandidate) -> float:
            url = candidate.context_url or candidate.url
            return get_source_score_from_url(url)

        filtered = [candidate for candidate in candidates if _score(candidate) >= threshold]
        logger.info(
            "Applied source score threshold %.2f: %d -> %d candidates",
            threshold,
            len(candidates),
            len(filtered),
        )
        return filtered

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
        target = max(search_cfg.max_candidates, self.request.num_images * 5)
        per_page = min(10, target)
        start = 1
        candidates: List[ImageCandidate] = []

        while start <= 100 and len(candidates) < target:
            params = {
                "key": search_cfg.api_key,
                "cx": search_cfg.engine_id,
                "q": query,
                "searchType": "image",
                "rights": search_cfg.rights_filter,
                "safe": search_cfg.safe_search,
                "imgType": search_cfg.image_type,
                "imgSize": search_cfg.image_size,
                "num": per_page,
                "start": start,
            }

            async with session.get(GOOGLE_SEARCH_ENDPOINT, params=params) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.warning("Google search failed (%s): %s", response.status, text)
                    break
                payload = await response.json()

            items = payload.get("items", [])
            if not items:
                break

            for item in items:
                image = item.get("image", {})
                url = item.get("link")
                if not url:
                    continue
                candidate = self._build_candidate_from_google(item, image)
                if candidate:
                    candidates.append(candidate)
                if len(candidates) >= target:
                    break

            start += per_page

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

        # Check URL against blocked patterns
        url_lower = candidate.url.lower()
        for pattern in BLOCKED_URL_PATTERNS:
            if re.search(pattern, url_lower):
                logger.info("Skipping %s due to blocked URL pattern: %s", candidate.url, pattern)
                return False

        min_width = self.request.min_width if self.request.min_width > 0 else DEFAULT_MIN_WIDTH
        min_height = self.request.min_height if self.request.min_height > 0 else DEFAULT_MIN_HEIGHT
        min_bytes = self.request.min_bytes if self.request.min_bytes > 0 else DEFAULT_MIN_BYTES

        if candidate.width and candidate.height:
            if candidate.width < min_width or candidate.height < min_height:
                logger.info("Skipping %s due to low resolution", candidate.url)
                return False

        if candidate.byte_size and candidate.byte_size < min_bytes:
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

    def _score_candidates(self, candidates: List[ImageCandidate], query: str) -> List[tuple[ImageCandidate, float]]:
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

        min_width = self.request.min_width if self.request.min_width > 0 else DEFAULT_MIN_WIDTH
        min_height = self.request.min_height if self.request.min_height > 0 else DEFAULT_MIN_HEIGHT
        if candidate.width and candidate.height:
            if candidate.width >= min_width and candidate.height >= min_height:
                score += 2.0
                aspect_ratio = candidate.width / max(candidate.height, 1)
                if 1.3 <= aspect_ratio <= 2.5:
                    score += 0.5

            if "news" in candidate.title.lower():
                score += 0.5

            # Boost trusted editorial sources
            if candidate.url:
                source_score = get_source_score_from_url(candidate.url)
                score += source_score * 3.0  # Up to +3.0 for trusted sources

            if score <= 0:
                score -= 5.0

            scored.append((candidate, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

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
            min_width = self.request.min_width if self.request.min_width > 0 else DEFAULT_MIN_WIDTH
            min_height = self.request.min_height if self.request.min_height > 0 else DEFAULT_MIN_HEIGHT
            min_bytes = self.request.min_bytes if self.request.min_bytes > 0 else DEFAULT_MIN_BYTES
            if candidate.width and candidate.height:
                if candidate.width < min_width or candidate.height < min_height:
                    logger.info("Pre-filter: Skipping %s due to low resolution (%dx%d)", 
                               candidate.url, candidate.width, candidate.height)
                    return None
            if candidate.byte_size and candidate.byte_size < min_bytes:
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
                            if byte_size < min_bytes:
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
            supabase_url = self.supabase_url()
            public_url = f"{supabase_url}/storage/v1/object/public/{self.supabase_bucket}/{destination}"
            
            try:
                response = self.supabase.storage.from_(self.supabase_bucket).upload(
                    path=destination,
                    file=image_bytes,
                    file_options={"contentType": content_type},
                )
                if isinstance(response, dict) and response.get("error"):
                    error_msg = str(response["error"]).lower()
                    # Handle "object already exists" - reuse existing storage object
                    if "duplicate" in error_msg or "exists" in error_msg or "already" in error_msg:
                        logger.info("Storage object already exists, reusing: %s", destination)
                        return public_url
                    raise RuntimeError(str(response["error"]))
            except Exception as exc:
                error_msg = str(exc).lower()
                # Handle "object already exists" exception
                if "duplicate" in error_msg or "exists" in error_msg or "already" in error_msg:
                    logger.info("Storage object already exists, reusing: %s", destination)
                    return public_url
                raise
            
            return public_url

        return await asyncio.to_thread(_upload)

    def supabase_url(self) -> str:
        config = self.request.supabase_config
        if config is None:
            raise RuntimeError("Supabase URL requested but Supabase is disabled")
        return config.url.rstrip("/")

    async def _find_existing_image(
        self, candidate: ImageCandidate
    ) -> Optional[Dict[str, Any]]:
        """Look up an existing image record by original_url to avoid duplicate uploads."""
        if self.supabase is None or not self.supabase_table:
            return None

        def _lookup() -> Optional[Dict[str, Any]]:
            table = self.supabase.table(self.supabase_table)
            original_urls = [candidate.url]
            if candidate.context_url and candidate.context_url != candidate.url:
                original_urls.append(candidate.context_url)
            for original_url in original_urls:
                existing = (
                    table.select("id,image_url,original_url")
                    .eq("original_url", original_url)
                    .limit(1)
                    .execute()
                )
                existing_data = getattr(existing, "data", None) or []
                if existing_data:
                    return existing_data[0]
            return None

        return await asyncio.to_thread(_lookup)

    async def _record_image(self, public_url: str, candidate: ImageCandidate) -> Optional[Dict[str, Any]]:
        if self.supabase is None or not self.supabase_table:
            raise RuntimeError("Supabase persistence is not configured")

        def _upsert() -> Optional[Dict[str, Any]]:
            payload = {
                "image_url": public_url,
                "original_url": candidate.url,
                "author": candidate.author or "",
                "source": candidate.source or "",
            }
            table = self.supabase.table(self.supabase_table)
            
            # Use upsert to handle race conditions - requires unique constraint on original_url
            try:
                response = table.upsert(
                    payload,
                    on_conflict="original_url"
                ).execute()
                data = getattr(response, "data", None) or []
                if data:
                    return data[0]
            except Exception as upsert_exc:
                # Fallback to insert + duplicate handling if upsert fails
                # (e.g., if unique constraint doesn't exist yet)
                logger.debug("Upsert failed, falling back to insert: %s", upsert_exc)
                response = table.insert(payload).execute()
                error = getattr(response, "error", None)
                if error:
                    message = str(error).lower()
                    if "duplicate" in message or "unique" in message:
                        existing = (
                            table.select("id,image_url,original_url")
                            .eq("original_url", payload["original_url"])
                            .limit(1)
                            .execute()
                        )
                        existing_data = getattr(existing, "data", None) or []
                        if existing_data:
                            logger.info("Reusing existing image record for %s", payload["original_url"])
                            return existing_data[0]
                    raise RuntimeError(error)  # type: ignore[arg-type]
                data = getattr(response, "data", None) or []
                if data:
                    return data[0]
            
            # Final fallback: try to fetch the record
            existing = (
                table.select("id,image_url,original_url")
                .eq("original_url", payload["original_url"])
                .limit(1)
                .execute()
            )
            existing_data = getattr(existing, "data", None) or []
            if existing_data:
                return existing_data[0]
            return payload

        return await asyncio.to_thread(_upsert)

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
        """Build a deterministic storage path based on URL hash.
        
        Uses MD5 hash only (no timestamp) to ensure the same original URL
        always maps to the same storage path, enabling deduplication.
        """
        digest = hashlib.md5(original_url.encode("utf-8")).hexdigest()
        path = PurePosixPath("public") / digest
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
