"""
Test data fixtures for integration testing.

Provides sample data for testing the full daily team update pipeline.
"""

from typing import Dict, List, Any

# Sample team data
SAMPLE_TEAMS = [
    {
        "id": "test-team-1",
        "name": "Kansas City Chiefs",
        "abbreviation": "KC",
        "location": "Kansas City",
        "conference": "AFC",
        "division": "West"
    },
    {
        "id": "test-team-2",
        "name": "San Francisco 49ers",
        "abbreviation": "SF",
        "location": "San Francisco",
        "conference": "NFC",
        "division": "West"
    }
]

# Sample news URLs
SAMPLE_NEWS_URLS = {
    "KC": [
        "https://example.com/chiefs-practice-report",
        "https://example.com/mahomes-interview",
        "https://example.com/chiefs-defense-analysis"
    ],
    "SF": [
        "https://example.com/49ers-injury-update",
        "https://example.com/purdy-preparation"
    ]
}

# Sample extracted content
SAMPLE_EXTRACTED_CONTENT = [
    {
        "url": "https://example.com/chiefs-practice-report",
        "title": "Chiefs Return to Practice with Full Roster",
        "description": "Kansas City Chiefs held full practice on Wednesday",
        "content": """Patrick Mahomes and the Kansas City Chiefs returned to practice Wednesday with 
        a full roster for the first time in three weeks. The quarterback looked sharp in 11-on-11 drills, 
        completing 15 of 17 passes. Defensive coordinator Steve Spagnuolo praised the team's preparation. 
        "We're getting everybody healthy at the right time," coach Andy Reid said.""",
        "paragraphs": [
            "Patrick Mahomes and the Kansas City Chiefs returned to practice Wednesday with a full roster.",
            "The quarterback looked sharp in 11-on-11 drills, completing 15 of 17 passes.",
            "Defensive coordinator Steve Spagnuolo praised the team's preparation.",
            "We're getting everybody healthy at the right time, coach Andy Reid said."
        ],
        "author": "John Smith",
        "publish_date": "2025-10-28T10:00:00Z",
        "images": ["https://example.com/mahomes.jpg"],
        "quotes": ["We're getting everybody healthy at the right time"],
        "tags": ["Chiefs", "Practice", "Mahomes"],
        "extraction_strategy": "playwright",
        "extraction_time_ms": 2500
    },
    {
        "url": "https://example.com/mahomes-interview",
        "title": "Mahomes: 'We're Ready for Anything'",
        "description": "Patrick Mahomes discusses upcoming game",
        "content": """Patrick Mahomes addressed media Tuesday, expressing confidence in the team's 
        preparation. "We're ready for anything they throw at us," Mahomes said. The two-time MVP 
        has thrown for 2,500 yards this season with a 68% completion rate. Travis Kelce echoed 
        his quarterback's confidence: "This team knows how to win.""",
        "paragraphs": [
            "Patrick Mahomes addressed media Tuesday, expressing confidence in the team's preparation.",
            "We're ready for anything they throw at us, Mahomes said.",
            "The two-time MVP has thrown for 2,500 yards this season with a 68% completion rate.",
            "Travis Kelce echoed his quarterback's confidence: This team knows how to win."
        ],
        "author": "Jane Doe",
        "publish_date": "2025-10-27T15:30:00Z",
        "images": ["https://example.com/mahomes-presser.jpg"],
        "quotes": ["We're ready for anything they throw at us", "This team knows how to win"],
        "tags": ["Chiefs", "Mahomes", "Interview"],
        "extraction_strategy": "light",
        "extraction_time_ms": 450
    }
]

# Sample summaries
SAMPLE_SUMMARIES = [
    {
        "content": """Patrick Mahomes and the Kansas City Chiefs held full practice Wednesday, 
        marking the first complete roster in three weeks. Mahomes completed 15 of 17 passes 
        in 11-on-11 drills. Head coach Andy Reid noted the team is "getting everybody healthy 
        at the right time." Defensive coordinator Steve Spagnuolo praised preparation levels.""",
        "source_article_id": "article-1",
        "word_count": 52,
        "key_quotes": ["getting everybody healthy at the right time"],
        "topics": ["practice", "health", "preparation"],
        "processing_time_ms": 3200,
        "tokens_used": 180
    },
    {
        "content": """Patrick Mahomes expressed confidence Tuesday about the Chiefs' readiness. 
        "We're ready for anything they throw at us," said Mahomes, who has 2,500 passing yards 
        this season with 68% completion. Travis Kelce reinforced his quarterback's optimism, 
        stating "this team knows how to win.""",
        "source_article_id": "article-2",
        "word_count": 48,
        "key_quotes": ["We're ready for anything they throw at us", "this team knows how to win"],
        "topics": ["confidence", "quarterback", "statistics"],
        "processing_time_ms": 2800,
        "tokens_used": 165
    }
]

# Sample generated article
SAMPLE_GENERATED_ARTICLE = {
    "headline": "Chiefs Embrace Full Health as Playoffs Approach",
    "sub_header": "Mahomes leads confident squad through crucial practice week",
    "introduction_paragraph": """The Kansas City Chiefs returned to full strength this week, 
    conducting their first complete practice in three weeks with Patrick Mahomes and the entire 
    roster healthy. The two-time MVP quarterback demonstrated his characteristic precision while 
    his teammates rallied around a message of readiness and confidence.""",
    "content": [
        """Wednesday's practice session showed a team hitting its stride at the perfect moment. 
        Mahomes completed 15 of 17 passes in 11-on-11 drills, displaying the accuracy that has 
        defined his 2,500-yard season with a 68% completion rate. Head coach Andy Reid expressed 
        satisfaction with the timing, noting the team is getting everybody healthy at the right time.""",
        """The quarterback's confidence was evident in Tuesday's media session. We're ready for 
        anything they throw at us, Mahomes declared, a sentiment echoed by tight end Travis Kelce. 
        This team knows how to win, Kelce added, referencing their championship pedigree.""",
        """Defensive coordinator Steve Spagnuolo praised the preparation levels across the roster, 
        suggesting the Chiefs are peaking as the season's most critical games approach. The 
        combination of full health and veteran confidence positions Kansas City as a formidable 
        force heading into the playoffs."""
    ],
    "central_theme": "team_preparation",
    "word_count": 185,
    "tokens_used": 850,
    "processing_time_ms": 18500
}

# Sample translated article
SAMPLE_TRANSLATED_ARTICLE = {
    "language": "de",
    "headline": "Chiefs begrüßen volle Gesundheit mit Blick auf Playoffs",
    "sub_header": "Mahomes führt selbstbewusstes Team durch entscheidende Trainingswoche",
    "introduction_paragraph": """Die Kansas City Chiefs kehrten diese Woche zu voller 
    Stärke zurück und absolvierten ihr erstes komplettes Training seit drei Wochen mit 
    Patrick Mahomes und dem gesamten Kader gesund. Der zweifache MVP-Quarterback zeigte 
    seine charakteristische Präzision, während seine Teamkollegen eine Botschaft der 
    Bereitschaft und des Selbstvertrauens vermittelten.""",
    "content": [
        """Die Trainingseinheit am Mittwoch zeigte ein Team, das zum perfekten Zeitpunkt 
        seinen Rhythmus findet. Mahomes verwandelte 15 von 17 Pässen in 11-gegen-11-Übungen 
        und demonstrierte die Genauigkeit, die seine 2.500-Yard-Saison mit 68% Completion-Rate 
        definiert. Head Coach Andy Reid äußerte Zufriedenheit über das Timing und bemerkte, 
        das Team werde zum richtigen Zeitpunkt wieder gesund.""",
        """Das Selbstvertrauen des Quarterbacks war bei der Medienkonferenz am Dienstag 
        deutlich spürbar. Wir sind bereit für alles, was sie uns entgegenwerfen, erklärte 
        Mahomes, eine Stimmung, die Tight End Travis Kelce teilte. Dieses Team weiß, wie 
        man gewinnt, fügte Kelce hinzu und verwies auf ihr Championship-Erbe.""",
        """Defensive Coordinator Steve Spagnuolo lobte das Vorbereitungsniveau im gesamten 
        Kader und deutete an, dass die Chiefs ihren Höhepunkt erreichen, während die 
        wichtigsten Spiele der Saison näher rücken. Die Kombination aus voller Gesundheit 
        und Veteranen-Selbstvertrauen positioniert Kansas City als beeindruckende Kraft 
        mit Blick auf die Playoffs."""
    ],
    "preserved_terms": ["Kansas City Chiefs", "Patrick Mahomes", "Andy Reid", "Travis Kelce", 
                        "Steve Spagnuolo", "MVP", "Quarterback", "Tight End", "Head Coach", 
                        "Defensive Coordinator", "Playoffs"],
    "processing_time_ms": 12300,
    "tokens_used": 920
}

def get_sample_team(abbreviation: str = "KC") -> Dict[str, Any]:
    """Get a sample team by abbreviation."""
    for team in SAMPLE_TEAMS:
        if team["abbreviation"] == abbreviation:
            return team
    return SAMPLE_TEAMS[0]

def get_sample_urls(team_abbr: str = "KC") -> List[str]:
    """Get sample URLs for a team."""
    return SAMPLE_NEWS_URLS.get(team_abbr, SAMPLE_NEWS_URLS["KC"])

def get_sample_extracted_content() -> List[Dict[str, Any]]:
    """Get sample extracted content."""
    return SAMPLE_EXTRACTED_CONTENT.copy()

def get_sample_summaries() -> List[Dict[str, Any]]:
    """Get sample summaries."""
    return SAMPLE_SUMMARIES.copy()

def get_sample_article() -> Dict[str, Any]:
    """Get sample generated article."""
    return SAMPLE_GENERATED_ARTICLE.copy()

def get_sample_translation() -> Dict[str, Any]:
    """Get sample translated article."""
    return SAMPLE_TRANSLATED_ARTICLE.copy()
