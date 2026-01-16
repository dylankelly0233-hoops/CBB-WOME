import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# --- PAGE CONFIG ---
st.set_page_config(page_title="CBB WOME Debugger", layout="wide")

# --- CONFIGURATION ---
API_KEY = 'rTQCNjitVG9Rs6LDYzuUVU4YbcpyVCA6mq2QSkPj8iTkxi3UBVbic+obsBlk7JCo' 
YEAR = 2026  # <--- CRITICAL: Set to 2025 for the 2025-26 Season
BASE_URL = 'https://api.collegebasketballdata.com'
HEADERS = {'Authorization': f'Bearer {API_KEY}', 'accept': 'application/json'}

def utc_to_et(iso_date_str):
    if not iso_date_str: return datetime.now()
    try:
        date_str = iso_date_str.replace('Z', '+00:00')
        dt_utc = datetime.fromisoformat(date_str)
        dt_et = dt_utc.astimezone(timezone(timedelta(hours=-5)))
        return dt_et
    except ValueError:
        return datetime.now()

def calculate_implied_probability(moneyline):
    if moneyline is None or pd.isna(moneyline) or moneyline == 0:
        return 0.5
    if moneyline < 0:
        return abs(moneyline) / (abs(moneyline) + 100)
    else:
        return 100 / (moneyline + 100)

@st.cache_data(ttl=3600)
def fetch_api_data(year):
    conferences = [
        {'abbreviation': 'ACC'}, {'abbreviation': 'B12'}, 
        {'abbreviation': 'B10'}, {'abbreviation': 'SEC'}, 
        {'abbreviation': 'BE'}, {'abbreviation': 'P12'}, 
        {'abbreviation': 'MWC'}, {'abbreviation': 'WCC'},
        {'abbreviation': 'AAC'}, {'abbreviation': 'A10'}
    ]
    
    all_games = []
    all_lines = []
    
    prog_bar = st.progress(0, text="Fetching season data...")
    
    for idx, conf in enumerate(conferences):
        conf_abbr = conf.get('abbreviation')
        prog_bar.progress((idx + 1) / len(conferences), text=f"Loading: {conf_abbr}")
        
        # Fetch Games
        try:
            g_resp = requests.get(f"{BASE_URL}/games", headers=HEADERS, params={'season': year, 'conference': conf_abbr})
            if g_resp.status_code == 200:
                all_games.extend(g_resp.json())
        except Exception as e:
            print(f"Error fetching games for {conf_abbr}: {e}")
            
        # Fetch Lines
        try:
            # Note: Some APIs require specific flags for historical lines
            l_resp = requests.get(f"{BASE_URL}/lines", headers=HEADERS, params={'season': year, 'conference': conf_abbr})
            if l_resp.status_code == 200:
                all_lines.extend(l_resp.json())
        except Exception as e:
            print(f"Error fetching lines for {conf_abbr}: {e}")
        
        time.sleep(0.1) 

    prog_bar.empty()
    
    # Debug print
    print(f"DEBUG: Fetched {len(all_games)} games and {len(all_lines)} lines.")

    # Create Dictionary Map with STRICT string keys
    lines_map = {}
    for l in all_lines:
        gid = l.get('gameId')
        if gid:
            lines_map[str(gid)] = l
            
    return all_games, lines_map

def run_analysis():
    st.sidebar.title("⚙️ Settings")
    target_date = st.sidebar.date_input("Target Date", datetime.now())
    target_date_str = target_date.strftime('%Y-%m-%d')
    threshold = st.sidebar.slider("Betting Signal Threshold", 0.5, 5.0, 2.0, 0.1)
    
    st.title("🏀 CBB WOME Debugger")
    
    games_list, lines_map = fetch_api_data(YEAR)
    
    if not games_list:
        st.error("No games fetched. Check API Key or Season Year.")
        return

    # Counter for debug
    matched_count = 0
    missing_line_count = 0
    
    team_stats = {}
    
    for g in games_list:
        game_id = str(g['id']) # Force string
        
        # Check if line exists
        if game_id not in lines_map:
            missing_line_count += 1
            continue
            
        l_data = lines_map[game_id]
        if not l_data.get('lines'): 
            continue
            
        provider = l_data['lines'][0]
        ml_home = provider.get('moneylineHome')
        ml_away = provider.get('moneylineAway')
        
        if ml_home is None or ml_away is None:
            continue

        matched_count += 1
        
        # ... (Rest of logic is the same) ...
        home_team = g['homeTeam']['name']
        away_team = g['awayTeam']['name']
        
        home_prob = calculate_implied_probability(ml_home)
        away_prob = calculate_implied_probability(ml_away)
        
        if g.get('homeTeamScore') is not None and g.get('awayTeamScore') is not None:
            h_score = g['homeTeamScore']
            a_score = g['awayTeamScore']
            
            home_win = 1.0 if h_score > a_score else 0.0
            away_win = 1.0 if a_score > h_score else 0.0
            
            if home_team not in team_stats: team_stats[home_team] = {'actual': 0, 'expected': 0}
            if away_team not in team_stats: team_stats[away_team] = {'actual': 0, 'expected': 0}
            
            team_stats[home_team]['actual'] += home_win
            team_stats[home_team]['expected'] += home_prob
            team_stats[away_team]['actual'] += away_win
            team_stats[away_team]['expected'] += away_prob

    # --- DEBUG INFO ON SCREEN ---
    st.info(f"Diagnostics: Processed {len(games_list)} games. Matched Lines for {matched_count} games. Missing Lines for {missing_line_count} games.")
    
    if not team_stats:
        st.warning("⚠️ Still no WOME data generated. The API might not be returning historical moneylines.")
        return

    # ... (Rest of dashboard display) ...
    df_wome = pd.DataFrame.from_dict(team_stats, orient='index')
    df_wome['WOME'] = df_wome['actual'] - df_wome['expected']
    df_wome = df_wome.sort_values('WOME', ascending=False)
    
    st.dataframe(df_wome)

if __name__ == "__main__":
    run_analysis()
