# app.py - FINAL: COLORED DOT + FIRE EMOJI ONLY + NO TEXT
import streamlit as st
import pandas as pd
import io
import random
from collections import defaultdict
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak, Spacer
from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
import json
import os
from openpyxl.styles import PatternFill

# ----------------------------------------------------------------------
# CONFIG & COLOR MAP
# ----------------------------------------------------------------------
CONFIG_FILE = "config.json"

# Color name → (hex, emoji)
COLOR_MAP = {
    "red": ("#FF0000", "red circle"),
    "blue": ("#0000FF", "blue circle"),
    "green": ("#008000", "green circle"),
    "yellow": ("#FFD700", "yellow circle"),
    "black": ("#000000", "black circle"),
    "white": ("#FFFFFF", "white circle"),
    "purple": ("#800080", "purple circle"),
    "orange": ("#FFA500", "orange circle")
}

# Default config
DEFAULT_CONFIG = {
    "MIN_MATCHES": 2,
    "MAX_MATCHES": 4,
    "NUM_MATS": 4,
    "MAX_LEVEL_DIFF": 1,
    "WEIGHT_DIFF_FACTOR": 0.10,
    "MIN_WEIGHT_DIFF": 5.0,
    "TEAMS": [
        {"name": "", "color": "red"},
        {"name": "", "color": "blue"},
        {"name": "", "color": "green"},
        {"name": "", "color": "yellow"},
        {"name": "", "color": "black"}
    ]
}

# Load or create config
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r") as f:
        CONFIG = json.load(f)
else:
    CONFIG = DEFAULT_CONFIG
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)

TEAMS = CONFIG["TEAMS"]

# ----------------------------------------------------------------------
# SESSION STATE – INITIALIZED
# ----------------------------------------------------------------------
if "initialized" not in st.session_state:
    st.session_state.initialized = False
if "bout_list" not in st.session_state:
    st.session_state.bout_list = []
if "mat_schedules" not in st.session_state:
    st.session_state.mat_schedules = []
if "suggestions" not in st.session_state:
    st.session_state.suggestions = []
if "active" not in st.session_state:
    st.session_state.active = []
if "last_removed" not in st.session_state:
    st.session_state.last_removed = None

# ----------------------------------------------------------------------
# SETTINGS MENU – COLORED DOT + COLOR NAME
# ----------------------------------------------------------------------
st.sidebar.header("Team Settings")

changed = False
for i in range(5):
    team = TEAMS[i]
    col1, col2 = st.sidebar.columns([1, 4])
    
    with col1:
        color_hex = COLOR_MAP[team["color"]][0]
        dot_html = f'<div style="width:32px;height:32px;background:{color_hex};border-radius:50%;border:2px solid #333;margin:auto;"></div>'
        st.markdown(dot_html, unsafe_allow_html=True)
    
    with col2:
        new_name = st.text_input(
            f"Team {i+1} Name",
            value=team["name"],
            key=f"name_{i}"
        )
        color_options = list(COLOR_MAP.keys())
        current_color = team["color"]
        new_color = st.selectbox(
            "Color",
            options=color_options,
            format_func=lambda x: x.capitalize(),
            index=color_options.index(current_color),
            key=f"color_{i}"
        )
    
    if new_name != team["name"]:
        team["name"] = new_name
        changed = True
    if new_color != team["color"]:
        team["color"] = new_color
        changed = True

if changed:
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)
    st.sidebar.success("Settings saved! Refresh to see changes.")
    st.rerun()

# Rebuild lookup
TEAM_NAMES = [t["name"] for t in TEAMS if t["name"].strip()]
TEAM_COLORS = {t["name"]: COLOR_MAP[t["color"]][0] for t in TEAMS}
TEAM_EMOJIS = {t["name"]: COLOR_MAP[t["color"]][1] for t in TEAMS}

# ----------------------------------------------------------------------
# CORE LOGIC (unchanged)
# ----------------------------------------------------------------------
def is_compatible(w1, w2):
    if w1["team"] == w2["team"]: return False
    if (w1["grade"] == 5 and w2["grade"] in [7,8]) or (w2["grade"] == 5 and w1["grade"] in [7,8]):
        return False
    return True

def max_weight_diff(weight):
    return max(CONFIG["MIN_WEIGHT_DIFF"], weight * CONFIG["WEIGHT_DIFF_FACTOR"])

def matchup_score(w1, w2):
    w_diff = abs(w1["weight"] - w2["weight"])
    l_diff = abs(w1["level"] - w2["level"])
    return round(w_diff + l_diff * 10, 1)

def generate_initial_matchups(active):
    bouts = set()
    sorted_by_level = sorted(active, key=lambda w: -w["level"])
    level_groups = defaultdict(list)
    for w in sorted_by_level:
        level_groups[w["level"]].append(w)
    for level in sorted(level_groups.keys(), reverse=True):
        group = level_groups[level]
        added_in_round = True
        while added_in_round:
            added_in_round = False
            random.shuffle(group)
            for w in group:
                if len(w["matches"]) >= CONFIG["MAX_MATCHES"]: continue
                opps = [o for o in active
                        if o != w and o not in w["matches"]
                        and len(o["matches"]) < CONFIG["MAX_MATCHES"]
                        and is_compatible(w, o)
                        and abs(w["weight"]-o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"]))
                        and abs(w["level"]-o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
                if not opps: continue
                best = min(opps, key=lambda o: matchup_score(w, o))
                w["matches"].append(best)
                best["matches"].append(w)
                bouts.add(frozenset({w["id"], best["id"]}))
                added_in_round = True
                break
    bout_list = []
    for idx, b in enumerate(bouts, 1):
        ids = list(b)
        w1 = next(w for w in active if w["id"] == ids[0])
        w2 = next(w for w in active if w["id"] == ids[1])
        score = matchup_score(w1, w2)
        avg_w = (w1["weight"] + w2["weight"]) / 2
        is_early = w1["early"] or w2["early"]
        bout_list.append({
            "bout_num": idx,
            "w1_id": w1["id"], "w1_name": w1["name"], "w1_team": w1["team"],
            "w1_level": w1["level"], "w1_weight": w1["weight"], "w1_grade": w1["grade"], "w1_early": w1["early"],
            "w2_id": w2["id"], "w2_name": w2["name"], "w2_team": w2["team"],
            "w2_level": w2["level"], "w2_weight": w2["weight"], "w2_grade": w2["grade"], "w2_early": w2["early"],
            "score": score, "avg_weight": avg_w, "is_early": is_early, "manual": ""
        })
    return bout_list

# ... [build_suggestions, generate_mat_schedule unchanged] ...

# ----------------------------------------------------------------------
# MAT PREVIEWS – COLORED DOT + FIRE EMOJI ONLY
# ----------------------------------------------------------------------
if st.session_state.initialized:
    st.subheader("Mat Previews")
    mat_dfs = {}
    for mat_num in range(1, CONFIG["NUM_MATS"] + 1):
        mat_bouts = [m for m in st.session_state.mat_schedules if m["mat"] == mat_num]
        if not mat_bouts:
            mat_dfs[mat_num] = pd.DataFrame(columns=["Remove","Slot","Early?","Wrestler 1","G/L/W","Wrestler 2","G/L/W 2","Score","bout_num","is_early"])
            continue
        rows = []
        for m in mat_bouts:
            bout = next(b for b in st.session_state.bout_list if b["bout_num"] == m["bout_num"])
            c1 = TEAM_COLORS.get(bout["w1_team"], "#CCCCCC")
            c2 = TEAM_COLORS.get(bout["w2_team"], "#CCCCCC")
            dot1 = f'<div style="display:inline-block;width:16px;height:16px;background:{c1};border-radius:50%;margin-right:8px;vertical-align:middle;"></div>'
            dot2 = f'<div style="display:inline-block;width:16px;height:16px;background:{c2};border-radius:50%;margin-right:8px;vertical-align:middle;"></div>'
            w1_str = f"{dot1}{bout['w1_name']} ({bout['w1_team']})"
            w2_str = f"{dot2}{bout['w2_name']} ({bout['w2_team']})"
            w1_glw = f"{bout['w1_grade']} / {bout['w1_level']:.1f} / {bout['w1_weight']:.0f}"
            w2_glw = f"{bout['w2_grade']} / {bout['w2_level']:.1f} / {bout['w2_weight']:.0f}"
            # FIRE EMOJI ONLY
            early_label = "fire" if bout["is_early"] else ""
            rows.append({
                "Remove": False,
                "Slot": m["mat_bout_num"],
                "Early?": early_label,
                "Wrestler 1": w1_str,
                "G/L/W": w1_glw,
                "Wrestler 2": w2_str,
                "G/L/W 2": w2_glw,
                "Score": f"{bout['score']:.1f}",
                "bout_num": bout["bout_num"],
                "is_early": bout["is_early"]
            })
        df = pd.DataFrame(rows)
        mat_dfs[mat_num] = df

    tabs = st.tabs([f"Mat {i}" for i in range(1, CONFIG["NUM_MATS"] + 1)])
    for i, tab in enumerate(tabs, 1):
        with tab:
            df = mat_dfs[i]
            if df.empty:
                st.write("No matches")
                continue
            # RENDER HTML + EMOJIS
            html_table = df.to_html(escape=False, index=False)
            st.markdown(html_table, unsafe_allow_html=True)

            # REMOVALS
            if st.button("Apply Removals on This Mat", key=f"apply_mat_{i}"):
                edited_df = st.data_editor(
                    df,
                    column_config={
                        "Remove": st.column_config.CheckboxColumn("Remove"),
                        "Slot": st.column_config.NumberColumn("Slot", disabled=True),
                        "Early?": st.column_config.TextColumn("Early?"),
                        "Wrestler 1": st.column_config.TextColumn("Wrestler 1"),
                        "G/L/W": st.column_config.TextColumn("G/L/W"),
                        "Wrestler 2": st.column_config.TextColumn("Wrestler 2"),
                        "G/L/W 2": st.column_config.TextColumn("G/L/W"),
                        "Score": st.column_config.NumberColumn("Score"),
                        "bout_num": st.column_config.NumberColumn("bout_num", width=0),
                        "is_early": st.column_config.CheckboxColumn("is_early", width=0),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key=f"mat_editor_{i}"
                )
                to_remove = edited_df[edited_df["Remove"] == True]["bout_num"].dropna().astype(int).tolist()
                if to_remove:
                    st.session_state.last_removed = to_remove[-1]
                    for bout_num in to_remove:
                        for b in st.session_state.bout_list:
                            if b["bout_num"] == bout_num:
                                b["manual"] = "Removed"
                                w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
                                w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
                                if w2 in w1["matches"]: w1["matches"].remove(w2)
                                if w1 in w2["matches"]: w2["matches"].remove(w1)
                    st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
                    st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
                    st.success(f"Removed {len(to_remove)} match(es)!")
                    st.rerun()

    # ----- UNDO, EXCEL, PDF (unchanged) -----
    # ... [same as before] ...
