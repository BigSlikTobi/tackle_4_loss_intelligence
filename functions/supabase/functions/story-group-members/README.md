# story-group-members Edge Function

This Supabase Edge Function receives insert notifications for the `story_groups` table via `pg_net`/`http` and enqueues them for asynchronous processing.

## Environment

The function expects the following environment variables (typically provided automatically by the Supabase Edge runtime):

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Optional overrides:

- `STORY_GROUP_QUEUE_TABLE` (default: `story_group_processing_queue`)
- `STORY_GROUP_QUEUE_PENDING_STATUS` (default: `pending`)
- `STORY_GROUP_QUEUE_CLAIMED_STATUS` (default: `processing`)
- `STORY_GROUP_QUEUE_MAX_LIMIT` (default: `50`)
- `STORY_GROUP_QUEUE_DEFAULT_LIMIT` (default: `10`)

## Queue schema

Create a durable queue table to persist incoming work items. Adjust column types to match your `story_groups.id` type (UUID shown below):

```sql
create table if not exists public.story_group_processing_queue (
  id bigint generated always as identity primary key,
  story_group_id uuid not null,
  payload jsonb not null,
  status text not null default 'pending',
  locked_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists story_group_processing_queue_status_created_idx
  on public.story_group_processing_queue (status, created_at asc);
```

## Database trigger

Install the `http` extension (bundled with Supabase) and create a trigger that forwards new rows to the Edge Function. Replace `<project-ref>` with your project ref and set the bearer token to an Edge function secret (for example, `STORY_QUEUE_WEBHOOK_SECRET`).

```sql
create extension if not exists http with schema extensions;

create or replace function public.forward_story_group_insert()
returns trigger
language plpgsql
security definer
as $$
declare
  response record;
begin
  select *
    from net.http_post(
      url := 'https://<project-ref>.functions.supabase.co/story-group-members',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer ' || current_setting('app.settings.story_queue_secret', true),
        'x-supabase-project-ref', '<project-ref>'
      ),
      body := jsonb_build_object(
        'type', TG_OP,
        'table', TG_TABLE_NAME,
        'schema', TG_TABLE_SCHEMA,
        'record', row_to_json(NEW)
      )
    )
    into response;

  return NEW;
end;
$$;

create trigger story_groups_forward
  after insert on public.story_groups
  for each row execute function public.forward_story_group_insert();
```

Expose the secret in Postgres (for example in `supabase/config.toml`):

```toml
[app.settings]
story_queue_secret = "<edge-function-bearer>"
```

## Polling the queue

The function exposes a `GET` endpoint that returns pending items (and optionally claims them):

```
GET https://<project-ref>.functions.supabase.co/story-group-members?limit=5&claim=true
Authorization: Bearer <service-role-or-custom-secret>
```

- `limit` — max items to return (default `10`, capped by `STORY_GROUP_QUEUE_MAX_LIMIT`).
- `claim` — set to `false` to read without transitioning items to the claimed status (`processing` by default).

Response shape:

```json
{
  "items": [
    {
      "id": 42,
      "story_group_id": "969f49cb-1de7-4b85-9d52-3d85dcc45a65",
      "payload": { "id": "969f49cb-1de7-4b85-9d52-3d85dcc45a65", ... },
      "status": "pending",
      "created_at": "2024-10-10T12:34:56.000Z",
      "locked_at": null
    }
  ]
}
```

## Local development

```bash
supabase functions serve story-group-members --env-file functions/.env.yaml.example
```

Provide sample payloads with the Supabase CLI or curl:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"type":"INSERT","table":"story_groups","record":{"id":"969f49cb-1de7-4b85-9d52-3d85dcc45a65"}}' \
  http://localhost:54321/functions/v1/story-group-members
```
