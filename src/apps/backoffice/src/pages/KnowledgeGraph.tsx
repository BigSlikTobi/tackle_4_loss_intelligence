import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph3D, { ForceGraphMethods } from 'react-force-graph-3d'
import * as THREE from 'three'
import { CalendarClock, Compass, Globe2, Loader2, Moon, Network, RefreshCcw, Sparkles, SunMedium, Users } from 'lucide-react'
import { useKnowledgeGraph } from '../hooks/useKnowledgeGraph'
import type { GameSummary, KnowledgeGraphResponse, PlayerProfile, TeamNode, TeamTopic } from '../types'

const DIVISION_ANGLES: Record<string, number> = {
  'AFC East': Math.PI * 0.2,
  'AFC North': Math.PI * 0.4,
  'AFC South': Math.PI * 0.6,
  'AFC West': Math.PI * 0.8,
  'NFC East': -Math.PI * 0.2,
  'NFC North': -Math.PI * 0.4,
  'NFC South': -Math.PI * 0.6,
  'NFC West': -Math.PI * 0.8,
}

const DIVISION_LATITUDE: Record<string, number> = {
  East: 55,
  North: 20,
  South: -10,
  West: -45,
}

type GraphNode = {
  id: string
  type: 'league' | 'division' | 'team'
  label: string
  division?: string
  conference?: string
  logo_url?: string | null
  color?: string | null
  x?: number
  y?: number
  z?: number
  team?: TeamNode
}

type GraphLink = { source: string; target: string }

type GraphData = { nodes: GraphNode[]; links: GraphLink[] }

const metallicMaterial = (color: string, theme: 'dark' | 'light') => new THREE.MeshStandardMaterial({
  color,
  metalness: 0.8,
  roughness: theme === 'dark' ? 0.3 : 0.4,
  emissive: theme === 'dark' ? new THREE.Color('#0a251a') : new THREE.Color('#9ac7b0'),
})

function buildGraphData(teams: TeamNode[]): GraphData {
  const nodes: GraphNode[] = [
    { id: 'NFL', type: 'league', label: 'NFL', x: 0, y: 0, z: 0, color: '#22c55e' }
  ]
  const links: GraphLink[] = []
  const grouped = new Map<string, TeamNode[]>()

  teams.forEach(team => {
    const division = team.division || 'Unknown'
    const conference = team.conference || 'Unknown'
    const key = `${conference} ${division}`
    grouped.set(key, [...(grouped.get(key) || []), team])
  })

  const radius = 170

  grouped.forEach((groupTeams, key) => {
    const [conference, division] = key.split(' ')
    const lat = DIVISION_LATITUDE[division as keyof typeof DIVISION_LATITUDE] ?? 0
    const theta = DIVISION_ANGLES[key] ?? 0
    const phi = (90 - lat) * (Math.PI / 180)

    const divisionX = radius * Math.sin(phi) * Math.cos(theta)
    const divisionY = radius * Math.cos(phi)
    const divisionZ = radius * Math.sin(phi) * Math.sin(theta)

    nodes.push({
      id: key,
      type: 'division',
      label: key,
      conference,
      division,
      x: divisionX,
      y: divisionY,
      z: divisionZ,
      color: '#1c3529',
    })
    links.push({ source: 'NFL', target: key })

    const orbitRadius = 32
    groupTeams.forEach((team, index) => {
      const angle = (2 * Math.PI * index) / groupTeams.length
      const x = divisionX + orbitRadius * Math.cos(angle)
      const y = divisionY + orbitRadius * Math.sin(angle) * 0.25
      const z = divisionZ + orbitRadius * Math.sin(angle)

      nodes.push({
        id: team.team_abbr,
        type: 'team',
        label: team.team_name || team.team_abbr,
        conference,
        division,
        logo_url: team.logo_url,
        color: team.primary_color || '#22c55e',
        x,
        y,
        z,
        team,
      })
      links.push({ source: key, target: team.team_abbr })
    })
  })

  return { nodes, links }
}

function nodeRenderer(theme: 'dark' | 'light') {
  const textureCache = new Map<string, THREE.Texture>()
  const loader = new THREE.TextureLoader()

  return (node: GraphNode) => {
    if (node.type === 'team' && node.logo_url) {
      if (!textureCache.has(node.logo_url)) {
        textureCache.set(node.logo_url, loader.load(node.logo_url))
      }
      const material = new THREE.SpriteMaterial({ map: textureCache.get(node.logo_url)!, depthWrite: false })
      const sprite = new THREE.Sprite(material)
      sprite.scale.set(18, 18, 1)
      return sprite
    }

    const geometry = new THREE.SphereGeometry(node.type === 'division' ? 9 : 11, 32, 32)
    const material = metallicMaterial(node.color || '#1c3529', theme)
    return new THREE.Mesh(geometry, material)
  }
}

function formatGame(game: GameSummary, teamAbbr?: string | null) {
  const played = game.home_score != null && game.away_score != null
  const opponent = game.home_team === teamAbbr ? game.away_team : game.home_team
  const isHome = game.home_team === teamAbbr
  const score = played ? `${game.away_score ?? 0} - ${game.home_score ?? 0}` : 'TBD'
  const resultLabel = played ? (game.result ?? 0) > 0 ? 'Win' : (game.result ?? 0) < 0 ? 'Loss' : 'Draw' : 'Scheduled'

  return { opponent, isHome, score, resultLabel }
}

const formatDate = (value?: string | null) => value ? new Date(value).toLocaleDateString() : 'TBD'

export default function KnowledgeGraph() {
  const prefersDark = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
  const [theme, setTheme] = useState<'dark' | 'light'>(prefersDark ? 'dark' : 'light')
  const [activeTeam, setActiveTeam] = useState<string | null>(null)
  const { base, selectedTeam, loading, error } = useKnowledgeGraph(activeTeam)
  const fgRef = useRef<ForceGraphMethods>()

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const teams = useMemo(() => selectedTeam?.teams || base?.teams || [], [selectedTeam, base])
  const graphData = useMemo(() => buildGraphData(teams), [teams])
  const renderNode = useMemo(() => nodeRenderer(theme), [theme])

  useEffect(() => {
    if (!fgRef.current) return
    const controls = fgRef.current.controls()
    if (controls) {
      controls.autoRotate = true
      controls.autoRotateSpeed = 0.7
    }
    const scene = fgRef.current.scene()
    const lights = scene.children.filter(child => child.type === 'AmbientLight' || child.type === 'DirectionalLight')
    lights.forEach(light => scene.remove(light))

    const ambient = new THREE.AmbientLight(theme === 'dark' ? 0xc8e6d4 : 0x1f352b, 0.85)
    const directional = new THREE.DirectionalLight(theme === 'dark' ? 0x22c55e : 0x1b4332, theme === 'dark' ? 1.1 : 0.9)
    directional.position.set(80, 120, 160)
    scene.add(ambient, directional)
  }, [theme, graphData])

  const handleNodeClick = (node: GraphNode) => {
    if (node.type === 'team') {
      setActiveTeam(node.id)
    }
  }

  const activeTeamData: KnowledgeGraphResponse | undefined = selectedTeam && activeTeam ? selectedTeam : undefined

  return (
    <div className="graph-hero">
      <div className="ambient-card">
        <div className="flex items-center justify-between">
          <div>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Globe2 size={18} /> Visual Knowledge Graph
            </h1>
            <p>Dark-green metallic sphere with 360° rotation and expandable team intelligence.</p>
            <div className="graph-legend">
              <span className="legend-item"><span style={{ width: 10, height: 10, borderRadius: '50%', background: '#22c55e', display: 'inline-block' }}></span> NFL Core</span>
              <span className="legend-item"><span style={{ width: 10, height: 10, borderRadius: '50%', background: '#1c3529', display: 'inline-block' }}></span> Divisions</span>
              <span className="legend-item"><Sparkles size={14} /> Team Logos on Orbit</span>
            </div>
          </div>
          <button className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? <SunMedium size={16} /> : <Moon size={16} />} {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </div>

      <div className="graph-shell">
        <div className="graph-view" style={{ height: '70vh', borderRadius: '14px', overflow: 'hidden', border: `1px solid var(--border-default)` }}>
          {loading && !graphData.nodes.length ? (
            <div className="loading-state"><Loader2 className="icon-subtle" /> Loading graph...</div>
          ) : (
            <ForceGraph3D
              ref={fgRef}
              graphData={graphData}
              backgroundColor={theme === 'dark' ? '#050d0a' : '#f6fbf7'}
              nodeThreeObject={renderNode as any}
              linkColor={() => theme === 'dark' ? '#2c5c46' : '#6bb28f'}
              linkOpacity={0.7}
              linkWidth={1}
              linkCurvature={0.15}
              showNavInfo={false}
              enableNodeDrag={false}
              cooldownTicks={0}
              nodeLabel={(node: GraphNode) => `${node.label}${node.division ? ` • ${node.division}` : ''}`}
              onNodeClick={handleNodeClick as any}
            />
          )}
          <div className="graph-caption">Rotate freely, then click a team logo to expand players, games, and topics.</div>
        </div>

        <aside className="graph-panel">
          <div className="graph-toolbar">
            <div>
              <h2 style={{ marginBottom: 4 }}><Network size={16} /> Knowledge layers</h2>
              <small>Teams grouped by division — NFC on the left of the sphere, AFC on the right.</small>
            </div>
            <div className="chips">
              <span className="chip active"><Compass size={14} /> 32 teams</span>
              <span className="chip"><Globe2 size={14} /> 8 divisions</span>
            </div>
          </div>

          {error && <div className="error-state">{error}</div>}

          {!activeTeamData && (
            <div className="graph-card">
              <h3><Sparkles size={14} /> Start exploring</h3>
              <p style={{ margin: 0, color: 'var(--text-subtle)' }}>Select any team logo on the sphere to pull their roster, schedule, and fresh facts.</p>
            </div>
          )}

          {activeTeamData && activeTeam && (
            <>
              <div className="graph-card">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="flex items-center gap-2"><Compass size={14} /> {activeTeam}</h3>
                  <span className="team-badge"><span style={{ width: 8, height: 8, borderRadius: '50%', background: '#22c55e', display: 'inline-block' }}></span>{activeTeamData?.teams.find(t => t.team_abbr === activeTeam)?.division}</span>
                </div>
                <div className="meta-grid">
                  <div className="meta-pill">Players: {activeTeamData.players?.length ?? 0}</div>
                  <div className="meta-pill">Games: {activeTeamData.games?.length ?? 0}</div>
                  <div className="meta-pill">Topics: {activeTeamData.topics?.length ?? 0}</div>
                </div>
              </div>

              <div className="graph-card">
                <h3 className="flex items-center gap-2"><Users size={14} /> Players</h3>
                {loading && <div className="loading-state" style={{ height: 80 }}><Loader2 className="icon-subtle" /> Loading players...</div>}
                {!loading && (activeTeamData.players?.slice(0, 12) || []).map((player: PlayerProfile) => (
                  <div key={player.player_id} className="player-row">
                    <img src={player.headshot || 'https://placehold.co/96x96'} alt={player.display_name} className="player-avatar" crossOrigin="anonymous" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{player.display_name}</span>
                        {player.position && <span className="chip" style={{ padding: '2px 8px' }}>{player.position}</span>}
                        {player.jersey_number != null && <span className="chip" style={{ padding: '2px 8px' }}>#{player.jersey_number}</span>}
                      </div>
                      <div className="text-xs text-muted">{player.college_name || 'College TBC'} • Experience: {player.years_of_experience ?? 'n/a'} years</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="graph-card">
                <h3 className="flex items-center gap-2"><CalendarClock size={14} /> Games</h3>
                {loading && <div className="loading-state" style={{ height: 80 }}><Loader2 className="icon-subtle" /> Loading games...</div>}
                {!loading && (activeTeamData.games || []).slice(0, 8).map((game: GameSummary) => {
                  const meta = formatGame(game, activeTeam)
                  return (
                    <div key={game.game_id} className="game-row">
                      <div className="team-badge">{meta.isHome ? 'Home' : 'Away'} vs {meta.opponent}</div>
                      <div>
                        <div className="font-medium">Week {game.week ?? '?'} • {game.season}</div>
                        <div className="text-xs text-muted">{formatDate(game.gameday)} • {game.gametime || 'TBD'} • {game.stadium || game.location || 'TBC'}</div>
                        <div className="meta-grid" style={{ marginTop: 4 }}>
                          <span className="meta-pill">Score: {meta.score}</span>
                          <span className="meta-pill">Result: {meta.resultLabel}</span>
                          {game.game_type && <span className="meta-pill">{game.game_type}</span>}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="graph-card">
                <h3 className="flex items-center gap-2"><Sparkles size={14} /> Topics (last 2 days)</h3>
                {loading && <div className="loading-state" style={{ height: 80 }}><Loader2 className="icon-subtle" /> Loading topics...</div>}
                {!loading && (activeTeamData.topics || []).slice(0, 10).map((topic: TeamTopic) => (
                  <div key={topic.id} className="topic-row">
                    <div className="team-badge"><CalendarClock size={14} /> {formatDate(topic.publication_date)}</div>
                    <div>
                      <div className="font-medium" style={{ marginBottom: 4 }}>{topic.title || topic.fact_text.slice(0, 80)}</div>
                      <div className="text-sm" style={{ color: 'var(--text-subtle)' }}>{topic.fact_text}</div>
                      <div className="text-xs text-muted" style={{ marginTop: 4 }}>{topic.source_name || 'Source unknown'}</div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="graph-card">
            <h3 className="flex items-center gap-2"><RefreshCcw size={14} /> Data freshness</h3>
            <div className="text-sm">Teams pulled from Supabase teams table; players/games/topics load live per team using the new Edge Function.</div>
            <div className="text-xs text-muted" style={{ marginTop: 6 }}>Generated: {base?.generated_at ? new Date(base.generated_at).toLocaleString() : 'pending'}</div>
          </div>
        </aside>
      </div>
    </div>
  )
}
