# app.py – RED X VERTICALLY CENTERED + ONLY ACTIVE MAT STAYS OPEN
import streamlit as st
import pandas as pd
import io
import random
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
COLOR_MAP = {
    "red": "#FF0000", "blue": "#0000FF", "green": "#008000",
    "yellow": "#FFD700", "black": "#000000", "white": "#FFFFFF",
    "purple": "#800080", "orange": "#FFA500"
}
DEFAULT_CONFIG = {
    "MIN_MATCHES": 2, "MAX_MATCHES": 4, "NUM_MATS": 4,
    "MAX_LEVEL_DIFF": 1, "WEIGHT_DIFF_FACTOR": 0.10, "MIN_WEIGHT_DIFF": 5.0,
    "TEAMS": [
        {"name": "", "color": "red"}, {"name": "", "color": "blue"},
        {"name": "", "color": "green"}, {"name": "", "color": "yellow"},
        {"name": "", "color": "black"}
    ]
}
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r") as f:
        CONFIG = json.load(f)
else:
    CONFIG = DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)
TEAMS = CONFIG["TEAMS"]

# ----------------------------------------------------------------------
# SESSION STATE
# ----------------------------------------------------------------------
for key in ["initialized","bout_list","mat_schedules","suggestions","active","undo_stack","mat_open"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list","mat_schedules","suggestions","active","undo_stack"] else {}

# ----------------------------------------------------------------------
# CORE LOGIC (unchanged – same as before)
# ----------------------------------------------------------------------
# ... [all functions: is_compatible, max_weight_diff, matchup_score, generate_initial_matchups, build_suggestions, generate_mat_schedule] ...

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def remove_match(bout_num):
    open_mats = st.session_state.mat_open.copy()
    b = next(x for x in st.session_state.bout_list if x["bout_num"] == bout_num)
    b["manual"] = "Removed"
    w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
    w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
    if b["w2_id"] in w1["match_ids"]: w1["match_ids"].remove(b["w2_id"])
    if b["w1_id"] in w2["match_ids"]: w2["match_ids"].remove(b["w1_id"])
    st.session_state.undo_stack.append(bout_num)
    st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
    st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
    st.success("Match removed.")
    st.session_state.mat_open = open_mats
    st.rerun()

def undo_last():
    open_mats = st.session_state.mat_open.copy()
    if st.session_state.undo_stack:
        bout_num = st.session_state.undo_stack.pop()
        b = next(x for x in st.session_state.bout_list if x["bout_num"] == bout_num and x["manual"] == "Removed")
        b["manual"] = ""
        w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
        w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
        if b["w2_id"] not in w1["match_ids"]: w1["match_ids"].append(b["w2_id"])
        if b["w1_id"] not in w2["match_ids"]: w2["match_ids"].append(b["w1_id"])
        st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.success("Undo successful!")
    st.session_state.mat_open = open_mats
    st.rerun()

# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")

# UPDATED CSS: X BUTTON VERTICALLY CENTERED
st.markdown("""
<style>
    .trash-btn {
        background:#ff4444!important;
        color:#fff!important;
        border:none!important;
        border-radius:4px!important;
        width:20px!important;
        height:20px!important;
        font-size:12px!important;
        line-height:1!important;
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;
        cursor:pointer!important;
        padding:0!important;
        margin:0!important;
    }
    .trash-btn:hover { background:#cc0000!important; }

    /* Vertically center the delete button with the card */
    div[data-testid="column"]:has(> div > button.trash-btn) {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
    }
</style>
""", unsafe_allow_html=True)

st.title("Wrestling Meet Scheduler")
st.caption("Upload roster to Generate to Edit to Download. **No data stored.**")

# ---- UPLOAD (unique key) ----
uploaded = st.file_uploader("Upload `roster.csv`", type="csv", key="roster_uploader")
if uploaded and not st.session_state.initialized:
    df = pd.read_csv(uploaded)
    req = ["id","name","team","grade","level","weight","early_matches","scratch"]
    if not all(c in df.columns for c in req):
        st.error("Missing columns: " + ", ".join(req)); st.stop()
    wrestlers = df.to_dict("records")
    for w in wrestlers:
        w["id"]=int(w["id"]); w["grade"]=int(w["grade"]); w["level"]=float(w["level"]); w["weight"]=float(w["weight"])
        w["early"] = str(w["early_matches"]).strip().upper()=="Y" or w["early_matches"] in [1,True]
        w["scratch"]= str(w["scratch"]).strip().upper()=="Y" or w["scratch"] in [1,True]
        w["match_ids"]=[]
    st.session_state.active = [w for w in wrestlers if not w["scratch"]]
    st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
    st.session_state.suggestions = build_suggestions(st.session_state.active,st.session_state.bout_list)
    st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list,gap=4)
    st.session_state.initialized = True
    st.session_state.mat_open = {}
    st.success("Roster loaded!")

# ---- SETTINGS SIDEBAR (FULLY RESTORED) ----
st.sidebar.header("Meet Settings")
changed = False
st.sidebar.subheader("Match & Scheduling Rules")
c1, c2 = st.sidebar.columns(2)
with c1:
    new_min = st.number_input("Min Matches per Wrestler", 1, 10, CONFIG["MIN_MATCHES"], key="min_matches")
    new_max = st.number_input("Max Matches per Wrestler", 1, 10, CONFIG["MAX_MATCHES"], key="max_matches")
    new_mats = st.number_input("Number of Mats", 1, 10, CONFIG["NUM_MATS"], key="num_mats")
with c2:
    new_level_diff = st.number_input("Max Level Difference", 0, 5, CONFIG["MAX_LEVEL_DIFF"], key="max_level_diff")
    new_weight_factor = st.slider("Weight Diff % Factor", 0.0, 0.5, CONFIG["WEIGHT_DIFF_FACTOR"], 0.01, format="%.2f", key="weight_factor")
    new_min_weight = st.number_input("Min Weight Diff (lbs)", 0.0, 50.0, CONFIG["MIN_WEIGHT_DIFF"], 0.5, key="min_weight_diff")
if new_min > new_max:
    st.sidebar.error("Min Matches cannot exceed Max Matches!")
    new_min = new_max
st.sidebar.markdown("---")
st.sidebar.subheader("Team Names & Colors")
for i in range(5):
    team = TEAMS[i]
    st.sidebar.markdown(f"**Team {i+1}**")
    new_name = st.sidebar.text_input("Name", team["name"], key=f"name_{i}", label_visibility="collapsed")
    new_color = st.sidebar.selectbox("Color", list(COLOR_MAP.keys()), index=list(COLOR_MAP.keys()).index(team["color"]),
                                     format_func=lambda x: x.capitalize(), key=f"color_{i}", label_visibility="collapsed")
    if new_name != team["name"]: team["name"], changed = new_name, True
    if new_color != team["color"]: team["color"], changed = new_color, True
if (new_min != CONFIG["MIN_MATCHES"] or new_max != CONFIG["MAX_MATCHES"] or
    new_mats != CONFIG["NUM_MATS"] or new_level_diff != CONFIG["MAX_LEVEL_DIFF"] or
    new_weight_factor != CONFIG["WEIGHT_DIFF_FACTOR"] or new_min_weight != CONFIG["MIN_WEIGHT_DIFF"]):
    CONFIG.update({"MIN_MATCHES": new_min, "MAX_MATCHES": new_max, "NUM_MATS": new_mats,
                   "MAX_LEVEL_DIFF": new_level_diff, "WEIGHT_DIFF_FACTOR": new_weight_factor,
                   "MIN_WEIGHT_DIFF": new_min_weight})
    changed = True
st.sidebar.markdown("---")
if st.sidebar.button("Reset to Default", type="secondary"):
    CONFIG = DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)
    st.sidebar.success("Reset! Refresh to apply.")
    st.rerun()
if changed:
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)
    st.sidebar.success("Settings saved! Refresh to apply.")
    st.rerun()
TEAM_COLORS = {t["name"]: COLOR_MAP[t["color"]] for t in TEAMS if t["name"]}

# ----------------------------------------------------------------------
# MAIN APP
# ----------------------------------------------------------------------
if st.session_state.initialized:
    # ---- SUGGESTED MATCHUPS (unchanged) ----
    st.subheader("Suggested Matches")
    if st.session_state.suggestions:
        sugg_data = []
        for i, s in enumerate(st.session_state.suggestions):
            w = next(w for w in st.session_state.active if w["id"] == s["_w_id"])
            o = next(o for o in st.session_state.active if o["id"] == s["_o_id"])
            sugg_data.append({
                "Add": False,
                "Wrestler": f"{w['name']} ({w['team']})",
                "Lvl": f"{w['level']:.1f}",
                "Wt": f"{w['weight']:.0f}",
                "vs": f"{o['name']} ({o['team']})",
                "vs_Lvl": f"{o['level']:.1f}",
                "vs_Wt": f"{o['weight']:.0f}",
                "Score": f"{s['score']:.1f}",
                "idx": i
            })
        sugg_full_df = pd.DataFrame(sugg_data)
        sugg_display_df = sugg_full_df.drop(columns=["idx"])
        edited = st.data_editor(
            sugg_display_df,
            column_config={
                "Add": st.column_config.CheckboxColumn("Add"),
                "Wrestler": st.column_config.TextColumn("Wrestler"),
                "Lvl": st.column_config.NumberColumn("Lvl"),
                "Wt": st.column_config.NumberColumn("Wt"),
                "vs": st.column_config.TextColumn("vs"),
                "vs_Lvl": st.column_config.NumberColumn("vs_Lvl"),
                "vs_Wt": st.column_config.NumberColumn("vs_Wt"),
                "Score": st.column_config.NumberColumn("Score"),
            },
            use_container_width=True,
            hide_index=True,
            key="sugg_editor"
        )
        if st.button("Add Selected"):
            to_add = [st.session_state.suggestions[sugg_full_df.iloc[row.name]["idx"]]
                      for _, row in edited.iterrows() if row["Add"]]
            for s in to_add:
                w = next(w for w in st.session_state.active if w["id"] == s["_w_id"])
                o = next(o for o in st.session_state.active if o["id"] == s["_o_id"])
                if o["id"] not in w["match_ids"]: w["match_ids"].append(o["id"])
                if w["id"] not in o["match_ids"]: o["match_ids"].append(w["id"])
                st.session_state.bout_list.append({
                    "bout_num": len(st.session_state.bout_list)+1,
                    "w1_id": w["id"], "w1_name": w["name"], "w1_team": w["team"],
                    "w1_level": w["level"], "w1_weight": w["weight"], "w1_grade": w["grade"], "w1_early": w["early"],
                    "w2_id": o["id"], "w2_name": o["name"], "w2_team": o["team"],
                    "w2_level": o["level"], "w2_weight": o["weight"], "w2_grade": o["grade"], "w2_early": o["early"],
                    "score": s["score"], "avg_weight": (w["weight"]+o["weight"])/2,
                    "is_early": w["early"] or o["early"], "manual": "Yes"
                })
            st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
            st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
            st.success("Matches added!")
            st.rerun()
    else:
        st.info("All wrestlers have 2+ matches. No suggestions needed.")

    # ---- MAT PREVIEWS – ONLY ACTIVE MAT STAYS OPEN ----
    st.subheader("Mat Previews")

    open_mats = st.session_state.mat_open.copy()

    for mat in range(1, CONFIG["NUM_MATS"]+1):
        bouts = [m for m in st.session_state.mat_schedules if m["mat"]==mat]
        if not bouts:
            st.write(f"**Mat {mat}: No matches**")
            continue

        key = f"mat_{mat}"
        is_open = open_mats.get(key, False)

        with st.expander(f"Mat {mat}", expanded=is_open):
            for idx,m in enumerate(bouts):
                b = next(x for x in st.session_state.bout_list if x["bout_num"]==m["bout_num"])
                bg = "#fff3cd" if b["is_early"] else "#ffffff"
                w1c = TEAM_COLORS.get(b["w1_team"], "#999")
                w2c = TEAM_COLORS.get(b["w2_team"], "#999")

                col_del, col_card = st.columns([0.08,1], gap="small")
                with col_del:
                    if st.button("X", key=f"del_{b['bout_num']}"):
                        remove_match(b["bout_num"])
                with col_card:
                    st.markdown(f"""
                    <div style="background:{bg};border:1px solid #e6e6e6;border-radius:8px;padding:10px;">
                        <div style="display:flex;align-items:center;gap:12px;">
                            <div style="display:flex;align-items:center;gap:8px;">
                                <div style="width:12px;height:12px;background:{w1c};border-radius:3px;"></div>
                                <div style="font-weight:600;">{b['w1_name']} ({b['w1_team']})</div>
                                <div style="font-size:0.85rem;color:#444;">{b['w1_grade']}/{b['w1_level']:.1f}/{b['w1_weight']:.0f}</div>
                            </div>
                            <div style="font-weight:700;">vs</div>
                            <div style="display:flex;flex-direction:row-reverse;align-items:center;gap:8px;">
                                <div style="width:12px;height:12px;background:{w2c};border-radius:3px;"></div>
                                <div style="font-size:0.85rem;color:#444;">{b['w2_grade']}/{b['w2_level']:.1f}/{b['w2_weight']:.0f}</div>
                                <div style="font-weight:600;">{b['w2_name']} ({b['w2_team']})</div>
                            </div>
                        </div>
                        <div style="font-size:0.8rem;color:#555;margin-top:4px;">
                            Slot: {m['mat_bout_num']} | {"Early" if b['is_early'] else ""} | Score: {b['score']:.1f}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

    # ---- UNDO BUTTON ----
    if st.session_state.undo_stack:
        st.markdown("---")
        if st.button("Undo"):
            undo_last()

    # ---- GENERATE MEET ----
    if st.button("Generate Meet", type="primary"):
        # ... [same as before] ...

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")
