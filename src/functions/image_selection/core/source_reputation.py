"""Source reputation scoring for image domains.

This module provides quality scores for image sources to prioritize
trusted editorial sources over generic aggregators.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Trusted sources with high-quality editorial content
TRUSTED_SOURCES = {
    # Wire services
    "apnews.com": 1.0,
    "reuters.com": 1.0,
    "afp.com": 0.95,
    # Official NFL
    "nfl.com": 0.95,
    "nflcdn.com": 0.95,
    # Major sports networks
    "espn.com": 0.85,
    "cbssports.com": 0.80,
    "nbcsports.com": 0.80,
    "foxsports.com": 0.80,
    "sportingnews.com": 0.75,
    "usatoday.com": 0.75,
    "theringer.com": 0.75,
    "theathletic.com": 0.80,
    # Team sites (via CDN)
    "static.clubs.nfl.com": 0.90,
    # Commons/Public domain
    "commons.wikimedia.org": 0.75,
    "upload.wikimedia.org": 0.75,
    # Quality news outlets
    "nytimes.com": 0.85,
    "washingtonpost.com": 0.85,
    "latimes.com": 0.80,
}

# Untrusted/low-quality sources
UNTRUSTED_SOURCES = {
    "blogspot.com": 0.2,
    "wordpress.com": 0.3,
    "medium.com": 0.3,
    "tumblr.com": 0.2,
    "pinterest.com": 0.1,
    "reddit.com": 0.2,
    "i.redd.it": 0.2,
}


def get_source_score(domain: str) -> float:
    """Return reputation score for a domain (0.0-1.0).
    
    Higher scores indicate more trustworthy sources with
    high-quality editorial content.
    
    Args:
        domain: The domain name to score.
        
    Returns:
        Float between 0.0 and 1.0, where 1.0 is most trusted.
    """
    domain = domain.lower().lstrip("www.")
    
    # Check exact match first
    if domain in TRUSTED_SOURCES:
        return TRUSTED_SOURCES[domain]
    if domain in UNTRUSTED_SOURCES:
        return UNTRUSTED_SOURCES[domain]
    
    # Check subdomain matches (e.g., static.espn.com -> espn.com)
    for trusted, score in TRUSTED_SOURCES.items():
        if domain.endswith("." + trusted):
            return score * 0.9  # Slight penalty for subdomains
    
    for untrusted, score in UNTRUSTED_SOURCES.items():
        if domain.endswith("." + untrusted):
            return score
    
    # Neutral default for unknown sources
    return 0.5


def get_source_score_from_url(url: str) -> float:
    """Extract domain from URL and return reputation score.
    
    Args:
        url: Full URL to extract domain from.
        
    Returns:
        Float between 0.0 and 1.0.
    """
    try:
        domain = urlparse(url).netloc
        return get_source_score(domain)
    except Exception:
        return 0.5


def is_trusted_source(url: str, threshold: float = 0.7) -> bool:
    """Check if a URL is from a trusted source.
    
    Args:
        url: Full URL to check.
        threshold: Minimum score to be considered trusted.
        
    Returns:
        True if the source score is at or above the threshold.
    """
    return get_source_score_from_url(url) >= threshold
