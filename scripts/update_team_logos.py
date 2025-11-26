#!/usr/bin/env python3
"""
Script to update team logo URLs in the teams table.
Maps team names to logo files in the Supabase storage bucket.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env
from src.shared.db.connection import get_supabase_client

# Supabase storage base URL
STORAGE_BASE_URL = "https://yqtiuzhedkfacwgormhn.supabase.co/storage/v1/object/public/team_logos"

# Mapping from team_name to logo filename
# The bucket uses format: {city}_{nickname}.png (lowercase, underscores)
TEAM_LOGO_MAP = {
    "Arizona Cardinals": "arizona_cardinals.png",
    "Atlanta Falcons": "atlanta_falcons.png",
    "Baltimore Ravens": "baltimore_ravens.png",
    "Buffalo Bills": "buffalo_bills.png",
    "Carolina Panthers": "carolina_panthers.png",
    "Chicago Bears": "chicago_bears.png",
    "Cincinnati Bengals": "cincinnati_bengals.png",
    "Cleveland Browns": "cleveland_browns.png",
    "Dallas Cowboys": "dallas_cowboys.png",
    "Denver Broncos": "denver_broncos.png",
    "Detroit Lions": "detroit_lions.png",
    "Green Bay Packers": "green_bay_packers.png",
    "Houston Texans": "houston_texans.png",
    "Indianapolis Colts": "indianapolis_colts.png",
    "Jacksonville Jaguars": "jacksonville_jaguars.png",
    "Kansas City Chiefs": "kansas_city_chiefs.png",
    "Las Vegas Raiders": "las_vegas_raiders.png",
    "Los Angeles Chargers": "los_angeles_chargers.png",
    "Los Angeles Chargers Chargers": "los_angeles_chargers.png",  # Handle duplicate name issue
    "Los Angeles Rams": "los_angeles_rams.png",
    "Los Angeles Rams Rams": "los_angeles_rams.png",  # Handle duplicate name issue
    "Miami Dolphins": "miami_dolphins.png",
    "Minnesota Vikings": "minnesota_vikings.png",
    "New England Patriots": "new_england_patriots.png",
    "New Orleans Saints": "new_orleans_saints.png",
    "New York Giants": "new_york_giants.png",
    "New York Giants Giants": "new_york_giants.png",  # Handle duplicate name issue
    "New York Jets": "new_york_jets.png",
    "New York Jets Jets": "new_york_jets.png",  # Handle duplicate name issue
    "Philadelphia Eagles": "philadelphia_eagles.png",
    "Pittsburgh Steelers": "pittsburgh_steelers.png",
    "San Francisco 49ers": "san_francisco_49ers.png",
    "Seattle Seahawks": "seattle_seahawks.png",
    "Tampa Bay Buccaneers": "tampa_bay_buccaneers.png",
    "Tennessee Titans": "tennessee_titans.png",
    "Washington Commanders": "washington_commanders.png",
}


def get_logo_url(team_name: str) -> str | None:
    """Get the full logo URL for a team name."""
    filename = TEAM_LOGO_MAP.get(team_name)
    if filename:
        return f"{STORAGE_BASE_URL}/{filename}"
    return None


def update_team_logos(dry_run: bool = True):
    """Update logo_url for all teams in the database."""
    load_env()
    client = get_supabase_client()
    
    # Fetch all teams
    response = client.table("teams").select("team_abbr, team_name, logo_url").execute()
    teams = response.data
    
    print(f"Found {len(teams)} teams in database\n")
    
    updates = []
    not_found = []
    
    for team in teams:
        team_name = team["team_name"]
        team_abbr = team["team_abbr"]
        current_logo = team.get("logo_url")
        
        new_logo_url = get_logo_url(team_name)
        
        if new_logo_url:
            if current_logo != new_logo_url:
                updates.append({
                    "team_abbr": team_abbr,
                    "team_name": team_name,
                    "logo_url": new_logo_url
                })
                print(f"✓ {team_abbr}: {team_name}")
                print(f"  → {new_logo_url}")
            else:
                print(f"= {team_abbr}: {team_name} (already set)")
        else:
            not_found.append(team_name)
            print(f"✗ {team_abbr}: {team_name} - NO MAPPING FOUND")
    
    print(f"\n{'='*60}")
    print(f"Summary: {len(updates)} updates, {len(not_found)} not found")
    
    if not_found:
        print(f"\nTeams without logo mapping:")
        for name in not_found:
            print(f"  - {name}")
    
    if dry_run:
        print(f"\n[DRY RUN] No changes made. Run with --apply to update database.")
    else:
        print(f"\nApplying {len(updates)} updates...")
        for update in updates:
            client.table("teams").update({
                "logo_url": update["logo_url"]
            }).eq("team_abbr", update["team_abbr"]).execute()
            print(f"  Updated {update['team_abbr']}")
        print("\n✓ All updates applied successfully!")


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    update_team_logos(dry_run=dry_run)
