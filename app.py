import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# --- PAGE CONFIG ---
st.set_page_config(page_title="CBB Market Regression (WOME)", layout="wide")

# --- CONFIGURATION ---
# ⚠️ REPLACE WITH YOUR ACTUAL KEY
API_KEY = 'rTQCNjitVG9Rs6LDYzuUVU4YbcpyVCA6mq2QSkPj8iTkxi3UBVbic+obsBlk7JCo' 
YEAR = 2025  # Ensure this is the current season
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

def calculate_implied_probability(moneyline):
    """
    Converts American Moneyline to Implied Probability (0.0 - 1.0)
    """
    if moneyline is None or pd.isna(moneyline) or moneyline == 0:
        return 0.5 # Default to coinflip if missing
    
    if moneyline < 0:
        return abs(moneyline) / (abs(moneyline) + 100)
    else:
        return 100 / (moneyline + 100)

@st.cache_data(ttl=3600)
def fetch_api_data(year):
    """
    Fetches Games and Lines using the conference loop to avoid API limits.
    """
    # Fallback conferences if API fails
    fallback_conferences = [
        {'abbreviation': 'ACC'}, {'abbreviation': 'B12'}, 
        {'abbreviation': 'B10'}, {'abbreviation': 'SEC'}, 
        {'abbreviation': 'BE'}, {'abbreviation': 'P12'}, 
        {'abbreviation': 'MWC'}, {'abbreviation': 'WCC'},
        {'abbreviation': 'AAC'}, {'abbreviation': 'A10'}
    ]

    # 1. FETCH CONFERENCES
    conferences = []
    with st.spinner('Initializing: Fetching conference list...'):
        try:
            conf_resp = requests.get(f"{BASE_URL}/conferences", headers=HEADERS)
            if conf_resp.status_code == 200:
                conferences = conf_resp.json()
            else:
                conferences = fallback_conferences
        except:
            conferences = fallback_conferences

    # 2. LOOP FETCH BY CONFERENCE
    all_games = []
    all_lines = []
    
    prog_bar = st.progress(0, text="Fetching season data...")
    total_confs = len(conferences)
    
    for idx, conf in enumerate(conferences):
        conf_abbr = conf.get('abbreviation')
        prog_bar.progress((idx + 1) / total_confs, text=f"Loading: {conf_abbr}")
        
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
        
        time.sleep(0.2) # Small buffer

    prog_bar.empty()
    
    # Deduplicate based on ID
    unique_games = {g['id']: g for g in all_games}.values()
    # Map lines by gameId for easy lookup
    lines_map = {str(l.get('gameId')): l for l in all_lines}

    return list(unique_games), lines_map

# --- MAIN LOGIC ---
def run_analysis():
    st.sidebar.title("⚙️ Market Settings")
    
    # Configuration
    target_date = st.sidebar.date_input("Target Date", datetime.now())
    target_date_str = target_date.strftime('%Y-%m-%d')
    
    threshold = st.sidebar.slider("Betting Signal Threshold (WOME Diff)", 0.5, 5.0, 2.0, 0.1)
    
    st.title(f"🏀 CBB WOME Rankings & Signals")
    st.markdown("""
    **Wins Over Market Expectation (WOME):**
    Teams are ranked by how many games they have won vs. how many the closing moneyline implied they *should* have won.
    **Strategy:** Fade the overachievers, buy the underachievers.
    """)

    # 1. LOAD DATA
    games_list, lines_map = fetch_api_data(YEAR)
    
    if not games_list:
        st.error("No data loaded. Check API Key.")
        return

    # 2. CALCULATE WOME STATS (Past Games)
    team_stats = {}
    
    # We iterate through all games to build the history up to today
    for g in games_list:
        game_id = str(g['id'])
        
        # Parse Date
        raw_start = g.get('startDate', '')
        dt_et = utc_to_et(raw_start)
        date_str = dt_et.strftime('%Y-%m-%d')
        
        # Skip future games for the "Training" phase
        if date_str >= target_date_str:
            continue
            
        # We need a result to calculate WOME
        if g.get('homeTeamScore') is None or g.get('awayTeamScore') is None:
            continue

        # Get Moneylines
        if game_id not in lines_map:
            continue # Skip games without market data (can't calc expectation)
            
        l_data = lines_map[game_id]
        if not l_data.get('lines'): continue
        
        # Use first available line provider (usually reliable)
        provider = l_data['lines'][0]
        ml_home = provider.get('moneylineHome')
        ml_away = provider.get('moneylineAway')
        
        # Skip if ML is missing
        if ml_home is None or ml_away is None:
            continue

        # Logic
        home_team = g['homeTeam']['name']
        away_team = g['awayTeam']['name']
        
        home_prob = calculate_implied_probability(ml_home)
        away_prob = calculate_implied_probability(ml_away)
        
        h_score = g['homeTeamScore']
        a_score = g['awayTeamScore']
        
        home_win = 1.0 if h_score > a_score else 0.0
        away_win = 1.0 if a_score > h_score else 0.0
        
        # Init dict entries
        if home_team not in team_stats: team_stats[home_team] = {'actual': 0, 'expected': 0}
        if away_team not in team_stats: team_stats[away_team] = {'actual': 0, 'expected': 0}
        
        # Update Stats
        team_stats[home_team]['actual'] += home_win
        team_stats[home_team]['expected'] += home_prob
        
        team_stats[away_team]['actual'] += away_win
        team_stats[away_team]['expected'] += away_prob

    # Create Rankings DataFrame
    df_wome = pd.DataFrame.from_dict(team_stats, orient='index')
    
    if df_wome.empty:
        st.warning("No past data found with moneylines to calculate WOME.")
        return

    df_wome['WOME'] = df_wome['actual'] - df_wome['expected']
    df_wome = df_wome.sort_values('WOME', ascending=False)
    df_wome['Rank'] = range(1, len(df_wome) + 1)
    
    # 3. ANALYZE TARGET GAMES
    upcoming_games = []
    
    for g in games_list:
        raw_start = g.get('startDate', '')
        dt_et = utc_to_et(raw_start)
        date_str = dt_et.strftime('%Y-%m-%d')
        
        if date_str == target_date_str:
            upcoming_games.append(g)
            
    # 4. DASHBOARD TABS
    tab1, tab2 = st.tabs(["🔥 Betting Signals", "📊 Team Rankings"])
    
    with tab2:
        st.subheader(f"Team Rankings (Through {target_date_str})")
        
        # Formatting for display
        display_df = df_wome.copy()
        display_df['actual'] = display_df['actual'].astype(int)
        display_df['expected'] = display_df['expected'].round(2)
        display_df['WOME'] = display_df['WOME'].round(2)
        
        def color_wome(val):
            color = '#d4edda' if val > 0 else '#f8d7da' # Green/Red
            return f'background-color: {color}'
            
        st.dataframe(display_df.style.applymap(color_wome, subset=['WOME']), use_container_width=True)

    with tab1:
        st.subheader(f"Games for {target_date_str}")
        
        signals_data = []
        
        if not upcoming_games:
            st.info("No games scheduled for this date.")
        
        for g in upcoming_games:
            h_team = g['homeTeam']['name']
            a_team = g['awayTeam']['name']
            
            if h_team in df_wome.index and a_team in df_wome.index:
                h_stats = df_wome.loc[h_team]
                a_stats = df_wome.loc[a_team]
                
                # DIFFERENTIAL LOGIC
                # Home WOME - Away WOME
                # If positive: Home is overachiever, Away is underachiever
                diff = h_stats['WOME'] - a_stats['WOME']
                
                signal = "No Play"
                signal_type = "None"
                
                if diff > threshold:
                    # Home is Overvalued -> Bet Away
                    signal = f"BET {a_team}"
                    signal_type = "Bet"
                elif diff < -threshold:
                    # Away is Overvalued -> Bet Home
                    signal = f"BET {h_team}"
                    signal_type = "Bet"
                    
                signals_data.append({
                    "Time": utc_to_et(g.get('startDate')).strftime('%I:%M %p'),
                    "Matchup": f"{a_team} @ {h_team}",
                    "Home WOME": f"{h_stats['WOME']:.2f} (#{h_stats['Rank']})",
                    "Away WOME": f"{a_stats['WOME']:.2f} (#{a_stats['Rank']})",
                    "Diff": round(diff, 2),
                    "Signal": signal
                })
        
        if signals_data:
            sig_df = pd.DataFrame(signals_data)
            
            def highlight_signal(row):
                if "BET" in row['Signal']:
                    return ['background-color: #90EE90; color: black; font-weight: bold'] * len(row)
                return [''] * len(row)

            st.dataframe(sig_df.style.apply(highlight_signal, axis=1), use_container_width=True)
        else:
            st.write("No matching data for upcoming games.")

if __name__ == "__main__":
    run_analysis()
