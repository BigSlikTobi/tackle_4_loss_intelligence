import { createClient } from "https://esm.sh/v135/@supabase/supabase-js@2.43.1?target=deno";

type NewsUrlRow = { id: number; url: string | null };
type JsonValue = Record<string, unknown> | JsonValue[] | string | number | boolean | null;

type Stage = "content" | "facts" | "summary";

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

const VALID_STAGES: Stage[] = ["content", "facts", "summary"];
const DEFAULT_LIMIT = 50;

function jsonResponse(body: JsonValue, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
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

function parseStage(raw: string | null): Stage {
  if (!raw) {
    throw new Error("Query parameter 'stage' is required.");
  }
  if ((VALID_STAGES as string[]).includes(raw)) {
    return raw as Stage;
  }
  throw new Error(
    "Query parameter 'stage' must be one of: content, facts, summary.",
  );
}

function parseLimit(raw: string | null): number {
  if (!raw) return DEFAULT_LIMIT;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error("Query parameter 'limit' must be a positive integer.");
  }
  return parsed;
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") {
    return handleOptions();
  }

  if (req.method !== "GET") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  const requestUrl = new URL(req.url);
  let stage: Stage;
  let limit: number;

  try {
    stage = parseStage(requestUrl.searchParams.get("stage"));
    limit = parseLimit(requestUrl.searchParams.get("limit"));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Invalid request.";
    console.error("Invalid request", { message });
    return jsonResponse({ error: message }, 400);
  }

  try {
    let query = supabase
      .from("news_urls")
      .select("id,url")
      .order("id", { ascending: true })
      .limit(limit);

    if (stage === "content") {
      query = query.is("content_extracted_at", null);
    } else if (stage === "facts") {
      query = query.not("content_extracted_at", "is", null).is(
        "facts_extracted_at",
        null,
      );
    } else {
      query = query
        .not("facts_extracted_at", "is", null)
        .is("summary_created_at", null);
    }

    const { data, error } = await query;

    if (error) {
      console.error("Failed to fetch pending news URLs", { stage, error });
      return jsonResponse({ error: "Failed to fetch pending news URLs." }, 500);
    }

    const urls = (data ?? []).map((row: NewsUrlRow) => ({
      id: row.id,
      url: row.url,
    }));

    console.log("Edge function get-pending-news-urls", {
      stage,
      limit,
      resultCount: urls.length,
    });

    return jsonResponse({ stage, limit, urls });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("Unexpected error in get-pending-news-urls", { message });
    return jsonResponse({ error: "Unexpected server error." }, 500);
  }
});
