/// <reference path="./types.d.ts" />
import { createClient } from "https://esm.sh/v135/@supabase/supabase-js@2.43.1?target=deno";

type JsonValue = Record<string, unknown> | JsonValue[] | string | number | boolean | null;

type TeamRow = {
  team_abbr: string;
  team_name: string | null;
  team_conference: string | null;
  team_division: string | null;
  logo_url?: string | null;
  logo?: string | null;
  team_logo?: string | null;
  primary_color?: string | null;
  secondary_color?: string | null;
};

type PlayerRow = {
  player_id: string;
  display_name: string | null;
  position: string | null;
  headshot?: string | null;
  latest_team?: string | null;
  jersey_number?: number | null;
  birth_date?: string | null;
  height?: number | null;
  weight?: number | null;
  draft_year?: number | null;
  draft_round?: number | null;
  draft_pick?: number | null;
  years_of_experience?: number | null;
  college_name?: string | null;
};

type GameRow = {
  game_id: string;
  season: number | null;
  game_type?: string | null;
  week: number | null;
  gameday?: string | null;
  gametime?: string | null;
  home_team: string | null;
  away_team: string | null;
  home_score?: number | null;
  away_score?: number | null;
  location?: string | null;
  stadium?: string | null;
  result?: number | null;
};

type TopicRow = {
  id: string;
  fact_text: string;
  news_url_id: string;
  news_urls: {
    publication_date: string | null;
    title: string | null;
    url: string | null;
    source_name: string | null;
  } | null;
};

type GraphResponse = {
  generated_at: string;
  team_abbr: string | null;
  teams: Array<{
    team_abbr: string;
    team_name: string | null;
    conference: string | null;
    division: string | null;
    logo_url: string | null;
    primary_color: string | null;
    secondary_color: string | null;
  }>;
  players?: Array<PlayerRow & { display_name: string }>;
  games?: GameRow[];
  topics?: Array<{
    id: string;
    fact_text: string;
    news_url_id: string;
    publication_date: string | null;
    title: string | null;
    url: string | null;
    source_name: string | null;
  }>;
};

const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

if (!supabaseUrl || !serviceRoleKey) {
  throw new Error(
    "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables.",
  );
}

const supabase = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false },
});

function jsonResponse(body: JsonValue, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "content-type, authorization, apikey",
    },
  });
}

function handleOptions(): Response {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "content-type, authorization, apikey",
    },
  });
}

function normaliseLogo(row: TeamRow): string | null {
  return row.logo_url || row.logo || row.team_logo || null;
}

async function fetchTeams(): Promise<GraphResponse["teams"]> {
  const { data, error } = await supabase
    .from("teams")
    .select(
      "team_abbr,team_name,team_conference,team_division,logo_url,logo,team_logo,primary_color,secondary_color",
    )
    .order("team_conference", { ascending: true })
    .order("team_division", { ascending: true })
    .order("team_abbr", { ascending: true });

  if (error) {
    console.error("Failed to fetch teams", { error });
    throw new Error("Unable to fetch teams from Supabase.");
  }

  return (data || []).map((row: TeamRow) => ({
    team_abbr: row.team_abbr,
    team_name: row.team_name,
    conference: row.team_conference,
    division: row.team_division,
    logo_url: normaliseLogo(row),
    primary_color: row.primary_color ?? null,
    secondary_color: row.secondary_color ?? null,
  }));
}

async function fetchPlayers(teamAbbr: string): Promise<GraphResponse["players"]> {
  const players: GraphResponse["players"] = [];
  const pageSize = 500;
  let offset = 0;

  while (true) {
    const { data, error } = await supabase
      .from("players")
      .select(
        "player_id,display_name,position,headshot,latest_team,jersey_number,birth_date,height,weight,draft_year,draft_round,draft_pick,years_of_experience,college_name",
      )
      .eq("latest_team", teamAbbr)
      .order("display_name", { ascending: true })
      .range(offset, offset + pageSize - 1);

    if (error) {
      console.error("Failed to fetch players", { teamAbbr, error });
      throw new Error("Unable to fetch players for the requested team.");
    }

    if (!data || data.length === 0) break;

    players.push(...data.map((row: PlayerRow) => ({
      ...row,
      display_name: row.display_name || "Unknown player",
    })));

    if (data.length < pageSize) break;
    offset += pageSize;
  }

  return players;
}

async function fetchGames(teamAbbr: string): Promise<GameRow[]> {
  const { data, error } = await supabase
    .from("games")
    .select(
      "game_id,season,game_type,week,gameday,gametime,home_team,away_team,home_score,away_score,location,stadium,result",
    )
    .or(`home_team.eq.${teamAbbr},away_team.eq.${teamAbbr}`)
    .order("gameday", { ascending: false })
    .limit(64);

  if (error) {
    console.error("Failed to fetch games", { teamAbbr, error });
    throw new Error("Unable to fetch games for the requested team.");
  }

  return data || [];
}

async function fetchTopics(teamAbbr: string): Promise<GraphResponse["topics"]> {
  const { data: factLinks, error: linkError } = await supabase
    .from("news_fact_entities")
    .select("news_fact_id")
    .eq("entity_type", "team")
    .eq("entity_id", teamAbbr);

  if (linkError) {
    console.error("Failed to fetch fact links", { teamAbbr, linkError });
    throw new Error("Unable to fetch topics for the requested team.");
  }

  const factIds = Array.from(
    new Set((factLinks || []).map((row: { news_fact_id: string }) => row.news_fact_id)),
  );

  if (factIds.length === 0) return [];

  const sinceDate = new Date(Date.now() - 1000 * 60 * 60 * 24 * 2).toISOString();

  const { data, error } = await supabase
    .from("news_facts")
    .select(
      "id,fact_text,news_url_id,news_urls!inner(publication_date,title,url,source_name)",
    )
    .in("id", factIds)
    .gte("news_urls.publication_date", sinceDate)
    .order("news_urls.publication_date", { ascending: false })
    .limit(100);

  if (error) {
    console.error("Failed to fetch topics", { teamAbbr, error });
    throw new Error("Unable to fetch recent facts for the requested team.");
  }

  return (data || []).map((row: TopicRow) => ({
    id: row.id,
    fact_text: row.fact_text,
    news_url_id: row.news_url_id,
    publication_date: row.news_urls?.publication_date ?? null,
    title: row.news_urls?.title ?? null,
    url: row.news_urls?.url ?? null,
    source_name: row.news_urls?.source_name ?? null,
  }));
}

async function buildResponse(teamAbbr?: string | null): Promise<GraphResponse> {
  const teams = await fetchTeams();

  if (!teamAbbr) {
    return {
      generated_at: new Date().toISOString(),
      team_abbr: null,
      teams,
    };
  }

  const [players, games, topics] = await Promise.all([
    fetchPlayers(teamAbbr),
    fetchGames(teamAbbr),
    fetchTopics(teamAbbr),
  ]);

  return {
    generated_at: new Date().toISOString(),
    team_abbr: teamAbbr,
    teams,
    players,
    games,
    topics,
  };
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") return handleOptions();

  if (!["GET", "POST"].includes(req.method)) {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  try {
    const requestUrl = new URL(req.url);
    let teamAbbr: string | null = requestUrl.searchParams.get("team_abbr");

    if (req.method === "POST" && !teamAbbr) {
      const payload = await req.json().catch(() => null) as { team_abbr?: string } | null;
      if (payload?.team_abbr) {
        teamAbbr = payload.team_abbr;
      }
    }

    const responsePayload = await buildResponse(teamAbbr ? teamAbbr.toUpperCase() : null);
    return jsonResponse(responsePayload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unexpected server error.";
    console.error("Unexpected error in knowledge-graph", { message });
    return jsonResponse({ error: message }, 500);
  }
});
