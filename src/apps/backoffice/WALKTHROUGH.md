# Knowledge graph walkthrough

1. **Open the app** — landing route `/graph` shows the spherical knowledge graph with the NFL crest at the core and eight division orbits.
2. **Rotate & zoom** — drag to rotate the sphere freely; scroll to zoom. Dark/light mode toggle in the top-right adjusts the metallic palette for accessibility.
3. **Identify divisions** — NFC divisions sit on the left hemisphere, AFC divisions on the right. Hover a logo to see the team/division label.
4. **Select a team** — click a logo to load the team panel. The panel surfaces:
   - Player cards (headshot, jersey, position, college, years of experience)
   - Schedule entries showing opponent, venue, kickoff, and score/result when available
   - Topics from the last 48 hours sourced from facts linked to the team
5. **Review freshness** — the footer of the panel shows the generation timestamp from the Edge Function response.
6. **Switch contexts** — click another logo to swap the panel data, or jump to the News Validator via the nav to audit extracted facts.

> Data is streamed from the Supabase Edge Function `knowledge-graph`, which joins teams, players, games, and news facts in one payload.
