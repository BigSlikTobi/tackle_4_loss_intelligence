# Backoffice dashboard

A Vite + React backoffice for visualising the NFL knowledge graph and validating extracted news facts. The landing page presents a metallic-green 3D sphere of all 32 teams grouped by division. Each team expands into players, schedule, and fresh topics fetched from Supabase via an Edge Function.

## Features
- 360° rotatable knowledge graph with league/division/team layers and logo orbits
- Dark/light toggle tuned to a dark-green metallic palette
- Team expansion panels for players (with headshots), upcoming/played games, and facts from the past two days
- Existing news validator table and detail view for the `news_urls` pipeline

## Running the app
1. Install dependencies from the project root:
   ```bash
   cd src/apps/backoffice
   npm install
   npm run dev
   ```
2. Environment variables (use a `.env` file in this directory):
   ```bash
   VITE_SUPABASE_URL=<your-supabase-url>
   VITE_SUPABASE_KEY=<anon-or-service-role-key>
   ```

## Supabase Edge Function
The knowledge graph pulls data from `supabase/functions/knowledge-graph`.
- **GET / POST** `/functions/v1/knowledge-graph?team_abbr=BUF` (optional `team_abbr`)
- Returns all teams with conference/division metadata, plus players/games/recent topics for the requested team.
- CORS enabled for headshot/logo rendering.

To deploy with the Supabase CLI:
```bash
supabase functions deploy knowledge-graph --project-ref <project-ref> --env-file ../../.env
```

## Project structure
- `src/pages/KnowledgeGraph.tsx` — 3D view + expansion panel
- `src/hooks/useKnowledgeGraph.ts` — data loading from the Edge Function
- `supabase/functions/knowledge-graph/` — serverless endpoint assembling teams, players, games, and topics
- `src/pages/NewsList.tsx` & `src/pages/NewsDetail.tsx` — existing validator views

## Accessibility & UX
- Keyboard-friendly buttons and large hit areas on nav and chips
- High-contrast palette in both themes with focus glows for interactive elements
- Concise copy so the graph is mostly self-explanatory
