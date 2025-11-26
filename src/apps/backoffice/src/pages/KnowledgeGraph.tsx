import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph3D from 'react-force-graph-3d'
import type { ForceGraphMethods } from 'react-force-graph-3d'
import * as THREE from 'three'
import { CalendarClock, Compass, Globe2, Loader2, Moon, Network, RefreshCcw, Sparkles, SunMedium, Users } from 'lucide-react'
import { useKnowledgeGraph } from '../hooks/useKnowledgeGraph'
import type { GameSummary, KnowledgeGraphResponse, PlayerProfile, TeamNode, TeamTopic } from '../types'

// Supabase storage bucket base URL for logos
const LOGO_BUCKET_URL = 'https://yqtiuzhedkfacwgormhn.supabase.co/storage/v1/object/public/team_logos'

// Logo URLs for NFL and conferences
const LEAGUE_LOGOS: Record<string, string> = {
  'NFL': `${LOGO_BUCKET_URL}/nfl.png`,
  'AFC': `${LOGO_BUCKET_URL}/afc.png`,
  'NFC': `${LOGO_BUCKET_URL}/nfc.png`,
}

const CONFERENCE_COLORS: Record<string, string> = {
  'AFC': '#d50a0a',  // AFC Red
  'NFC': '#013369',  // NFC Blue
}

const NFL_COLOR = '#013369' // NFL Blue

// Positions for conferences (left/right of center)
const CONFERENCE_POSITIONS: Record<string, { x: number; z: number }> = {
  'NFC': { x: -80, z: 0 },
  'AFC': { x: 80, z: 0 },
}

// Positions for divisions relative to their conference
const DIVISION_OFFSETS: Record<string, { x: number; y: number; z: number }> = {
  'East': { x: 60, y: 40, z: 0 },
  'North': { x: 60, y: -40, z: 0 },
  'South': { x: 30, y: 40, z: 50 },
  'West': { x: 30, y: -40, z: 50 },
}

type GraphNode = {
  id: string
  type: 'league' | 'conference' | 'division' | 'team'
  label: string
  division?: string
  conference?: string
  logo_url?: string | null
  color?: string | null
  x?: number
  y?: number
  z?: number
  fx?: number
  fy?: number
  fz?: number
  team?: TeamNode
}

type GraphLink = { source: string; target: string }

type GraphData = { nodes: GraphNode[]; links: GraphLink[] }

function buildGraphData(teams: TeamNode[]): GraphData {
  const nodes: GraphNode[] = [
    { id: 'NFL', type: 'league', label: 'NFL', fx: 0, fy: 0, fz: 0, color: '#22c55e' }
  ]
  const links: GraphLink[] = []
  
  // Group teams by conference and division
  const conferences = new Map<string, Map<string, TeamNode[]>>()
  
  teams.forEach(team => {
    const conference = team.conference || 'Unknown'
    const division = team.division || 'Unknown' // This is the full division name like "AFC East"
    
    if (!conferences.has(conference)) {
      conferences.set(conference, new Map())
    }
    const divisionMap = conferences.get(conference)!
    if (!divisionMap.has(division)) {
      divisionMap.set(division, [])
    }
    divisionMap.get(division)!.push(team)
  })

  // Add conference nodes
  conferences.forEach((divisions, conference) => {
    const confPos = CONFERENCE_POSITIONS[conference] || { x: 0, z: 0 }
    const confColor = CONFERENCE_COLORS[conference] || '#1c3529'
    
    nodes.push({
      id: conference,
      type: 'conference',
      label: conference,
      conference,
      fx: confPos.x,
      fy: 0,
      fz: confPos.z,
      color: confColor,
    })
    links.push({ source: 'NFL', target: conference })

    // Add division nodes
    divisions.forEach((divisionTeams, divisionFullName) => {
      // Extract short division name (East, North, South, West) from full name
      const divisionShort = divisionFullName.replace('AFC ', '').replace('NFC ', '')
      const divOffset = DIVISION_OFFSETS[divisionShort] || { x: 50, y: 0, z: 0 }
      
      // Mirror x offset for NFC (left side)
      const xMultiplier = conference === 'NFC' ? -1 : 1
      
      const divX = confPos.x + (divOffset.x * xMultiplier)
      const divY = divOffset.y
      const divZ = confPos.z + divOffset.z
      
      nodes.push({
        id: divisionFullName,
        type: 'division',
        label: divisionShort,
        conference,
        division: divisionShort,
        fx: divX,
        fy: divY,
        fz: divZ,
        color: '#1c3529',
      })
      links.push({ source: conference, target: divisionFullName })

      // Add team nodes orbiting around the division
      const orbitRadius = 25
      divisionTeams.forEach((team, index) => {
        const angle = (2 * Math.PI * index) / divisionTeams.length
        const teamX = divX + orbitRadius * Math.cos(angle)
        const teamY = divY + orbitRadius * Math.sin(angle) * 0.5
        const teamZ = divZ + orbitRadius * Math.sin(angle) * 0.5

        nodes.push({
          id: team.team_abbr,
          type: 'team',
          label: team.team_name || team.team_abbr,
          conference,
          division: divisionShort,
          logo_url: team.logo_url,
          color: team.primary_color || '#22c55e',
          fx: teamX,
          fy: teamY,
          fz: teamZ,
          team,
        })
        links.push({ source: divisionFullName, target: team.team_abbr })
      })
    })
  })

  return { nodes, links }
}

function nodeRenderer(theme: 'dark' | 'light') {
  // Use a simple approach: colored spheres with text overlays rendered via CSS
  // The 3D graph will show spheres, labels show on hover
  
  const createColoredSphere = (color: string, radius: number) => {
    const geometry = new THREE.SphereGeometry(radius, 32, 32)
    const material = new THREE.MeshLambertMaterial({
      color: new THREE.Color(color),
      transparent: false,
    })
    return new THREE.Mesh(geometry, material)
  }

  // Create a sprite with text/logo drawn on canvas
  const createLabelSprite = (text: string, bgColor: string, size: number, logoUrl?: string) => {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')!
    canvas.width = 128
    canvas.height = 128
    
    // Draw circular background
    ctx.beginPath()
    ctx.arc(64, 64, 60, 0, Math.PI * 2)
    ctx.fillStyle = bgColor
    ctx.fill()
    ctx.strokeStyle = '#ffffff'
    ctx.lineWidth = 3
    ctx.stroke()
    
    // Draw text
    ctx.fillStyle = '#ffffff'
    ctx.font = 'bold 32px Arial'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(text, 64, 64)
    
    const texture = new THREE.CanvasTexture(canvas)
    texture.needsUpdate = true
    
    const spriteMaterial = new THREE.SpriteMaterial({ 
      map: texture,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    })
    const sprite = new THREE.Sprite(spriteMaterial)
    sprite.scale.set(size, size, 1)
    
    // If logo URL provided, load it and update the sprite
    if (logoUrl) {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => {
        // Clear and redraw with image
        ctx.clearRect(0, 0, 128, 128)
        ctx.drawImage(img, 4, 4, 120, 120)
        texture.needsUpdate = true
      }
      img.onerror = () => {
        console.warn('Failed to load logo:', logoUrl)
      }
      img.src = logoUrl
    }
    
    return sprite
  }

  return (node: GraphNode) => {
    // NFL node
    if (node.type === 'league') {
      return createLabelSprite('NFL', '#013369', 30, LEAGUE_LOGOS['NFL'])
    }

    // Conference nodes
    if (node.type === 'conference') {
      const color = node.conference === 'AFC' ? '#d50a0a' : '#013369'
      return createLabelSprite(node.label, color, 24, LEAGUE_LOGOS[node.label])
    }

    // Division nodes
    if (node.type === 'division') {
      return createLabelSprite(node.label.charAt(0), '#1c3529', 12)
    }

    // Team nodes
    if (node.type === 'team') {
      return createLabelSprite(node.id, node.color || '#22c55e', 16, node.logo_url || undefined)
    }

    // Default
    return createColoredSphere('#1c3529', 4)
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
              <span className="legend-item"><span style={{ width: 10, height: 10, borderRadius: '50%', background: '#22c55e', display: 'inline-block' }}></span> NFL</span>
              <span className="legend-item"><span style={{ width: 10, height: 10, borderRadius: '50%', background: '#013369', display: 'inline-block' }}></span> NFC</span>
              <span className="legend-item"><span style={{ width: 10, height: 10, borderRadius: '50%', background: '#d50a0a', display: 'inline-block' }}></span> AFC</span>
              <span className="legend-item"><span style={{ width: 10, height: 10, borderRadius: '50%', background: '#1c3529', display: 'inline-block' }}></span> Divisions</span>
              <span className="legend-item"><Sparkles size={14} /> Teams</span>
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
              nodeThreeObjectExtend={false}
              linkColor={() => theme === 'dark' ? '#2c5c46' : '#4a7c5c'}
              linkOpacity={0.8}
              linkWidth={2}
              linkCurvature={0.15}
              showNavInfo={false}
              enableNodeDrag={false}
              warmupTicks={100}
              cooldownTicks={100}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.3}
              nodeLabel={(node: GraphNode) => {
                if (node.type === 'league') return 'NFL'
                if (node.type === 'conference') return `${node.conference} Conference`
                if (node.type === 'division') return `${node.conference} ${node.division}`
                return `${node.label}${node.conference ? ` • ${node.conference} ${node.division}` : ''}`
              }}
              onNodeClick={handleNodeClick as any}
              onEngineStop={() => {
                // Zoom to fit after the graph settles
                if (fgRef.current) {
                  fgRef.current.zoomToFit(400, 50)
                }
              }}
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
              <span className="chip"><Network size={14} /> 2 conferences</span>
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
