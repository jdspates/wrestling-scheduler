# app.py – Wrestling Scheduler – FINAL CLEAN VERSION - 946 111325
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

# ---------- Safe PatternFill import ----------
try:
    from openpyxl.styles import PatternFill
    _EXCEL_AVAILABLE = True
except Exception:
    _EXCEL_AVAILABLE = False

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

# Safe config load
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as f:
            CONFIG = json.load(f)
            if not isinstance(CONFIG, dict):
                raise ValueError
    except Exception:
        CONFIG = DEFAULT_CONFIG.copy()
        with open(CONFIG_FILE, "w") as f:
            json.dump(CONFIG, f, indent=4)
else:
    CONFIG = DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)

TEAMS = CONFIG["TEAMS"]

# ----------------------------------------------------------------------
# SESSION STATE
# ----------------------------------------------------------------------
for key in ["initialized","bout_list","mat_schedules","suggestions","active","undo_stack","mat_order","excel_bytes","pdf_bytes"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list","mat_schedules","suggestions","active","undo_stack"] else {} if key == "mat_order" else None if key in ["excel_bytes","pdf_bytes"] else None

# ----------------------------------------------------------------------
# CORE LOGIC
# ----------------------------------------------------------------------
def is_compatible(w1, w2):
    return w1["team"] != w2["team"] and not (
        (w1["grade"] == 5 and w2["grade"] in [7, 8]) or (w2["grade"] == 5 and w1["grade"] in [7, 8])
    )

def max_weight_diff(w):
    return max(CONFIG["MIN_WEIGHT_DIFF"], w * CONFIG["WEIGHT_DIFF_FACTOR"])

def matchup_score(w1, w2):
    return round(abs(w1["weight"] - w2["weight"]) + abs(w1["level"] - w2["level"]) * 10, 1)

def generate_initial_matchups(active):
    bouts = set()
    for level in sorted({w["level"] for w in active}, reverse=True):
        group = [w for w in active if w["level"] == level]
        while True:
            added = False
            random.shuffle(group)
            for w in group:
                if len(w["match_ids"]) >= CONFIG["MAX_MATCHES"]: continue
                opps = [o for o in active
                        if o["id"] not in w["match_ids"]
                        and o["id"] != w["id"]
                        and len(o["match_ids"]) < CONFIG["MAX_MATCHES"]
                        and is_compatible(w, o)
                        and abs(w["weight"] - o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"]))
                        and abs(w["level"] - o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
                if not opps: continue
                best = min(opps, key=lambda o: matchup_score(w, o))
                w["match_ids"].append(best["id"])
                best["match_ids"].append(w["id"])
                bouts.add(frozenset({w["id"], best["id"]}))
                added = True
                break
            if not added: break
    bout_list = []
    for idx, b in enumerate(bouts, 1):
        w1 = next(w for w in active if w["id"] == list(b)[0])
        w2 = next(w for w in active if w["id"] == list(b)[1])
        bout_list.append({
            "bout_num": idx, "w1_id": w1["id"], "w1_name": w1["name"], "w1_team": w1["team"],
            "w1_level": w1["level"], "w1_weight": w1["weight"], "w1_grade": w1["grade"], "w1_early": w1["early"],
            "w2_id": w2["id"], "w2_name": w2["name"], "w2_team": w2["team"],
            "w2_level": w2["level"], "w2_weight": w2["weight"], "w2_grade": w2["grade"], "w2_early": w2["early"],
            "score": matchup_score(w1, w2), "avg_weight": (w1["weight"] + w2["weight"]) / 2,
            "is_early": w1["early"] or w2["early"], "manual": ""
        })
    return bout_list

def build_suggestions(active, bout_list):
    under = [w for w in active if len(w["match_ids"]) < CONFIG["MIN_MATCHES"]]
    sugg = []
    for w in under:
        opps = [o for o in active if o["id"] not in w["match_ids"] and o["id"] != w["id"]]
        opps = [o for o in opps if abs(w["weight"]-o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"])) and abs(w["level"]-o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
        if not opps: opps = [o for o in active if o["id"] not in w["match_ids"] and o["id"] != w["id"]]
        for o in sorted(opps, key=lambda o: matchup_score(w, o))[:3]:
            sugg.append({
                "wrestler": w["name"], "team": w["team"], "level": w["level"], "weight": w["weight"],
                "current": len(w["match_ids"]), "vs": o["name"], "vs_team": o["team"],
                "vs_current": len(o["match_ids"]), "vs_level": o["level"], "vs_weight": o["weight"], "score": matchup_score(w, o),
                "_w_id": w["id"], "_o_id": o["id"]
            })
    return sugg

def generate_mat_schedule(bout_list, gap=4):
    valid = [b for b in bout_list if b["manual"] != "Manually Removed"]
    
    # SORT BY AVERAGE WEIGHT FIRST (lightest to heaviest)
    valid.sort(key=lambda x: x["avg_weight"])
    
    # DISTRIBUTE ACROSS MATS (lightest on Mat 1, heaviest on last mat)
    per_mat = len(valid) // CONFIG["NUM_MATS"]
    extra = len(valid) % CONFIG["NUM_MATS"]
    mats = []
    start = 0
    for i in range(CONFIG["NUM_MATS"]):
        end = start + per_mat + (1 if i < extra else 0)
        mats.append(valid[start:end])
        start = end

    schedules = []
    last_slot = {}
    for mat_num, mat_bouts in enumerate(mats, 1):
        early_bouts = [b for b in mat_bouts if b["is_early"]]
        non_early_bouts = [b for b in mat_bouts if not b["is_early"]]
        total_slots = len(mat_bouts)
        first_half_end = (total_slots + 1) // 2
        slot = 1
        scheduled = []
        first_half_wrestlers = set()

        # Try to place first early match at slot 1
        first_early = None
        for b in early_bouts:
            l1 = last_slot.get(b["w1_id"], -100)
            l2 = last_slot.get(b["w2_id"], -100)
            if l1 < 0 and l2 < 0:
                first_early = b
                break
        if first_early:
            early_bouts.remove(first_early)
            scheduled.append((1, first_early))
            last_slot[first_early["w1_id"]] = 1
            last_slot[first_early["w2_id"]] = 1
            first_half_wrestlers.update([first_early["w1_id"], first_early["w2_id"]])
            slot = 2

        # Fill first half with early matches
        while early_bouts and len(scheduled) < first_half_end:
            best = None
            best_score = -float("inf")
            for b in early_bouts:
                if b["w1_id"] in first_half_wrestlers or b["w2_id"] in first_half_wrestlers: continue
                l1 = last_slot.get(b["w1_id"], -100)
                l2 = last_slot.get(b["w2_id"], -100)
                if l1 >= slot - 1 or l2 >= slot - 1: continue
                score = min(slot - l1 - 1, slot - l2 - 1)
                if score > best_score:
                    best_score = score
                    best = b
            if best is None: break
            early_bouts.remove(best)
            scheduled.append((slot, best))
            last_slot[best["w1_id"]] = slot
            last_slot[best["w2_id"]] = slot
            first_half_wrestlers.update([best["w1_id"], best["w2_id"]])
            slot += 1

        # Fill remaining with gap logic
        remaining = non_early_bouts + early_bouts
        while remaining:
            best = None
            best_gap = -1
            for b in remaining:
                l1 = last_slot.get(b["w1_id"], -100)
                l2 = last_slot.get(b["w2_id"], -100)
                if l1 >= slot - gap or l2 >= slot - gap: continue
                gap_val = min(slot - l1 - 1, slot - l2 - 1)
                if gap_val > best_gap:
                    best_gap = gap_val
                    best = b
            if best is None:
                best = remaining[0]
            remaining.remove(best)
            scheduled.append((slot, best))
            last_slot[best["w1_id"]] = slot
            last_slot[best["w2_id"]] = slot
            slot += 1

        for s, b in scheduled:
            schedules.append({
                "mat": mat_num,
                "slot": s,
                "bout_num": b["bout_num"],
                "w1": f"{b['w1_name']} ({b['w1_team']})",
                "w2": f"{b['w2_name']} ({b['w2_team']})",
                "w1_team": b["w1_team"],
                "w2_team": b["w2_team"],
                "is_early": b["is_early"]
            })

    # Assign mat_bout_num
    for mat_num in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [m for m in schedules if m["mat"] == mat_num]
        mat_entries.sort(key=lambda x: x["slot"])
        for idx, entry in enumerate(mat_entries, 1):
            entry["mat_bout_num"] = idx

    return schedules

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def remove_match(bout_num):
    b = next(x for x in st.session_state.bout_list if x["bout_num"] == bout_num)
    b["manual"] = "Manually Removed"
    w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
    w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
    if b["w2_id"] in w1["match_ids"]: w1["match_ids"].remove(b["w2_id"])
    if b["w1_id"] in w2["match_ids"]: w2["match_ids"].remove(b["w1_id"])
    st.session_state.undo_stack.append(bout_num)
    st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
    st.session_state.mat_order = {}
    st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
    st.success("Match removed.")
    st.session_state.excel_bytes = None
    st.session_state.pdf_bytes = None
    st.rerun()

def undo_last():
    if st.session_state.undo_stack:
        bout_num = st.session_state.undo_stack.pop()
        b = next(x for x in st.session_state.bout_list if x["bout_num"] == bout_num and x["manual"] == "Manually Removed")
        b["manual"] = ""
        w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
        w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
        if b["w2_id"] not in w1["match_ids"]: w1["match_ids"].append(b["w2_id"])
        if b["w1_id"] not in w2["match_ids"]: w2["match_ids"].append(w["w1_id"])
        st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
        st.session_state.mat_order = {}
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.success("Undo successful!")
        st.session_state.excel_bytes = None
        st.session_state.pdf_bytes = None
    st.rerun()

def move_up(mat, bout_num):
    if mat in st.session_state.mat_order:
        order = st.session_state.mat_order[mat]
        if bout_num in order:
            idx = order.index(bout_num)
            if idx > 0:
                order[idx-1], order[idx] = order[idx], order[idx-1]

def move_down(mat, bout_num):
    if mat in st.session_state.mat_order:
        order = st.session_state.mat_order[mat]
        if bout_num in order:
            idx = order.index(bout_num)
            if idx < len(order) - 1:
                order[idx], order[idx+1] = order[idx+1], order[idx]

# ----------------------------------------------------------------------
# STREAMLIT APP
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.markdown("""
<style>
    div[data-testid="stExpander"] > div > div { padding:0 !important; margin:0 !important; }
    div[data-testid="stVerticalBlock"] > div { gap:0 !important; }
    .block-container { padding:2rem 1rem !important; max-width:1200px !important; margin:0 auto !important; }
    .main .block-container { padding-left:2rem !important; padding-right:2rem !important; }
    h1 { margin-top:0 !important; }
    .main .stButton > button {
        min-width: 30px;
        height: 30px;
        padding: 0;
        font-size: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .stSidebar .stButton > button {
        padding: 0.5rem 1rem !important;
        height: auto !important;
        min-width: auto !important;
    }
    .stTextInput > div > div > input { border-radius: 6px !important; }
    .stTextInput > div > div > button { background: transparent !important; border: none !important; color: #888 !important; }
    .stButton > button[key^="del_"] { line-height: 30px !important; font-size: 18px !important; }
</style>
""", unsafe_allow_html=True)

st.title("Wrestling Meet Scheduler")
st.caption("Upload roster to Generate to Edit to Download. **No data stored.**")

# ---- UPLOAD ----
uploaded = st.file_uploader("Upload `roster.csv`", type="csv")
if uploaded and not st.session_state.initialized:
    try:
        df = pd.read_csv(uploaded)
        required = ["id","name","team","grade","level","weight","early_matches","scratch"]
        if not all(c in df.columns for c in required):
            st.error("Missing columns. Need: " + ", ".join(required))
            st.stop()
        wrestlers = df.to_dict("records")
        for w in wrestlers:
            w["id"] = int(w["id"])
            w["grade"] = int(w["grade"])
            w["level"] = float(w["level"])
            w["weight"] = float(w["weight"])
            w["early"] = (str(w["early_matches"]).strip().upper() == "Y") or (w["early_matches"] in [1,True])
            w["scratch"] = (str(w["scratch"]).strip().upper() == "Y") or (w["scratch"] in [1,True])
            w["match_ids"] = []
        st.session_state.active = [w for w in wrestlers if not w["scratch"]]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
        st.session_state.initialized = True
        st.success("Roster loaded and matchups generated!")
    except Exception as e:
        st.error(f"Error: {e}")

# ---- SETTINGS ----
st.sidebar.header("Meet Settings")
st.sidebar.subheader("Search Wrestlers")
search_term = st.sidebar.text_input(
    "Filter by name or team",
    value="",
    placeholder="e.g. Smith or Red",
    key="wrestler_search",
    help="Live filter – shows all matches for matching wrestlers in Mat Previews"
)
st.sidebar.caption("**Note:** This search filters **Mat Previews only**. Suggested Matches show all under-matched wrestlers.")
changed = False
st.sidebar.subheader("Match & Scheduling Rules")
c1, c2 = st.sidebar.columns(2)
with c1:
    new_min = st.number_input("Min Matches per Wrestler", 1, 10, CONFIG["MIN_MATCHES"], key="min_matches")
    new_max = st.number_input("Max Matches per Wrestler", 1, 10, CONFIG["MAX_MATCHES"], key="max_matches")
    new_mats = st.number_input("Number of Mats", 1, 10, CONFIG["NUM_MATS"], key="num_mats")
with c2:
    new_level_diff = st.number_input("Max Level Difference", 0, 5, CONFIG["MAX_LEVEL_DIFF"], key="max_level_diff")
    new_weight_factor = st.slider("Weight Diff % Factor", 0.0, 0.5, CONFIG["WEIGHT_DIFF_FACTOR"], 0.01,
                                  format="%.2f", key="weight_factor")
    new_min_weight = st.number_input("Min Weight Diff (lbs)", 0.0, 50.0, CONFIG["MIN_WEIGHT_DIFF"], 0.5,
                                     key="min_weight_diff")
if new_min > new_max:
    st.sidebar.error("Min Matches cannot exceed Max Matches!")
    new_min = new_max
st.sidebar.markdown("---")
st.sidebar.subheader("Team Names & Colors")
for i in range(5):
    team = TEAMS[i]
    st.sidebar.markdown(f"**Team {i+1}**")
    new_name = st.sidebar.text_input("Name", team["name"], key=f"name_{i}", label_visibility="collapsed")
    new_color = st.sidebar.selectbox(
        "Color", list(COLOR_MAP.keys()),
        index=list(COLOR_MAP.keys()).index(team["color"]),
        format_func=lambda x: x.capitalize(),
        key=f"color_{i}", label_visibility="collapsed"
    )
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
if st.sidebar.button("Reset", type="secondary"):
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
# MAIN APP – SEARCH + CLEAN MATS
# ----------------------------------------------------------------------
if st.session_state.initialized:
    raw_active = st.session_state.active
    if search_term.strip():
        term = search_term.strip().lower()
        filtered_active = [
            w for w in raw_active
            if term in w["name"].lower() or term in w["team"].lower()
        ]
        st.info(f"Showing **{len(filtered_active)}** wrestler(s) matching “{search_term}” (out of {len(raw_active)} total).")
    else:
        filtered_active = raw_active
        st.info(f"Showing **all {len(filtered_active)}** wrestlers.")

    st.subheader("Suggested Matches")
    current_suggestions = build_sSuggestions(filtered_active, st.session_state.bout_list)
    under_count = len([w for w in filtered_active if len(w["match_ids"]) < CONFIG["MIN_MATCHES"]])
    st.caption(f"**{under_count}** of **{len(filtered_active)}** filtered wrestler(s) need more matches.")
    if current_suggestions:
        sugg_data = []
        for i, s in enumerate(current_suggestions):
            w = next(w for w in filtered_active if w["id"] == s["_w_id"])
            o = next(o for o in filtered_active if o["id"] == s["_o_id"])
            sugg_data.append({
                "Add": False,
                "Current": f"{len(w['match_ids'])}",
                "Wrestler": f"{w['name']} ({w['team']})",
                "Lvl": f"{w['level']:.1f}",
                "Wt": f"{w['weight']:.0f}",
                "vs_Current": f"{len(o['match_ids'])}",
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
                "Current": st.column_config.NumberColumn("Current"),
                "Wrestler": st.column_config.TextColumn("Wrestler"),
                "Lvl": st.column_config.NumberColumn("Lvl"),
                "Wt": st.column_config.NumberColumn("Wt"),
                "vs_Current": st.column_config.NumberColumn("vs_Current"),
                "vs": st.column_config.TextColumn("vs"),
                "vs_Lvl": st.column_config.NumberColumn("vs_Lvl"),
                "vs_Wt": st.column_config.NumberColumn("vs_Wt"),
                "Score": st.column_config.NumberColumn("Score"),
            },
            use_container_width=True,
            hide_index=True,
            key="sugg_editor"
        )
        if st.button("Add Selected", help="Add checked suggested matches"):
            to_add = [current_suggestions[sugg_full_df.iloc[row.name]["idx"]]
                      for _, row in edited.iterrows() if row["Add"]]
            for s in to_add:
                w = next(w for w in raw_active if w["id"] == s["_w_id"])
                o = next(o for o in raw_active if o["id"] == s["_o_id"])
                if o["id"] not in w["match_ids"]: w["match_ids"].append(o["id"])
                if w["id"] not in o["match_ids"]: o["match_ids"].append(w["id"])
                st.session_state.bout_list.append({
                    "bout_num": len(st.session_state.bout_list)+1,
                    "w1_id": w["id"], "w1_name": w["name"], "w1_team": w["team"],
                    "w1_level": w["level"], "w1_weight": w["weight"], "w1_grade": w["grade"], "w1_early": w["early"],
                    "w2_id": o["id"], "w2_name": o["name"], "w2_team": o["team"],
                    "w2_level": o["level"], "w2_weight": o["weight"], "w2_grade": o["grade"], "w2_early": o["early"],
                    "score": s["score"], "avg_weight": (w["weight"]+o["weight"])/2,
                    "is_early": w["early"] or o["early"], "manual": "Manually Added"
                })
            st.session_state.suggestions = build_suggestions(raw_active, st.session_state.bout_list)
            st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
            st.session_state.mat_order = {}
            st.success("Matches added!")
            st.session_state.excel_bytes = None
            st.session_state.pdf_bytes = None
            st.rerun()
    else:
        st.info("All filtered wrestlers have 2+ matches. No suggestions needed.")

    st.subheader("Mat Previews")
    filtered_ids = {w["id"] for w in filtered_active}
    filtered_bout_list = [
        b for b in st.session_state.bout_list
        if b["w1_id"] in filtered_ids or b["w2_id"] in filtered_ids
    ]
    filtered_schedule = generate_mat_schedule(filtered_bout_list) if filtered_bout_list else []
    bout_to_mat = {entry["bout_num"]: entry["mat"] for entry in filtered_schedule}
    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        mat_bouts = [b for b in filtered_bout_list if bout_to_mat.get(b["bout_num"]) == mat]
        with st.expander(f"Mat {mat}", expanded=True):
            if not mat_bouts:
                pass
            else:
                if mat not in st.session_state.mat_order:
                    st.session_state.mat_order[mat] = [b["bout_num"] for b in mat_bouts]
                ordered_bouts = []
                for bout_num in st.session_state.mat_order[mat]:
                    entry = next((e for e in filtered_schedule if e["bout_num"] == bout_num), None)
                    if entry:
                        ordered_bouts.append(entry)
                for idx, m in enumerate(ordered_bouts):
                    b = next(x for x in st.session_state.bout_list if x["bout_num"] == m["bout_num"])
                    bg = "#fff3cd" if b["is_early"] else "#ffffff"
                    w1c = TEAM_COLORS.get(b["w1_team"], "#999")
                    w2c = TEAM_COLORS.get(b["w2_team"], "#999")
                    col_up, col_down, col_del, col_card = st.columns([0.05, 0.05, 0.05, 1], gap="small")
                    with col_up:
                        st.button("Up", key=f"up_{mat}_{b['bout_num']}_{idx}", on_click=move_up, args=(mat, b['bout_num']), help="Move up")
                    with col_down:
                        st.button("Down", key=f"down_{mat}_{b['bout_num']}_{idx}", on_click=move_down, args=(mat, b['bout_num']), help="Move down")
                    with col_del:
                        st.button("X", key=f"del_{b['bout_num']}_{idx}", help="Remove match (Undo available)", on_click=remove_match, args=(b['bout_num'],))
                    with col_card:
                        st.markdown(f"""
                        <div class="card-container" data-bout="{b['bout_num']}" style="background:{bg}; border:1px solid #ddd; padding:8px; border-radius:4px; margin-bottom:4px;">
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
                                Slot: {idx+1} | {"Early" if b['is_early'] else ""} | Score: {b['score']:.1f}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

    if st.session_state.undo_stack:
        st.markdown("---")
        if st.button("Undo", help="Restore last removed match"):
            undo_last()

    # ---- GENERATE MEET ----
    if st.button("Generate Matches", type="primary", help="Download Excel + PDF"):
        with st.spinner("Generating files..."):
            try:
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as writer:
                    # Roster sheet
                    roster_df = pd.DataFrame(st.session_state.active)
                    roster_df.to_excel(writer, sheet_name='Roster', index=False)

                    # Matchups sheet
                    matchups_df = pd.DataFrame(st.session_state.bout_list)
                    matchups_df.to_excel(writer, sheet_name='Matchups', index=False)

                    # Remaining Suggestions sheet
                    suggestions_df = pd.DataFrame(st.session_state.suggestions)
                    suggestions_df.to_excel(writer, sheet_name='Remaining Suggestions', index=False)

                    # Mat sheets
                    for m in range(1, CONFIG["NUM_MATS"]+1):
                        data = [e for e in st.session_state.mat_schedules if e["mat"] == m]
                        if not data:
                            pd.DataFrame([["", "", ""]], columns=["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]).to_excel(writer, f"Mat {m}", index=False)
                            continue
                        df = pd.DataFrame(data)[["mat_bout_num","w1","w2"]]
                        df.columns = ["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]
                        df.to_excel(writer, f"Mat {m}", index=False)
                        if _EXCEL_AVAILABLE:
                            ws = writer.book[f"Mat {m}"]
                            fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
                            for i, _ in df.iterrows():
                                if next(b for b in st.session_state.bout_list if b["bout_num"] == data[i]["bout_num"])["is_early"]:
                                    for c in range(1,4): ws.cell(row=i+2, column=c).fill = fill
                st.session_state.excel_bytes = out.getvalue()

                buf = io.BytesIO()
                doc = SimpleDocTemplate(buf, pagesize=letter); elements = []; styles = getSampleStyleSheet()
                for m in range(1, CONFIG["NUM_MATS"]+1):
                    data = [e for e in st.session_state.mat_schedules if e["mat"] == m]
                    if not data:
                        elements.append(Paragraph(f"Mat {m} - No matches", styles["Title"])); elements.append(PageBreak()); continue
                    table = [["#","Wrestler 1","Wrestler 2"]]
                    for e in data:
                        b = next(x for x in st.session_state.bout_list if x["bout_num"] == e["bout_num"])
                        table.append([e["mat_bout_num"],
                                      Paragraph(f'<font color="{TEAM_COLORS.get(b["w1_team"],"#000")}"><b>{b["w1_name"]}</b></font> ({b["w1_team"]})', styles["Normal"]),
                                      Paragraph(f'<font color="{TEAM_COLORS.get(b["w2_team"],"#000")}"><b>{b["w2_name"]}</b></font> ({b["w2_team"]})', styles["Normal"])])
                    t = Table(table, colWidths=[0.5*inch, 3*inch, 3*inch])
                    s = TableStyle([("GRID",(0,0),(-1,-1),0.5,rl_colors.black),
                                    ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
                                    ("BACKGROUND",(0,0),(-1,0),rl_colors.lightgrey),
                                    ("ALIGN",(0,0),(-1,-1),"LEFT"),
                                    ("VALIGN",(0,0),(-1,-1),"MIDDLE")])
                    for r, _ in enumerate(table[1:], 1):
                        if next(b for b in st.session_state.bout_list if b["bout_num"] == data[r-1]["bout_num"])["is_early"]:
                            s.add("BACKGROUND", (0, r), (-1, r), HexColor("#FFFF99"))
                    t.setStyle(s)
                    elements += [Paragraph(f"Mat {m}", styles["Title"]), Spacer(1,12), t]
                    if m < CONFIG["NUM_MATS"]: elements.append(PageBreak())
                doc.build(elements)
                st.session_state.pdf_bytes = buf.getvalue()

                st.toast("Files generated!")
            except Exception as e:
                st.error(f"Generation failed: {e}")
                st.toast("Error – check console.")

# Show buttons persistently
col_ex, col_pdf = st.columns(2)
with col_ex:
    if st.session_state.excel_bytes is not None:
        st.download_button(
            label="Download Excel",
            data=st.session_state.excel_bytes,
            file_name="meet_schedule.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
with col_pdf:
    if st.session_state.pdf_bytes is not None:
        st.download_button(
            label="Download PDF",
            data=st.session_state.pdf_bytes,
            file_name="meet_schedule.pdf",
            mime="application/pdf",
            use_container_width=True
        )

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")

