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
    "nfl.com": 1.0,
    "nflcdn.com": 1.0,
    # Major sports networks
    "espn.com": 1.0,
    "si.com": 0.80,
    "bleacherreport.com": 0.80,
    "profootballtalk.com": 1.0,
    "sbnation.com": 0.78,
    "on3.com": 0.75,
    "yahoo.com": 0.75,
    "sports.yahoo.com": 0.78,
    "cbssports.com": 1.0,
    "nbcsports.com": 1.0,
    "foxsports.com": 1.0,
    "sportingnews.com": 0.75,
    "usatoday.com": 1.0,
    "theringer.com": 0.75,
    "theathletic.com": 1.0,
    # Team sites (via CDN)
    "static.clubs.nfl.com": 0.90,
    # Team sites (all 32)
    "azcardinals.com": 1.0,
    "atlantafalcons.com": 1.0,
    "baltimoreravens.com": 1.0,
    "buffalobills.com": 1.0,
    "panthers.com": 1.0,
    "chicagobears.com": 1.0,
    "bengals.com": 1.0,
    "clevelandbrowns.com": 1.0,
    "dallascowboys.com": 1.0,
    "denverbroncos.com": 1.0,
    "detroitlions.com": 1.0,
    "packers.com": 1.0,
    "houstontexans.com": 1.0,
    "colts.com": 1.0,
    "jaguars.com": 1.0,
    "chiefs.com": 1.0,
    "raiders.com": 1.0,
    "chargers.com": 1.0,
    "therams.com": 1.0,
    "miamidolphins.com": 1.0,
    "vikings.com": 1.0,
    "patriots.com": 1.0,
    "neworleanssaints.com": 1.0,
    "giants.com": 1.0,
    "newyorkjets.com": 1.0,
    "philadelphiaeagles.com": 1.0,
    "steelers.com": 1.0,
    "49ers.com": 1.0,
    "seahawks.com": 1.0,
    "buccaneers.com": 1.0,
    "titansonline.com": 1.0,
    "commanders.com": 1.0,
    # Commons/Public domain
    "commons.wikimedia.org": 0.75,
    "upload.wikimedia.org": 0.75,
    # Quality news outlets
    "nytimes.com": 0.95,
    "newyorker.com": 0.95,
    "washingtonpost.com": 0.95,
    "latimes.com": 0.90,
    "wsj.com": 0.95,
    "bloomberg.com": 0.80,
    "cnn.com": 1.0,
    "foxnews.com": 1.0,
    "nbcnews.com": 1.0,
    "abcnews.go.com": 0.75,
    "cbsnews.com": 0.75,
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
