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
