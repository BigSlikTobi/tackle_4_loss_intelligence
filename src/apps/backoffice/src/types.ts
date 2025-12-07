export interface NewsUrl {
    id: string
    url: string
    title: string | null
    description: string | null
    publication_date: string | null
    source_name: string | null
    publisher: string | null
    facts_count: number | null
    distinct_topics: number | null
    distinct_teams: number | null
}

export interface NewsFact {
    id: string
    news_url_id: string
    fact_text: string
    created_at: string
}

export interface NewsFactEntity {
    id: string
    news_fact_id: string
    entity_type: 'player' | 'team' | 'game'
    entity_id: string | null
    mention_text: string | null
    matched_name: string | null
    confidence: number | null
    is_primary: boolean
}

export interface NewsFactTopic {
    id: string
    news_fact_id: string
    topic: string
    canonical_topic: string
    confidence: number | null
    is_primary: boolean
}

export interface NewsDetail extends NewsUrl {
    facts: (NewsFact & {
        entities: NewsFactEntity[]
        topics: NewsFactTopic[]
    })[]
}

export interface TeamNode {
    team_abbr: string
    team_name: string | null
    conference: string | null
    division: string | null
    logo_url: string | null
    primary_color: string | null
    secondary_color: string | null
}

export interface PlayerProfile {
    player_id: string
    display_name: string
    position: string | null
    headshot?: string | null
    latest_team?: string | null
    jersey_number?: number | null
    birth_date?: string | null
    height?: number | null
    weight?: number | null
    draft_year?: number | null
    draft_round?: number | null
    draft_pick?: number | null
    years_of_experience?: number | null
    college_name?: string | null
}

export interface GameSummary {
    game_id: string
    season: number | null
    game_type?: string | null
    week: number | null
    gameday?: string | null
    gametime?: string | null
    home_team: string | null
    away_team: string | null
    home_score?: number | null
    away_score?: number | null
    location?: string | null
    stadium?: string | null
    result?: number | null
}

export interface TeamTopic {
    id: string
    fact_text: string
    news_url_id: string
    publication_date: string | null
    title: string | null
    url: string | null
    source_name: string | null
}

export interface KnowledgeGraphResponse {
    generated_at: string
    team_abbr: string | null
    teams: TeamNode[]
    players?: PlayerProfile[]
    games?: GameSummary[]
    topics?: TeamTopic[]
}
