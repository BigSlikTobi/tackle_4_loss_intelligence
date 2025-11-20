import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { NewsUrl, NewsDetail } from '../types'

export function useNewsList(
    page: number = 1,
    pageSize: number = 50,
    sortBy: string = 'publication_date',
    sortOrder: 'asc' | 'desc' = 'desc'
) {
    const [news, setNews] = useState<NewsUrl[]>([])
    const [totalCount, setTotalCount] = useState<number>(0)
    const [totalFacts, setTotalFacts] = useState<number>(0)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        async function fetchNews() {
            try {
                setLoading(true)
                const from = (page - 1) * pageSize
                const to = from + pageSize - 1

                const { data, error, count } = await supabase
                    .from('news_urls')
                    .select('*, news_facts!inner(id)', { count: 'exact' })
                    .order(sortBy, { ascending: sortOrder === 'asc' })
                    .range(from, to)

                if (error) throw error

                // Fetch total facts count
                const { count: factsCount, error: factsError } = await supabase
                    .from('news_facts')
                    .select('*', { count: 'exact', head: true })

                if (factsError) console.error('Error fetching facts count:', factsError)

                // Calculate facts_count from the returned news_facts array
                const transformedData = (data || []).map((item: any) => ({
                    ...item,
                    facts_count: item.news_facts ? item.news_facts.length : 0
                }))

                setNews(transformedData)
                if (count !== null) setTotalCount(count)
                if (factsCount !== null) setTotalFacts(factsCount)
            } catch (err: any) {
                setError(err.message)
            } finally {
                setLoading(false)
            }
        }

        fetchNews()
    }, [page, pageSize, sortBy, sortOrder])

    return { news, totalCount, totalFacts, loading, error }
}

export function useNewsDetail(id: string) {
    const [newsDetail, setNewsDetail] = useState<NewsDetail | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!id) return

        async function fetchDetail() {
            try {
                setLoading(true)
                // Fetch URL details
                const { data: urlData, error: urlError } = await supabase
                    .from('news_urls')
                    .select('*')
                    .eq('id', id)
                    .single()

                if (urlError) throw urlError

                // Fetch facts with nested entities and topics
                // Note: Supabase JS might require specific syntax for deep nesting depending on foreign key names.
                // We'll try to fetch facts and then manually fetch children if deep select is tricky, 
                // but standard deep select should work: news_facts(*, news_fact_entities(*), news_fact_topics(*))

                const { data: factsData, error: factsError } = await supabase
                    .from('news_facts')
                    .select(`
            *,
            entities:news_fact_entities(*),
            topics:news_fact_topics(*)
          `)
                    .eq('news_url_id', id)

                if (factsError) throw factsError

                const fullDetail: NewsDetail = {
                    ...urlData,
                    facts: factsData || []
                }

                setNewsDetail(fullDetail)
            } catch (err: any) {
                console.error('Error fetching news detail:', err)
                setError(err.message)
            } finally {
                setLoading(false)
            }
        }

        fetchDetail()
    }, [id])

    return { newsDetail, loading, error }
}
