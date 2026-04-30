-- NFL standings table.
-- Apply once via the Supabase SQL editor before running standings_cli.py.
--
-- One row per (season, through_week, team_abbr). Historical snapshots are
-- preserved so consumers can show "as-of week N" views without recomputing.

create table if not exists public.standings (
    season              integer    not null,
    through_week        integer    not null,
    team_abbr           text       not null,
    team_name           text,
    conference          text       not null,
    division            text       not null,
    wins                integer    not null,
    losses              integer    not null,
    ties                integer    not null,
    win_pct             numeric    not null,
    points_for          integer    not null,
    points_against      integer    not null,
    point_diff          integer    not null,
    division_record     text       not null,
    conference_record   text       not null,
    home_record         text       not null,
    away_record         text       not null,
    last5               text       not null,
    streak              text       not null,
    division_rank       integer    not null,
    conference_rank     integer,
    conference_seed     integer,
    league_rank         integer,
    clinched            text,
    tiebreaker_trail    jsonb,
    tied                boolean    not null default false,
    computed_at         timestamptz not null default now(),
    primary key (season, through_week, team_abbr)
);

create index if not exists standings_season_idx
    on public.standings (season, through_week);

create index if not exists standings_conference_idx
    on public.standings (season, through_week, conference);

create index if not exists standings_division_idx
    on public.standings (season, through_week, division);

-- Public read access for the Flutter client (anon key). Writes go through
-- the service-role key used by the data-loading workflow.
alter table public.standings enable row level security;

drop policy if exists "standings_public_read" on public.standings;
create policy "standings_public_read"
    on public.standings
    for select
    using (true);

-- ---------------------------------------------------------------------------
-- Migration: add conference_rank + league_rank columns
-- Run this if the table was created before these columns existed.
-- ---------------------------------------------------------------------------
alter table public.standings
    add column if not exists conference_rank integer,
    add column if not exists league_rank     integer;
