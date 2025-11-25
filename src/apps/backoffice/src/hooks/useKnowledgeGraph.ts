import { useCallback, useEffect, useMemo, useState } from 'react'
import { supabaseKey, supabaseUrl } from '../lib/supabase'
import type { KnowledgeGraphResponse } from '../types'

type GraphState = {
  base?: KnowledgeGraphResponse
  selectedTeam?: KnowledgeGraphResponse
  loading: boolean
  error?: string | null
}

const FUNCTION_NAME = 'knowledge-graph'

const buildFunctionUrl = (teamAbbr?: string) => {
  const base = `${supabaseUrl}/functions/v1/${FUNCTION_NAME}`
  if (!teamAbbr) return base
  const params = new URLSearchParams({ team_abbr: teamAbbr })
  return `${base}?${params.toString()}`
}

export function useKnowledgeGraph(teamAbbr?: string | null) {
  const [state, setState] = useState<GraphState>({ loading: true })

  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    apikey: supabaseKey,
    Authorization: `Bearer ${supabaseKey}`,
  }), [])

  const fetchBase = useCallback(async () => {
    const response = await fetch(buildFunctionUrl(), { headers })
    if (!response.ok) throw new Error(`Failed to fetch graph data: ${response.statusText}`)
    return (await response.json()) as KnowledgeGraphResponse
  }, [headers])

  const fetchTeam = useCallback(async (abbr: string) => {
    const response = await fetch(buildFunctionUrl(abbr), { headers })
    if (!response.ok) throw new Error(`Failed to fetch ${abbr} data: ${response.statusText}`)
    return (await response.json()) as KnowledgeGraphResponse
  }, [headers])

  useEffect(() => {
    let active = true
    setState(prev => ({ ...prev, loading: true, error: null }))

    const load = async () => {
      try {
        const base = await fetchBase()
        if (!active) return

        if (teamAbbr) {
          const selected = await fetchTeam(teamAbbr)
          if (!active) return
          setState({ base, selectedTeam: selected, loading: false, error: null })
        } else {
          setState({ base, selectedTeam: undefined, loading: false, error: null })
        }
      } catch (error: any) {
        if (!active) return
        setState(prev => ({ ...prev, loading: false, error: error?.message ?? 'Failed to load graph data' }))
      }
    }

    load()
    return () => { active = false }
  }, [teamAbbr, fetchBase, fetchTeam])

  const refreshTeam = useCallback(async (abbr: string) => {
    setState(prev => ({ ...prev, loading: true }))
    try {
      const [base, selectedTeam] = await Promise.all([
        fetchBase(),
        fetchTeam(abbr),
      ])
      setState({ base, selectedTeam, loading: false, error: null })
    } catch (error: any) {
      setState(prev => ({ ...prev, loading: false, error: error?.message ?? 'Failed to refresh graph data' }))
    }
  }, [fetchBase, fetchTeam])

  return {
    base: state.base,
    selectedTeam: state.selectedTeam,
    loading: state.loading,
    error: state.error,
    refreshTeam,
  }
}
