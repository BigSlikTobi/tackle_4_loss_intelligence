// @ts-nocheck

import { createClient } from "https://esm.sh/v135/@supabase/supabase-js@2.43.1?target=deno";

const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

if (!supabaseUrl || !serviceRoleKey) {
  throw new Error(
    "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables.",
  );
}

const DEFAULT_MAX_URLS = getEnvNumber("TEAM_NEWS_MAX_URLS", 200, { min: 1 });
const DEFAULT_TIMEOUT_MS = getEnvNumber("TEAM_NEWS_TIMEOUT_MS", 10000, { min: 100 });
const DEFAULT_CONCURRENCY = getEnvNumber("TEAM_NEWS_CONCURRENCY", 4, {
  min: 1,
  max: 20,
});
const DEFAULT_LOOKBACK_HOURS = getEnvNumber("TEAM_NEWS_LOOKBACK_HOURS", 24, {
  min: 1,
  max: 168,
});
const DEFAULT_ENTITY_PAGE_SIZE = getEnvNumber("TEAM_NEWS_ENTITY_PAGE_SIZE", 1000, {
  min: 1,
  max: 1000,
});
const DEFAULT_GROUP_CHUNK_SIZE = getEnvNumber("TEAM_NEWS_GROUP_CHUNK_SIZE", 200, {
  min: 1,
});

const supabase = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false },
});

class HttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type JsonBody = Record<string, unknown> | unknown[];

type StoryEntityRow = { story_group_id: string | null };
type StoryGroupMemberRow = { news_url_id: string | null };
type NewsUrlRow = { id: string; url: string | null; created_at: string | null };
type UrlItem = { url: string; created_at: string | null };

function getEnvNumber(
  key: string,
  fallback: number,
  { min, max }: { min?: number; max?: number } = {},
): number {
  const raw = Deno.env.get(key);
  if (!raw) return fallback;

  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;

  const value = Math.floor(parsed);
  if (typeof min === "number" && value < min) return fallback;
  if (typeof max === "number" && value > max) return fallback;
  return value;
}

function jsonResponse(body: JsonBody, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function parsePositiveInt(
  name: string,
  raw: string | null,
  { defaultValue, min = 1, max }: { defaultValue: number; min?: number; max?: number },
): number {
  if (!raw) return defaultValue;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) {
    throw new HttpError(400, `Query parameter '${name}' must be a number.`);
  }
  if (!Number.isInteger(parsed)) {
    throw new HttpError(400, `Query parameter '${name}' must be an integer.`);
  }
  if (parsed < min) {
    throw new HttpError(400, `Query parameter '${name}' must be >= ${min}.`);
  }
  if (typeof max === "number" && parsed > max) {
    throw new HttpError(400, `Query parameter '${name}' must be <= ${max}.`);
  }
  return parsed;
}

function chunkArray<T>(items: T[], chunkSize: number): T[][] {
  if (!items.length) return [];
  const safeSize = Math.max(1, chunkSize);
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += safeSize) {
    chunks.push(items.slice(i, i + safeSize));
  }
  return chunks;
}

function normalizeUrl(raw: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;

  try {
    const url = new URL(trimmed);
    const protocol = url.protocol.toLowerCase();
    const hostname = url.hostname.toLowerCase();
    const port = url.port ? `:${url.port}` : "";
    const pathname = url.pathname || "/";
    return `${protocol}//${hostname}${port}${pathname}${url.search}${url.hash}`;
  } catch (_error) {
    return null;
  }
}

async function fetchStoryGroupIds(
  teamAbbr: string,
  signal: AbortSignal,
  cutoffIso: string,
): Promise<string[]> {
  const unique = new Set<string>();
  let offset = 0;

  while (true) {
    const upper = offset + DEFAULT_ENTITY_PAGE_SIZE - 1;
    const { data, error } = await supabase
      .from<StoryEntityRow>("story_entities")
      .select("story_group_id")
      .eq("entity_type", "team")
      .eq("entity_id", teamAbbr)
      .not("story_group_id", "is", null)
      .gte("extracted_at", cutoffIso)
      .range(offset, upper)
      .abortSignal(signal);

    if (error) {
      console.error("Failed to fetch story entities", error);
      throw new HttpError(500, `Failed to load story entities: ${error.message}`);
    }

    const rows = data ?? [];
    for (const row of rows) {
      if (row.story_group_id) {
        unique.add(row.story_group_id);
      }
    }

    if (rows.length < DEFAULT_ENTITY_PAGE_SIZE) {
      break;
    }
    offset += DEFAULT_ENTITY_PAGE_SIZE;
  }

  return Array.from(unique);
}

async function fetchStoryGroupMembers(
  groupIds: string[],
  signal: AbortSignal,
  cutoffIso: string,
): Promise<string[]> {
  if (!groupIds.length) return [];

  const unique = new Set<string>();
  const chunks = chunkArray(groupIds, DEFAULT_GROUP_CHUNK_SIZE);

  for (const chunk of chunks) {
    const { data, error } = await supabase
      .from<StoryGroupMemberRow>("story_group_members")
      .select("news_url_id")
      .in("group_id", chunk)
      .not("news_url_id", "is", null)
      .gte("added_at", cutoffIso)
      .abortSignal(signal);

    if (error) {
      console.error("Failed to fetch story group members", error);
      throw new HttpError(500, `Failed to load story group members: ${error.message}`);
    }

    const rows = data ?? [];
    for (const row of rows) {
      if (row.news_url_id) {
        unique.add(row.news_url_id);
      }
    }
  }

  return Array.from(unique);
}

async function fetchNewsUrls(
  newsUrlIds: string[],
  signal: AbortSignal,
  concurrency: number,
  cutoffIso: string,
): Promise<UrlItem[]> {
  if (!newsUrlIds.length) return [];

  const configuredChunkSize = Number(
    Deno.env.get("TEAM_NEWS_URL_CHUNK_SIZE") ?? "200",
  );
  const chunkSize = Number.isFinite(configuredChunkSize) && configuredChunkSize > 0
    ? Math.floor(configuredChunkSize)
    : 200;
  const chunks = chunkArray(newsUrlIds, chunkSize);
  const results: UrlItem[] = [];
  const maxConcurrency = Math.max(1, concurrency);
  let next = 0;

  async function worker(): Promise<void> {
    while (next < chunks.length) {
      const current = next;
      next += 1;
      const chunk = chunks[current];

      const { data, error } = await supabase
        .from<NewsUrlRow>("news_urls")
        .select("id,url,created_at")
        .in("id", chunk)
        .gte("created_at", cutoffIso)
        .abortSignal(signal);

      if (error) {
        console.error("Failed to fetch news URLs", error);
        throw new HttpError(500, `Failed to load news URLs: ${error.message}`);
      }

      const rows = data ?? [];
      for (const row of rows) {
        if (row.url) {
          results.push({ url: row.url, created_at: row.created_at ?? null });
        }
      }
    }
  }

  const workers = Array.from(
    { length: Math.min(maxConcurrency, chunks.length || 1) },
    () => worker(),
  );

  await Promise.all(workers);
  return results;
}

function dedupeAndLimit(items: UrlItem[], maxUrls: number): UrlItem[] {
  const seen = new Set<string>();
  const output: UrlItem[] = [];

  for (const item of items) {
    const normalized = normalizeUrl(item.url);
    if (!normalized) continue;
    if (seen.has(normalized)) continue;
    seen.add(normalized);
    output.push({ url: normalized, created_at: item.created_at });
    if (output.length >= maxUrls) break;
  }

  return output;
}

function handleOptions(): Response {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    },
  });
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") {
    return handleOptions();
  }

  if (req.method !== "GET") {
    return jsonResponse({ error: "Method not allowed." }, 405);
  }

  const url = new URL(req.url);
  const teamAbbrParam = url.searchParams.get("team_abbr");
  if (!teamAbbrParam) {
    return jsonResponse({ error: "Query parameter 'team_abbr' is required." }, 400);
  }

  const teamAbbr = teamAbbrParam.trim().toUpperCase();
  if (!teamAbbr) {
    return jsonResponse({ error: "Query parameter 'team_abbr' cannot be empty." }, 400);
  }

  try {
    const maxUrls = parsePositiveInt("max_urls", url.searchParams.get("max_urls"), {
      defaultValue: DEFAULT_MAX_URLS,
      min: 1,
    });
    const timeoutMs = parsePositiveInt("timeout_ms", url.searchParams.get("timeout_ms"), {
      defaultValue: DEFAULT_TIMEOUT_MS,
      min: 100,
    });
    const concurrency = parsePositiveInt("concurrency", url.searchParams.get("concurrency"), {
      defaultValue: DEFAULT_CONCURRENCY,
      min: 1,
      max: 20,
    });

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
    const cutoffIso = new Date(Date.now() - DEFAULT_LOOKBACK_HOURS * 60 * 60 * 1000).toISOString();

    try {
      const groupIds = await fetchStoryGroupIds(teamAbbr, controller.signal, cutoffIso);
      if (!groupIds.length) {
        return jsonResponse({
          team_abbr: teamAbbr,
          count: 0,
          urls: [],
          url_items: [],
        });
      }

      const newsUrlIds = await fetchStoryGroupMembers(groupIds, controller.signal, cutoffIso);
      if (!newsUrlIds.length) {
        return jsonResponse({
          team_abbr: teamAbbr,
          count: 0,
          urls: [],
          url_items: [],
        });
      }

      const rawUrls = await fetchNewsUrls(newsUrlIds, controller.signal, concurrency, cutoffIso);
      const urlItems = dedupeAndLimit(rawUrls, maxUrls);
      const urls = urlItems.map((item) => item.url);

      console.log("team-news-urls", {
        team_abbr: teamAbbr,
        group_count: groupIds.length,
        news_url_ids: newsUrlIds.length,
        url_count: urls.length,
      });

      return jsonResponse({
        team_abbr: teamAbbr,
        count: urls.length,
        urls,
        url_items: urlItems.map((item) => ({
          url: item.url,
          created_at: item.created_at,
        })),
      });
    } finally {
      clearTimeout(timeout);
    }
  } catch (error) {
    if (error === "timeout") {
      return jsonResponse({ error: "Request timed out." }, 504);
    }

    if (error instanceof DOMException && error.name === "AbortError") {
      return jsonResponse({ error: "Request timed out." }, 504);
    }

    if (error instanceof HttpError) {
      return jsonResponse({ error: error.message }, error.status);
    }

    console.error("Unexpected error", error);
    return jsonResponse({ error: "Unexpected server error." }, 500);
  }
});
