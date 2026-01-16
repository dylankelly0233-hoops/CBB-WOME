import streamlit as st
import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta, timezone

# --- PAGE CONFIG ---
st.set_page_config(page_title="CBB WOME (Spread Aware)", layout="wide")

# --- CONFIGURATION ---
# ⚠️ CRITICAL: Use 2025 for the 2025-26 Season
YEAR = 2025  
API_KEY = 'rTQCNjitVG9Rs6LDYzuUVU4YbcpyVCA6mq2QSkPj8iTkxi3UBVbic+obsBlk7JCo' 
BASE_URL = 'https://api.collegebasketballdata.com'
HEADERS = {'Authorization': f'Bearer {API_KEY}', 'accept': 'application/json'}

# --- HELPER FUNCTIONS ---
def utc_to_et(iso_date_str):
    if not iso_date_str: return datetime.now()
    try:
        date_str = iso_date_str.replace('Z', '+00:00')
        dt_utc = datetime.fromisoformat(date_str)
        dt_et = dt_utc.astimezone(timezone(timedelta(hours=-5)))
        return dt_et
    except ValueError:
        return datetime.now()

def get_implied_prob(moneyline, spread):
    """
    Robust Win Probability Calculator.
    Priority 1: Moneyline (Most accurate)
    Priority 2: Spread Conversion (Good approximation)
    """
    # 1. Try Moneyline
    if moneyline is not None and not pd.isna(moneyline) and moneyline != 0:
        if moneyline < 0:
            return abs(moneyline) / (abs(moneyline) + 100)
        else:
            return 100 / (moneyline + 100)
    
    # 2. Fallback to Spread
    # Formula: Logistic probability based on CBB standard deviation (~11 pts)
    # If Spread is -6.0 (Fav), prob should be > 50%
    if spread is not None and not pd.isna(spread):
        # Invert spread because negative spread = higher win prob
        # e.g., Spread -5.0 -> 1 / (1 + 10^(-5/11.5))
        return 1 / (1 + 10 ** (spread / 11.5))
        
    return 0.5 # Default to coinflip if no data

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
    
    prog_bar = st.progress(0, text=f"Fetching data for Season {year}...")
    
    for idx, conf in enumerate(conferences):
        conf_abbr = conf.get('abbreviation')
        prog_bar.progress((idx + 1) / len(conferences), text=f"Loading: {conf_abbr}")
        
        # Fetch Games
        try:
            g_resp = requests.get(f"{BASE_URL}/games", headers=HEADERS, params={'season': year, 'conference': conf_abbr})
            if g_resp.status_code == 200:
                all_games.extend(g_resp.json())
        except: pass
            
        # Fetch Lines
        try:
            l_resp = requests.get(f"{BASE_URL}/lines", headers=HEADERS, params={'season': year, 'conference': conf_abbr})
            if l_resp.status_code == 200:
                all_lines.extend(l_resp.json())
        except: pass
        
        time.sleep(0.1) 

    prog_bar.empty()

    # Map lines by gameId
    lines_map = {}
    for l in all_lines:
        gid = l.get('gameId')
        if gid:
            lines_map[str(gid)] = l
            
    return all_games, lines_map

def run_analysis():
    st.sidebar.title("⚙️ Market Settings")
    target_date = st.sidebar.date_input("Target Date", datetime.now())
    target_date_str = target_date.strftime('%Y-%m-%d')
    threshold = st.sidebar.slider("Bet Signal Threshold (Diff)", 0.5, 5.0, 2.0, 0.1)
    
    st.title(f"🏀 CBB WOME Rankings (Season {YEAR})")
    
    # 1. Fetch Data
    games_list, lines_map = fetch_api_data(YEAR)
    
    if not games_list:
        st.error(f"No games found for Year {YEAR}. Check API Key.")
        return

    # 2. Calculate Stats
    team_stats = {}
    
    # Counters for diagnostics
    stats_debug = {'processed': 0, 'with_data': 0, 'ml_used': 0, 'spread_used': 0}

    for g in games_list:
        game_id = str(g['id'])
        stats_debug['processed'] += 1
        
        # Parse Date
        dt_et = utc_to_et(g.get('startDate', ''))
        date_str = dt_et.strftime('%Y-%m-%d')
        
        # Skip Future Games for "Actual Wins" calculation
        if date_str >= target_date_str:
            continue
            
        # Check for Market Data
        if game_id not in lines_map: continue
        l_data = lines_map[game_id]
        
        if not l_data.get('lines'): continue # Empty lines object
        
        # Get Betting Data
        provider = l_data['lines'][0] # Use first provider
        ml_home = provider.get('moneylineHome')
        ml_away = provider.get('moneylineAway')
        spread_home = provider.get('spread')
        
        # Determine Implied Prob (Use fallback if ML missing)
        home_prob = get_implied_prob(ml_home, spread_home)
        
        # If Spread is Home -5, Away Spread is +5. 
        # Win Prob for away is 1 - Home_Prob (roughly)
        away_prob = 1.0 - home_prob
        
        # Track data source for debug
        if ml_home is not None: stats_debug['ml_used'] += 1
        elif spread_home is not None: stats_debug['spread_used'] += 1
        
        # Calculate Result
        if g.get('homeTeamScore') is not None and g.get('awayTeamScore') is not None:
            stats_debug['with_data'] += 1
            
            h_score = g['homeTeamScore']
            a_score = g['awayTeamScore']
            h_team = g['homeTeam']['name']
            a_team = g['awayTeam']['name']
            
            h_win = 1.0 if h_score > a_score else 0.0
            a_win = 1.0 if a_score > h_score else 0.0
            
            # Update Dict
            if h_team not in team_stats: team_stats[h_team] = {'actual': 0, 'expected': 0}
            if a_team not in team_stats: team_stats[a_team] = {'actual': 0, 'expected': 0}
            
            team_stats[h_team]['actual'] += h_win
            team_stats[h_team]['expected'] += home_prob
            team_stats[a_team]['actual'] += a_win
            team_stats[a_team]['expected'] += away_prob

    # --- 3. DISPLAY RESULTS ---
    if not team_stats:
        st.warning("No past games with betting data found.")
        st.json(stats_debug) # Show why
        return

    df_wome = pd.DataFrame.from_dict(team_stats, orient='index')
    df_wome['WOME'] = df_wome['actual'] - df_wome['expected']
    df_wome = df_wome.sort_values('WOME', ascending=False)
    df_wome['Rank'] = range(1, len(df_wome) + 1)
    
    tab1, tab2 = st.tabs(["🔥 Betting Signals", "📊 Rankings"])
    
    with tab1:
        st.subheader(f"Signals for {target_date_str}")
        st.caption(f"Based on {stats_debug['with_data']} past games. (ML Used: {stats_debug['ml_used']}, Spread Fallback: {stats_debug['spread_used']})")
        
        upcoming = [g for g in games_list if utc_to_et(g.get('startDate', '')).strftime('%Y-%m-%d') == target_date_str]
        
        if not upcoming:
            st.info("No games scheduled for target date.")
        
        signals_found = False
        for g in upcoming:
            h = g['homeTeam']['name']
            a = g['awayTeam']['name']
            
            if h in df_wome.index and a in df_wome.index:
                h_stat = df_wome.loc[h]
                a_stat = df_wome.loc[a]
                diff = h_stat['WOME'] - a_stat['WOME']
                
                signal_text = ""
                box_color = "transparent"
                
                if diff > threshold:
                    signal_text = f"✅ BET {a} (Fade {h})"
                    box_color = "#d4edda" # Green
                    signals_found = True
                elif diff < -threshold:
                    signal_text = f"✅ BET {h} (Fade {a})"
                    box_color = "#d4edda"
                    signals_found = True
                
                if signal_text:
                    with st.container():
                        st.markdown(f"""
                        <div style="background-color: {box_color}; padding: 10px; border-radius: 5px; margin-bottom: 10px; border: 1px solid #c3e6cb;">
                            <strong>{signal_text}</strong><br>
                            <small>{a} (#{a_stat['Rank']}) @ {h} (#{h_stat['Rank']}) | WOME Diff: {diff:.2f}</small>
                        </div>
                        """, unsafe_allow_html=True)
                        
        if not signals_found:
            st.info("No games meet the threshold criteria.")

    with tab2:
        st.dataframe(df_wome[['Rank', 'actual', 'expected', 'WOME']].style.format("{:.2f}"))

if __name__ == "__main__":
    run_analysis()
