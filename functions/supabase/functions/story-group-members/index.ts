// @ts-nocheck

import { createClient } from "https://esm.sh/v135/@supabase/supabase-js@2.43.1?target=deno";

type QueueRecord = {
  id: number;
  story_group_id: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: string;
  locked_at: string | null;
};

type PgNetPayload = {
  type?: string;
  table?: string;
  record?: Record<string, unknown>;
  new?: Record<string, unknown>;
  old?: Record<string, unknown>;
  schema?: string;
  [key: string]: unknown;
};

const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

if (!supabaseUrl || !serviceRoleKey) {
  throw new Error(
    "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables.",
  );
}

const QUEUE_TABLE = Deno.env.get("STORY_GROUP_QUEUE_TABLE") ??
  "story_group_processing_queue";
const PENDING_STATUS = Deno.env.get("STORY_GROUP_QUEUE_PENDING_STATUS") ??
  "pending";
const CLAIMED_STATUS = Deno.env.get("STORY_GROUP_QUEUE_CLAIMED_STATUS") ??
  "processing";
const MAX_LIMIT = Number(Deno.env.get("STORY_GROUP_QUEUE_MAX_LIMIT") ?? "50");
const DEFAULT_LIMIT = Math.min(
  Number(Deno.env.get("STORY_GROUP_QUEUE_DEFAULT_LIMIT") ?? "10"),
  MAX_LIMIT,
);

const supabase = createClient(supabaseUrl, serviceRoleKey, {
  auth: {
    persistSession: false,
  },
});

class HttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type JsonResponseBody = Record<string, unknown> | unknown[];

function jsonResponse(body: JsonResponseBody, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function parseJson<T>(req: Request): Promise<T> {
  try {
    return await req.json() as T;
  } catch {
    throw new HttpError(400, "Request body must be valid JSON.");
  }
}

function coerceLimit(raw: string | null): number {
  if (!raw) return DEFAULT_LIMIT;
  const parsed = Number(raw);
  if (Number.isNaN(parsed) || parsed <= 0) {
    throw new HttpError(400, "Query parameter 'limit' must be a positive number.");
  }
  return Math.min(parsed, MAX_LIMIT);
}

function extractStoryRecord(payload: PgNetPayload): Record<string, unknown> {
  const record = payload.record ?? payload.new ?? payload;
  if (!record || typeof record !== "object") {
    throw new HttpError(400, "Unable to locate inserted record in payload.");
  }
  if (!("id" in record)) {
    throw new HttpError(400, "Inserted record must include an 'id' field.");
  }
  return record;
}

async function enqueueRecord(record: Record<string, unknown>): Promise<Response> {
  const row = {
    story_group_id: record.id,
    payload: record,
    status: PENDING_STATUS,
  };

  const { data, error } = await supabase
    .from(QUEUE_TABLE)
    .insert(row)
    .select("id")
    .single();

  if (error) {
    console.error("Failed to enqueue story group", error);
    throw new HttpError(500, `Failed to enqueue record: ${error.message}`);
  }

  return jsonResponse({ enqueued_id: data.id }, 201);
}

async function pollQueue(limit: number, claim: boolean): Promise<Response> {
  const { data, error } = await supabase
    .from<QueueRecord>(QUEUE_TABLE)
    .select("*")
    .eq("status", PENDING_STATUS)
    .order("created_at", { ascending: true })
    .limit(limit);

  if (error) {
    console.error("Failed to fetch queue", error);
    throw new HttpError(500, `Failed to fetch queue: ${error.message}`);
  }

  if (!data?.length) {
    return jsonResponse({ items: [] });
  }

  if (claim) {
  const ids = data.map((item: QueueRecord) => item.id);
    const { error: updateError } = await supabase
      .from(QUEUE_TABLE)
      .update({
        status: CLAIMED_STATUS,
        locked_at: new Date().toISOString(),
      })
      .in("id", ids)
      .eq("status", PENDING_STATUS);

    if (updateError) {
      console.error("Failed to claim queue items", updateError);
      throw new HttpError(500, `Failed to claim items: ${updateError.message}`);
    }
  }

  return jsonResponse({ items: data });
}

function handleHealthCheck(url: URL): Response | null {
  if (url.pathname.endsWith("/health")) {
    return jsonResponse({ status: "ok" });
  }
  return null;
}

Deno.serve(async (req: Request): Promise<Response> => {
  const url = new URL(req.url);

  try {
    const health = handleHealthCheck(url);
    if (health) return health;

    if (req.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
          "Access-Control-Allow-Headers": "content-type",
        },
      });
    }

    if (req.method === "POST") {
      const payload = await parseJson<PgNetPayload>(req);

      if (payload.table && payload.table !== "story_groups") {
        throw new HttpError(400, "Only story_groups inserts are supported.");
      }

      if (payload.type && payload.type !== "INSERT") {
        throw new HttpError(400, "Only INSERT payloads are supported.");
      }

      const record = extractStoryRecord(payload);
      return await enqueueRecord(record);
    }

    if (req.method === "GET") {
      const limit = coerceLimit(url.searchParams.get("limit"));
      const claimParam = url.searchParams.get("claim");
      const claim = claimParam === null ? true : claimParam !== "false";
      return await pollQueue(limit, claim);
    }

    throw new HttpError(405, "Method not allowed.");
  } catch (error) {
    if (error instanceof HttpError) {
      return jsonResponse({ error: error.message }, error.status);
    }

    console.error("Unexpected error", error);
    return jsonResponse({ error: "Unexpected server error." }, 500);
  }
});
