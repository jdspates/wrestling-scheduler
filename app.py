# app.py – Wrestling Scheduler – drag rows + rest gap warnings + scratches + manual matches
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
import copy

from streamlit_sortables import sort_items  # drag-and-drop component

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

# 9-color palette that matches circle emojis
COLOR_MAP = {
    "red": "#FF0000",
    "orange": "#FF7F00",
    "yellow": "#FFD700",
    "green": "#008000",
    "blue": "#0000FF",
    "purple": "#800080",
    "brown": "#8B4513",
    "black": "#000000",
    "white": "#FFFFFF",
}

# Circle emojis – one per color, no duplicates
COLOR_ICON = {
    "red": "🔴",
    "orange": "🟠",
    "yellow": "🟡",
    "green": "🟢",
    "blue": "🔵",
    "purple": "🟣",
    "brown": "🟤",
    "black": "⚫",
    "white": "⚪",
}

DEFAULT_CONFIG = {
    "MIN_MATCHES": 2,
    "MAX_MATCHES": 4,
    "NUM_MATS": 4,
    "MAX_LEVEL_DIFF": 1,
    "WEIGHT_DIFF_FACTOR": 0.10,
    "MIN_WEIGHT_DIFF": 5.0,
    "REST_GAP": 4,  # minimum matches between bouts for same wrestler
    # TEAMS will be rebuilt from roster CSV once uploaded
    "TEAMS": []
}

# ----------------------------------------------------------------------
# ROSTER TEMPLATE (for new coaches)
# ----------------------------------------------------------------------
# Columns MUST match what the app expects below:
# ["id", "name", "team", "grade", "level", "weight", "early_matches", "scratch"]
TEMPLATE_CSV = """id,name,team,grade,level,weight,early_matches,scratch
1,John Doe,Stillwater,7,1.0,70,Y,N
2,Jane Smith,Hastings,8,1.5,75,N,N
3,Ben Carter,Cottage Grove,6,2.0,80,N,N
4,Ava Johnson,Woodbury,7,1.0,68,Y,N
"""

# Load base config once (read-only default, e.g. from repo)
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                BASE_CONFIG = loaded
            else:
                BASE_CONFIG = DEFAULT_CONFIG
    except Exception:
        BASE_CONFIG = DEFAULT_CONFIG
else:
    BASE_CONFIG = DEFAULT_CONFIG

# ----------------------------------------------------------------------
# STYLES
# ----------------------------------------------------------------------
SORTABLE_STYLE = """
.sortable-component {
    background-color: transparent;
    border: none;
    padding: 0;
}
.sortable-container {
    background-color: transparent;
    border: none;
    box-shadow: none;
}
.sortable-container-header {
    display: none;
}
.sortable-container-body {
    background-color: transparent;
    padding: 0;
}
.sortable-item {
    background-color: #ffffff;
    color: #222 !important;
    border-radius: 4px;
    border: 1px solid #ddd;
    padding: 0 8px;
    margin-bottom: 4px;
    font-size: 0.85rem;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    cursor: grab;

    height: 36px;
    display: flex;
    align-items: center;
}
.sortable-item:hover {
    background-color: #f7f7f7;
    color: #222 !important;
}
"""

# ----------------------------------------------------------------------
# SESSION STATE
# ----------------------------------------------------------------------
# Per-session CONFIG, cloned from BASE_CONFIG once
if "CONFIG" not in st.session_state:
    st.session_state.CONFIG = copy.deepcopy(BASE_CONFIG)

CONFIG = st.session_state.CONFIG  # convenience reference

for key in [
    "initialized", "bout_list", "mat_schedules", "suggestions",
    "active", "undo_stack", "mat_order", "excel_bytes", "pdf_bytes",
    "roster", "mat_order_history", "manual_match_warning"
]:
    if key not in st.session_state:
        if key in ["bout_list", "mat_schedules", "suggestions", "active", "undo_stack"]:
            st.session_state[key] = []
        elif key == "mat_order":
            st.session_state[key] = {}
        elif key in ["roster", "mat_order_history"]:
            st.session_state[key] = []
        elif key == "manual_match_warning":
            st.session_state[key] = ""
        else:
            st.session_state[key] = None

# version bump for sortable widgets so they refresh on add/remove/undo/scratches/color changes
if "sortable_version" not in st.session_state:
    st.session_state.sortable_version = 0

# ----------------------------------------------------------------------
# CORE LOGIC
# ----------------------------------------------------------------------
def is_compatible(w1, w2):
    return w1["team"] != w2["team"] and not (
        (w1["grade"] == 5 and w2["grade"] in [7, 8]) or
        (w2["grade"] == 5 and w1["grade"] in [7, 8])
    )

def max_weight_diff(w):
    return max(CONFIG["MIN_WEIGHT_DIFF"], w * CONFIG["WEIGHT_DIFF_FACTOR"])

def matchup_score(w1, w2):
    return round(
        abs(w1["weight"] - w2["weight"]) +
        abs(w1["level"] - w2["level"]) * 10, 1
    )

def generate_initial_matchups(active):
    bouts = set()
    for level in sorted({w["level"] for w in active}, reverse=True):
        group = [w for w in active if w["level"] == level]
        while True:
            added = False
            random.shuffle(group)
            for w in group:
                if len(w["match_ids"]) >= CONFIG["MAX_MATCHES"]:
                    continue
                opps = [
                    o for o in active
                    if o["id"] not in w["match_ids"]
                    and o["id"] != w["id"]
                    and len(o["match_ids"]) < CONFIG["MAX_MATCHES"]
                    and is_compatible(w, o)
                    and abs(w["weight"] - o["weight"]) <= \
                        min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"]))
                    and abs(w["level"] - o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]
                ]
                if not opps:
                    continue
                best = min(opps, key=lambda o: matchup_score(w, o))
                w["match_ids"].append(best["id"])
                best["match_ids"].append(w["id"])
                bouts.add(frozenset({w["id"], best["id"]}))
                added = True
                break
            if not added:
                break

    bout_list = []
    for idx, b in enumerate(bouts, 1):
        w1 = next(w for w in active if w["id"] == list(b)[0])
        w2 = next(w for w in active if w["id"] == list(b)[1])
        bout_list.append({
            "bout_num": idx,
            "w1_id": w1["id"], "w1_name": w1["name"], "w1_team": w1["team"],
            "w1_level": w1["level"], "w1_weight": w1["weight"],
            "w1_grade": w1["grade"], "w1_early": w1["early"],
            "w2_id": w2["id"], "w2_name": w2["name"], "w2_team": w2["team"],
            "w2_level": w2["level"], "w2_weight": w2["weight"],
            "w2_grade": w2["grade"], "w2_early": w2["early"],
            "score": matchup_score(w1, w2),
            "avg_weight": (w1["weight"] + w2["weight"]) / 2,
            "is_early": w1["early"] or w2["early"],
            "manual": ""
        })
    return bout_list

def build_suggestions(active, bout_list):
    under = [w for w in active if len(w["match_ids"]) < CONFIG["MIN_MATCHES"]]
    sugg = []
    for w in under:
        opps = [o for o in active if o["id"] not in w["match_ids"] and o["id"] != w["id"]]
        opps = [
            o for o in opps
            if abs(w["weight"] - o["weight"]) <= \
                min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"]))
            and abs(w["level"] - o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]
        ]
        if not opps:
            opps = [o for o in active if o["id"] not in w["match_ids"] and o["id"] != w["id"]]
        for o in sorted(opps, key=lambda o: matchup_score(w, o))[:3]:
            sugg.append({
                "wrestler": w["name"], "team": w["team"],
                "level": w["level"], "weight": w["weight"],
                "current": len(w["match_ids"]),
                "vs": o["name"], "vs_team": o["team"],
                "vs_current": len(o["match_ids"]),
                "vs_level": o["level"], "vs_weight": o["weight"],
                "score": matchup_score(w, o),
                "_w_id": w["id"], "_o_id": o["id"]
            })
    return sugg

def generate_mat_schedule(bout_list, gap=4):
    """Base scheduling algorithm (ignores manual ordering, respects manual removals)."""
    valid = [b for b in bout_list if b["manual"] != "Manually Removed"]
    valid = sorted(valid, key=lambda x: x["avg_weight"])  # Light to heavy

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

        # First early match if possible
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

        # More early matches in first half
        while early_bouts and len(scheduled) < first_half_end:
            best = None
            best_score = -float("inf")
            for b in early_bouts:
                if b["w1_id"] in first_half_wrestlers or b["w2_id"] in first_half_wrestlers:
                    continue
                l1 = last_slot.get(b["w1_id"], -100)
                l2 = last_slot.get(b["w2_id"], -100)
                if l1 >= slot - 1 or l2 >= slot - 1:
                    continue
                score = min(slot - l1 - 1, slot - l2 - 1)
                if score > best_score:
                    best_score = score
                    best = b
            if best is None:
                break
            early_bouts.remove(best)
            scheduled.append((slot, best))
            last_slot[best["w1_id"]] = slot
            last_slot[best["w2_id"]] = slot
            first_half_wrestlers.update([best["w1_id"], best["w2_id"]])
            slot += 1

        # Remaining matches
        remaining = non_early_bouts + early_bouts
        while remaining:
            best = None
            best_gap = -1
            for b in remaining:
                l1 = last_slot.get(b["w1_id"], -100)
                l2 = last_slot.get(b["w2_id"], -100)
                if l1 >= slot - gap or l2 >= slot - gap:
                    continue
                gap_val = min(slot - l1 - 1, slot - l2 - 1)
                if gap_val > best_gap:
                    best_gap = gap_val
                    best = b
            if best is None and remaining:
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

    for mat_num in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [m for m in schedules if m["mat"] == mat_num]
        mat_entries.sort(key=lambda x: x["slot"])
        for idx, entry in enumerate(mat_entries, 1):
            entry["mat_bout_num"] = idx

    return schedules

def apply_mat_order_to_global_schedule():
    """
    Take the base schedule, then reorder each mat according to st.session_state.mat_order,
    and recompute slot + mat_bout_num so exports and previews match the dragged order.
    """
    rest_gap = CONFIG.get("REST_GAP", 4)
    base = generate_mat_schedule(st.session_state.bout_list, gap=rest_gap)
    schedules = []

    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        entries = [e for e in base if e["mat"] == mat]
        order = st.session_state.mat_order.get(mat)

        if order:
            entries_sorted = sorted(
                entries,
                key=lambda e: (
                    order.index(e["bout_num"])
                    if e["bout_num"] in order
                    else len(order) + e["slot"]
                )
            )
        else:
            entries_sorted = sorted(entries, key=lambda e: e["slot"])

        for idx, e in enumerate(entries_sorted, start=1):
            e["slot"] = idx
            e["mat_bout_num"] = idx
            schedules.append(e)

    return schedules

def compute_rest_conflicts(schedule, min_gap):
    """
    Given a flat schedule (list of entries with mat, slot, bout_num),
    find wrestlers who have matches too close together (slot difference < min_gap).
    Returns a list of dicts with details for display.
    """
    appearances = {}

    for e in schedule:
        b = next(x for x in st.session_state.bout_list if x["bout_num"] == e["bout_num"])

        for w_id, name, team in [
            (b["w1_id"], b["w1_name"], b["w1_team"]),
            (b["w2_id"], b["w2_name"], b["w2_team"]),
        ]:
            if w_id not in appearances:
                appearances[w_id] = {
                    "name": name,
                    "team": team,
                    "matches": []
                }
            appearances[w_id]["matches"].append((e["mat"], e["slot"], e["bout_num"]))

    conflicts = []

    for w_id, info in appearances.items():
        by_mat = {}
        for mat, slot, bout_num in info["matches"]:
            by_mat.setdefault(mat, []).append((slot, bout_num))

        for mat, matches in by_mat.items():
            matches.sort(key=lambda x: x[0])  # sort by slot
            for (slot1, bout1), (slot2, bout2) in zip(matches, matches[1:]):
                gap = slot2 - slot1
                if gap < min_gap:
                    conflicts.append({
                        "wrestler_id": w_id,
                        "wrestler": info["name"],
                        "team": info["team"],
                        "mat": mat,
                        "slot1": slot1,
                        "slot2": slot2,
                        "bout1": bout1,
                        "bout2": bout2,
                        "gap": gap,
                    })

    return conflicts

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def color_dot_hex(hex_color: str) -> str:
    """Return a small HTML circle for the given hex color (for legends / HTML tables)."""
    if not hex_color:
        return ""
    return (
        "<span style='display:inline-block;width:12px;height:12px;"
        f"border-radius:50%;background:{hex_color};margin-right:6px;'></span>"
    )

def remove_bout(bout_num: int):
    """Mark bout as manually removed, update wrestler match_ids, trim from mat_order."""
    try:
        b = next(x for x in st.session_state.bout_list if x["bout_num"] == bout_num)
    except StopIteration:
        return
    if b.get("manual") == "Manually Removed":
        return

    b["manual"] = "Manually Removed"
    w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
    w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
    if b["w2_id"] in w1["match_ids"]:
        w1["match_ids"].remove(b["w2_id"])
    if b["w1_id"] in w2["match_ids"]:
        w2["match_ids"].remove(b["w1_id"])

    st.session_state.undo_stack.append(bout_num)

    for mat, order in st.session_state.mat_order.items():
        if bout_num in order:
            order.remove(bout_num)

    # removing a bout changes layout; clear drag history
    st.session_state.mat_order_history = []

    st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
    st.session_state.excel_bytes = None
    st.session_state.pdf_bytes = None

    st.session_state.sortable_version += 1
    st.rerun()

def undo_last():
    if st.session_state.undo_stack:
        bout_num = st.session_state.undo_stack.pop()
        b = next(
            x for x in st.session_state.bout_list
            if x["bout_num"] == bout_num and x.get("manual") == "Manually Removed"
        )
        b["manual"] = ""
        w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
        w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
        if b["w2_id"] not in w1["match_ids"]:
            w1["match_ids"].append(b["w2_id"])
        if b["w1_id"] not in w2["match_ids"]:
            w2["match_ids"].append(b["w1_id"])
        st.session_state.bout_list.sort(key=lambda x: x["avg_weight"])
        st.session_state.mat_order = {}
        st.session_state.mat_order_history = []  # reset drag history after structural change
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.success("Undo successful!")
        st.session_state.excel_bytes = None
        st.session_state.pdf_bytes = None

        st.session_state.sortable_version += 1
    st.rerun()

def undo_last_drag():
    """Undo the last drag-based reorder across mats."""
    history = st.session_state.get("mat_order_history", [])
    if history:
        last_snapshot = history.pop()
        st.session_state.mat_order = last_snapshot
        st.session_state.excel_bytes = None
        st.session_state.pdf_bytes = None
        st.session_state.sortable_version += 1
        st.success("Last drag/reorder undone.")
        st.rerun()
    else:
        st.info("No drag operations to undo yet.")

def validate_roster_df(df: pd.DataFrame):
    """Return list of error messages if roster has issues; empty list if OK."""
    errors = []
    required = ["id", "name", "team", "grade", "level", "weight", "early_matches", "scratch"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        errors.append("Missing columns: " + ", ".join(missing))
        return errors

    if df.empty:
        errors.append("Roster file is empty (no wrestlers found).")

    # Duplicated IDs
    if df["id"].duplicated().any():
        dups = df["id"][df["id"].duplicated()].unique().tolist()
        errors.append(f"Duplicate wrestler IDs found: {dups}. IDs must be unique.")

    # Basic numeric checks
    for col in ["grade", "level", "weight"]:
        bad = pd.to_numeric(df[col], errors="coerce").isna()
        if bad.any():
            bad_vals = df.loc[bad, col].astype(str).unique().tolist()
            errors.append(f"Column '{col}' has non-numeric values: {bad_vals}")

    return errors

# ----------------------------------------------------------------------
# STREAMLIT APP LAYOUT
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")

st.markdown(
    """
<style>
    div[data-testid="stExpander"] > div > div { padding:0 !important; margin:0 !important; }
    div[data-testid="stVerticalBlock"] > div { gap:0 !important; }
    .block-container { padding:2rem 1rem !important; max-width:1200px !important; margin:0 auto !important; }
    .main .block-container { padding-left:2rem !important; padding-right:2rem !important; }
    h1 { margin-top:0 !important; }
    .stSidebar .stButton > button {
        padding: 0.5rem 1rem !important;
        height: auto !important;
        min-width: auto !important;
    }
    .stTextInput > div > div > input { border-radius: 6px !important; }
    .stTextInput > div > div > button {
        background: transparent !important;
        border: none !important;
        color: #888 !important;
    }
</style>
""",
    unsafe_allow_html=True,
)
st.markdown(f"<style>{SORTABLE_STYLE}</style>", unsafe_allow_html=True)

st.title("Wrestling Meet Scheduler")
st.caption("Upload roster → Generate → Edit → Download. **No data stored.**")

# ---- STEP 1: DOWNLOAD ROSTER TEMPLATE ----
st.markdown("### Step 1 – Download roster template (CSV)")
st.markdown(
    "Download the example file, add your wrestlers, save it as a `.csv`, "
    "then upload it in Step 2 below."
)

st.download_button(
    label="⬇️ Download roster template CSV",
    data=TEMPLATE_CSV.encode("utf-8"),
    file_name="roster_template.csv",
    mime="text/csv",
    use_container_width=False,
)

st.markdown("---")

# ---- STEP 2: UPLOAD ROSTER ----
st.markdown("### Step 2 – Upload your completed `roster.csv`")

uploaded = st.file_uploader(
    "Upload your roster.csv file",
    type="csv",
    key="roster_csv_uploader"
)

if uploaded and not st.session_state.initialized:
    try:
        df = pd.read_csv(uploaded)

        # Validate first
        validation_errors = validate_roster_df(df)
        if validation_errors:
            for msg in validation_errors:
                st.error(msg)
            st.stop()

        wrestlers = df.to_dict("records")
        for w in wrestlers:
            w["id"] = int(w["id"])
            w["grade"] = int(w["grade"])
            w["level"] = float(w["level"])
            w["weight"] = float(w["weight"])
            w["early"] = (str(w["early_matches"]).strip().upper() == "Y") or (w["early_matches"] in [1, True])
            w["scratch"] = (str(w["scratch"]).strip().upper() == "Y") or (w["scratch"] in [1, True])
            w["match_ids"] = []

        st.session_state.roster = wrestlers
        st.session_state.active = [w for w in wrestlers if not w["scratch"]]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.initialized = True

        st.success(
            f"Roster loaded ({len(wrestlers)} wrestlers, "
            f"{len({w['team'] for w in wrestlers})} teams) and matchups generated!"
        )
    except Exception as e:
        st.error(f"Error loading roster: {e}")

# ----------------------------------------------------------------------
# SIDEBAR SETTINGS
# ----------------------------------------------------------------------
st.sidebar.header("Meet Settings")
st.sidebar.subheader("Search Wrestlers")
search_term = st.sidebar.text_input(
    "Filter by name or team",
    value="",
    placeholder="e.g. Smith or Red",
    key="wrestler_search",
    help="Search affects Mat Previews only (edit disabled while searching)."
)
st.sidebar.caption(
    "**Note:** Suggested Matches are based on all wrestlers; Mat Previews show only matches involving filtered wrestlers."
)

changed = False
st.sidebar.subheader("Match & Scheduling Rules")

# Top row: numbers in two columns
c1, c2 = st.sidebar.columns(2)
with c1:
    new_min = st.sidebar.number_input("Min Matches", 1, 10, CONFIG["MIN_MATCHES"], key="min_matches")
    new_max = st.sidebar.number_input("Max Matches", 1, 10, CONFIG["MAX_MATCHES"], key="max_matches")
    new_mats = st.sidebar.number_input("Number of Mats", 1, 10, CONFIG["NUM_MATS"], key="num_mats")
with c2:
    new_level_diff = st.sidebar.number_input("Max Level Diff", 0, 5, CONFIG["MAX_LEVEL_DIFF"], key="max_level_diff")
    new_min_weight = st.sidebar.number_input(
        "Min Wt Diff (lbs)", 0.0, 50.0, CONFIG["MIN_WEIGHT_DIFF"], 0.5,
        key="min_weight_diff"
    )

# Slider on its own row below the other settings
new_weight_factor = st.sidebar.slider(
    "Weight Diff % Factor",
    0.0, 0.5,
    CONFIG["WEIGHT_DIFF_FACTOR"],
    0.01,
    format="%.2f",
    key="weight_factor"
)

# Min rest gap
new_rest_gap = st.sidebar.number_input(
    "Min Rest Gap (matches)",
    1, 10,
    CONFIG.get("REST_GAP", 4),
    key="rest_gap"
)

if new_min > new_max:
    st.sidebar.error("Min Matches cannot exceed Max Matches!")
    new_min = new_max

st.sidebar.markdown("---")
st.sidebar.subheader("Team Colors")

circle_color_names = list(COLOR_ICON.keys())

# Rebuild TEAMS from the roster every run (if roster exists)
if st.session_state.get("roster"):
    roster_teams = sorted({
        str(w["team"]).strip()
        for w in st.session_state.roster
        if str(w["team"]).strip()
    })

    prev_teams = CONFIG.get("TEAMS", [])
    prev_color_by_name = {
        t["name"]: t["color"] for t in prev_teams if t.get("name")
    }

    TEAMS = []
    used_colors = set()

    for team_name in roster_teams:
        color = prev_color_by_name.get(team_name)
        if color not in circle_color_names:
            # pick first unused color, then wrap
            for c in circle_color_names:
                if c not in used_colors:
                    color = c
                    break
            if color is None:
                color = circle_color_names[0]
        used_colors.add(color)
        TEAMS.append({"name": team_name, "color": color})

    CONFIG["TEAMS"] = TEAMS
    st.session_state.CONFIG = CONFIG
else:
    TEAMS = CONFIG.get("TEAMS", [])

if TEAMS:
    for i, team in enumerate(TEAMS):
        st.sidebar.markdown(f"**{team['name']}**")
        try:
            default_idx = circle_color_names.index(team["color"])
        except ValueError:
            default_idx = 0

        new_color = st.sidebar.selectbox(
            "Color",
            circle_color_names,
            index=default_idx,
            format_func=lambda x: x.capitalize(),
            key=f"color_{i}",
            label_visibility="collapsed"
        )

        if new_color != team["color"]:
            team["color"] = new_color
            changed = True
            st.session_state.sortable_version += 1
else:
    st.sidebar.caption("Upload a roster to configure team colors.")

if (
    new_min != CONFIG["MIN_MATCHES"] or new_max != CONFIG["MAX_MATCHES"] or
    new_mats != CONFIG["NUM_MATS"] or new_level_diff != CONFIG["MAX_LEVEL_DIFF"] or
    new_weight_factor != CONFIG["WEIGHT_DIFF_FACTOR"] or new_min_weight != CONFIG["MIN_WEIGHT_DIFF"] or
    new_rest_gap != CONFIG.get("REST_GAP", 4)
):
    CONFIG.update({
        "MIN_MATCHES": new_min,
        "MAX_MATCHES": new_max,
        "NUM_MATS": new_mats,
        "MAX_LEVEL_DIFF": new_level_diff,
        "WEIGHT_DIFF_FACTOR": new_weight_factor,
        "MIN_WEIGHT_DIFF": new_min_weight,
        "REST_GAP": new_rest_gap,
    })
    changed = True

st.sidebar.markdown("---")
if st.sidebar.button("Reset Settings", type="secondary"):
    # Reset CONFIG to BASE_CONFIG for this browser session only
    st.session_state.CONFIG = copy.deepcopy(BASE_CONFIG)
    CONFIG = st.session_state.CONFIG
    st.sidebar.success("Reset settings for this session. Refresh to apply.")
    st.rerun()

if changed:
    st.sidebar.success("Settings updated for this session. Refresh to apply.")
    st.rerun()

TEAM_COLORS = {t["name"]: COLOR_MAP.get(t["color"], "#000000") for t in TEAMS if t["name"]}
TEAM_COLOR_NAMES = {t["name"]: t["color"] for t in TEAMS if t["name"]}

# ----------------------------------------------------------------------
# MAIN APP – TABS
# ----------------------------------------------------------------------
if st.session_state.initialized:
    raw_active = st.session_state.active
    roster = st.session_state.roster

    tab_build, tab_summary, tab_help = st.tabs(["Match Builder", "Meet Summary", "Help"])

    # ==========================================================
    # TAB 1 – MATCH BUILDER
    # ==========================================================
    with tab_build:
        # Map each roster team to a color name (for icons + HTML)
        roster_teams = sorted({w["team"] for w in roster})
        palette = list(COLOR_ICON.keys())
        team_color_for_roster = {}

        # First, use explicit config team colors (TEAM_COLOR_NAMES)
        for team_name in roster_teams:
            cfg_color = TEAM_COLOR_NAMES.get(team_name)
            if cfg_color:
                team_color_for_roster[team_name] = cfg_color

        used_colors = set(team_color_for_roster.values())
        idx = 0
        for team_name in roster_teams:
            if team_name in team_color_for_roster:
                continue
            while palette[idx % len(palette)] in used_colors and len(used_colors) < len(palette):
                idx += 1
            color_name = palette[idx % len(palette)]
            team_color_for_roster[team_name] = color_name
            used_colors.add(color_name)
            idx += 1

        # ----- Pre-Meet Scratches -----
        st.subheader("Pre-Meet Scratches")

        if roster:
            default_scratched_ids = [w["id"] for w in roster if w.get("scratch")]

            selected_scratched = st.multiselect(
                "Mark wrestlers as scratched (removed from meet scheduling):",
                options=[w["id"] for w in roster],
                default=default_scratched_ids,
                format_func=lambda wid: next(
                    f"{w['name']} ({w['team']})"
                    for w in roster if w["id"] == wid
                ),
                key="scratch_multiselect"
            )

            if st.button("Apply scratches & regenerate schedule"):
                for w in roster:
                    w["scratch"] = (w["id"] in selected_scratched)
                    w["match_ids"] = []

                st.session_state.roster = roster
                st.session_state.active = [w for w in roster if not w["scratch"]]

                st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
                st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
                st.session_state.mat_order = {}
                st.session_state.mat_order_history = []  # reset drag history
                st.session_state.undo_stack = []
                st.session_state.excel_bytes = None
                st.session_state.pdf_bytes = None

                st.session_state.sortable_version += 1

                st.success("Scratches applied and schedule regenerated.")
                st.rerun()

        # ---- Filtered wrestlers by search ----
        if search_term.strip():
            term = search_term.strip().lower()
            filtered_active = [
                w for w in raw_active
                if term in w["name"].lower() or term in w["team"].lower()
            ]
            st.info(
                f"Showing **{len(filtered_active)}** wrestler(s) matching “{search_term}” "
                f"(out of {len(raw_active)} active)."
            )
        else:
            filtered_active = raw_active
            st.info(f"Showing **all {len(filtered_active)}** active wrestlers.")

        filtered_ids = {w["id"] for w in filtered_active}

        # ----- Manual Match Creator -----
        st.subheader("Manual Match Creator")

        # Show any stored manual-match warning from last run
        manual_warning = st.session_state.get("manual_match_warning")
        if manual_warning:
            st.warning(manual_warning)
            st.session_state.manual_match_warning = ""

        active_ids = [w["id"] for w in raw_active]

        if len(active_ids) < 2:
            st.caption("Not enough active wrestlers to create a manual match.")
        else:
            col_m1, col_m2, col_m_btn = st.columns([3, 3, 1])

            with col_m1:
                manual_w1_id = st.selectbox(
                    "Wrestler 1",
                    options=active_ids,
                    format_func=lambda wid: next(
                        f"{w['name']} ({w['team']}) – Lvl {w['level']:.1f}, {w['weight']:.0f} lbs"
                        for w in raw_active if w["id"] == wid
                    ),
                    key="manual_match_w1",
                )

            with col_m2:
                manual_w2_id = st.selectbox(
                    "Wrestler 2",
                    options=[wid for wid in active_ids if wid != manual_w1_id],
                    format_func=lambda wid: next(
                        f"{w['name']} ({w['team']}) – Lvl {w['level']:.1f}, {w['weight']:.0f} lbs"
                        for w in raw_active if w["id"] == wid
                    ),
                    key="manual_match_w2",
                )

            with col_m_btn:
                create_manual = st.button(
                    "Create Match",
                    help="Force a match between these two wrestlers, even if it wasn’t auto-generated.",
                    key="manual_match_create_btn",
                )

            if create_manual:
                if manual_w1_id == manual_w2_id:
                    st.warning("Please choose two different wrestlers.")
                else:
                    w1 = next(w for w in raw_active if w["id"] == manual_w1_id)
                    w2 = next(w for w in raw_active if w["id"] == manual_w2_id)

                    # Check if they already have a match together (ignore Manually Removed bouts)
                    already_linked = any(
                        (
                            (b["w1_id"] == w1["id"] and b["w2_id"] == w2["id"]) or
                            (b["w1_id"] == w2["id"] and b["w2_id"] == w1["id"])
                        )
                        for b in st.session_state.bout_list
                        if b.get("manual") != "Manually Removed"
                    )

                    if already_linked:
                        msg = (
                            f"{w1['name']} ({w1['team']}) and "
                            f"{w2['name']} ({w2['team']}) already have a match together. "
                            "A new match will not be created."
                        )
                        st.session_state.manual_match_warning = msg
                        st.warning(msg)
                    else:
                        # Soft warnings for coaches – but still allow the match
                        warning_msgs = []
                        if w1["team"] == w2["team"]:
                            warning_msgs.append("Same team matchup.")
                        if abs(w1["level"] - w2["level"]) > CONFIG["MAX_LEVEL_DIFF"]:
                            warning_msgs.append("Large level difference.")
                        if abs(w1["weight"] - w2["weight"]) > max_weight_diff(w1["weight"]):
                            warning_msgs.append("Large weight difference.")

                        if warning_msgs:
                            st.info(
                                "Note: " + " ".join(
                                    f"• {msg}" for msg in warning_msgs
                                ) + " (match will still be created)."
                            )

                        # Link in match_ids if not already present
                        if w2["id"] not in w1["match_ids"]:
                            w1["match_ids"].append(w2["id"])
                        if w1["id"] not in w2["match_ids"]:
                            w2["match_ids"].append(w1["id"])

                        new_bout_num = (max([b["bout_num"] for b in st.session_state.bout_list]) + 1) \
                            if st.session_state.bout_list else 1

                        new_score = matchup_score(w1, w2)
                        new_bout = {
                            "bout_num": new_bout_num,
                            "w1_id": w1["id"], "w1_name": w1["name"], "w1_team": w1["team"],
                            "w1_level": w1["level"], "w1_weight": w1["weight"],
                            "w1_grade": w1["grade"], "w1_early": w1["early"],
                            "w2_id": w2["id"], "w2_name": w2["name"], "w2_team": w2["team"],
                            "w2_level": w2["level"], "w2_weight": w2["weight"],
                            "w2_grade": w2["grade"], "w2_early": w2["early"],
                            "score": new_score,
                            "avg_weight": (w1["weight"] + w2["weight"]) / 2,
                            "is_early": w1["early"] or w2["early"],
                            "manual": "Coach Manual Match",
                        }

                        st.session_state.bout_list.append(new_bout)

                        # Keep bouts sorted by avg_weight so base scheduler behaves
                        st.session_state.bout_list.sort(key=lambda x: x["avg_weight"])

                        # Clear manual mat order so the new match gets placed, then coach can drag it
                        st.session_state.mat_order = {}
                        st.session_state.mat_order_history = []

                        # Rebuild suggestions based on new counts
                        st.session_state.suggestions = build_suggestions(raw_active, st.session_state.bout_list)

                        # Invalidate exports
                        st.session_state.excel_bytes = None
                        st.session_state.pdf_bytes = None

                        # Refresh drag widgets
                        st.session_state.sortable_version += 1

                        st.success(
                            f"Manual match created: {w1['name']} ({w1['team']}) vs {w2['name']} ({w2['team']}). "
                            "You can now drag it to the desired mat and slot."
                        )
                        st.rerun()

        # ----- Suggested Matches -----
        st.subheader("Suggested Matches")

        all_suggestions = build_suggestions(raw_active, st.session_state.bout_list)
        current_suggestions = [s for s in all_suggestions if s["_w_id"] in filtered_ids]

        under_count = len([
            w for w in filtered_active
            if len(w["match_ids"]) < CONFIG["MIN_MATCHES"]
        ])
        st.caption(
            f"**{under_count}** of **{len(filtered_active)}** filtered wrestler(s) need more matches."
        )

        if current_suggestions:
            sugg_data = []
            for i, s in enumerate(current_suggestions):
                w = next(w for w in filtered_active if w["id"] == s["_w_id"])
                o = next(w for w in raw_active if w["id"] == s["_o_id"])
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
                to_add = [
                    current_suggestions[sugg_full_df.iloc[row.name]["idx"]]
                    for _, row in edited.iterrows() if row["Add"]
                ]
                for s in to_add:
                    w = next(w for w in raw_active if w["id"] == s["_w_id"])
                    o = next(w for w in raw_active if w["id"] == s["_o_id"])
                    if o["id"] not in w["match_ids"]:
                        w["match_ids"].append(o["id"])
                    if w["id"] not in o["match_ids"]:
                        o["match_ids"].append(w["id"])
                    new_bout = {
                        "bout_num": len(st.session_state.bout_list) + 1,
                        "w1_id": w["id"], "w1_name": w["name"], "w1_team": w["team"],
                        "w1_level": w["level"], "w1_weight": w["weight"],
                        "w1_grade": w["grade"], "w1_early": w["early"],
                        "w2_id": o["id"], "w2_name": o["name"], "w2_team": o["team"],
                        "w2_level": o["level"], "w2_weight": o["weight"],
                        "w2_grade": o["grade"], "w2_early": o["early"],
                        "score": s["score"],
                        "avg_weight": (w["weight"] + o["weight"]) / 2,
                        "is_early": w["early"] or o["early"],
                        "manual": "Manually Added"
                    }
                    st.session_state.bout_list.append(new_bout)

                st.session_state.bout_list.sort(key=lambda x: x["avg_weight"])
                st.session_state.mat_order = {}
                st.session_state.mat_order_history = []
                st.session_state.suggestions = build_suggestions(raw_active, st.session_state.bout_list)
                st.success("Matches added! Early matches placed at the top of their mat.")
                st.session_state.excel_bytes = None
                st.session_state.pdf_bytes = None

                st.session_state.sortable_version += 1
                st.rerun()
        else:
            st.info("All filtered wrestlers meet the minimum matches. No suggestions needed.")

        # ----- Global schedule & rest conflicts -----
        full_schedule = apply_mat_order_to_global_schedule() if st.session_state.bout_list else []
        rest_gap = CONFIG.get("REST_GAP", 4)
        conflicts_all = compute_rest_conflicts(full_schedule, rest_gap) if full_schedule else []

        if search_term.strip():
            visible_conflicts = [c for c in conflicts_all if c["wrestler_id"] in filtered_ids]
        else:
            visible_conflicts = conflicts_all

        st.subheader("Mat Previews")

        if visible_conflicts:
            st.warning(
                f"Rest conflicts detected: **{len(visible_conflicts)}** (requires at least "
                f"**{rest_gap}** matches between bouts for the same wrestler)."
            )
        else:
            st.caption(f"No rest conflicts found (min gap: {rest_gap} matches).")

        if not full_schedule:
            st.caption("No bouts scheduled yet.")
        else:
            def bout_in_filtered(b):
                return (
                    b["manual"] != "Manually Removed" and
                    (b["w1_id"] in filtered_ids or b["w2_id"] in filtered_ids)
                )

            # ---------- SEARCH MODE (read-only, HTML table) ----------
            if search_term.strip():
                for mat in range(1, CONFIG["NUM_MATS"] + 1):
                    mat_entries = [
                        e for e in full_schedule
                        if e["mat"] == mat and bout_in_filtered(
                            next(
                                b for b in st.session_state.bout_list
                                if b["bout_num"] == e["bout_num"]
                            )
                        )
                    ]
                    mat_label = f"Mat {mat} ({len(mat_entries)} matches)"
                    with st.expander(mat_label, expanded=True):
                        if not mat_entries:
                            st.caption("No matches for the current filter on this mat.")
                            continue

                        # HTML table with colored dots
                        table_rows = []
                        for e in mat_entries:
                            b = next(
                                x for x in st.session_state.bout_list
                                if x["bout_num"] == e["bout_num"]
                            )
                            early_flag = "⏰🔥 EARLY 🔥⏰" if b["is_early"] else ""
                            color_name1 = team_color_for_roster.get(b["w1_team"])
                            color_name2 = team_color_for_roster.get(b["w2_team"])
                            dot1 = color_dot_hex(COLOR_MAP.get(color_name1, "#000000")) if color_name1 else ""
                            dot2 = color_dot_hex(COLOR_MAP.get(color_name2, "#000000")) if color_name2 else ""

                            table_rows.append(
                                f"<tr>"
                                f"<td>{e['mat_bout_num']}</td>"
                                f"<td>{b['bout_num']}</td>"
                                f"<td>{early_flag}</td>"
                                f"<td>{dot1}{b['w1_name']} ({b['w1_team']})</td>"
                                f"<td>{dot2}{b['w2_name']} ({b['w2_team']})</td>"
                                f"<td>{b['w1_level']:.1f}/{b['w2_level']:.1f}</td>"
                                f"<td>{b['w1_weight']:.0f}/{b['w2_weight']:.0f}</td>"
                                f"<td>{b['score']:.1f}</td>"
                                f"</tr>"
                            )

                        table_html = (
                            "<table style='width:100%;border-collapse:collapse;font-size:0.85rem;'>"
                            "<thead>"
                            "<tr style='background:#f0f0f0;'>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Slot</th>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Bout</th>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Early</th>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Wrestler 1</th>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Wrestler 2</th>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Lvls</th>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Wts</th>"
                            "<th style='border:1px solid #ddd;padding:4px;'>Score</th>"
                            "</tr>"
                            "</thead>"
                            "<tbody>"
                            + "".join(table_rows) +
                            "</tbody>"
                            "</table>"
                        )

                        st.markdown(table_html, unsafe_allow_html=True)

                        # Per-mat rest warnings for visible wrestlers
                        mat_conflicts = [
                            c for c in visible_conflicts if c["mat"] == mat
                        ]
                        if mat_conflicts:
                            st.markdown("**Rest warnings on this mat (filtered wrestlers):**")
                            for c in mat_conflicts:
                                st.markdown(
                                    f"- {c['wrestler']} ({c['team']}): "
                                    f"Bout {c['bout1']} (Slot {c['slot1']}) → "
                                    f"Bout {c['bout2']} (Slot {c['slot2']}) "
                                    f"(gap {c['gap']} < required {rest_gap})"
                                )

                st.caption("Reordering and removal are disabled while search is active. Clear the search box to edit mats.")

            # ---------- EDIT MODE (drag + per-mat remove) ----------
            else:
                for mat in range(1, CONFIG["NUM_MATS"] + 1):
                    mat_entries = [e for e in full_schedule if e["mat"] == mat]
                    mat_label = f"Mat {mat} ({len(mat_entries)} matches)"
                    with st.expander(mat_label, expanded=True):
                        if not mat_entries:
                            st.caption("No bouts on this mat.")
                            continue

                        bout_nums_in_mat = [e["bout_num"] for e in mat_entries]
                        existing_order = st.session_state.mat_order.get(mat)
                        if not existing_order:
                            st.session_state.mat_order[mat] = bout_nums_in_mat.copy()
                        else:
                            cleaned = [bn for bn in existing_order if bn in bout_nums_in_mat]
                            for bn in bout_nums_in_mat:
                                if bn not in cleaned:
                                    cleaned.append(bn)
                            st.session_state.mat_order[mat] = cleaned

                        prev_order = st.session_state.mat_order[mat].copy()

                        # Legend for teams on this mat (HTML dots)
                        teams_on_mat = set()
                        for e in mat_entries:
                            b_for_legend = next(
                                x for x in st.session_state.bout_list
                                if x["bout_num"] == e["bout_num"]
                            )
                            teams_on_mat.add(b_for_legend["w1_team"])
                            teams_on_mat.add(b_for_legend["w2_team"])
                        legend_bits = []
                        for t in sorted(teams_on_mat):
                            hex_color = TEAM_COLORS.get(t, "#000000")
                            dot = color_dot_hex(hex_color)
                            legend_bits.append(f"{dot}{t}")
                        if legend_bits:
                            legend_html = " ".join(legend_bits)
                            st.markdown(
                                f"<div style='margin-bottom:4px;font-size:0.8rem;'>Teams on this mat: {legend_html}</div>",
                                unsafe_allow_html=True,
                            )

                        # Build drag labels (plain text, circle emojis)
                        row_labels = []
                        label_to_bout = {}
                        for bn in st.session_state.mat_order[mat]:
                            if bn not in bout_nums_in_mat:
                                continue
                            b = next(x for x in st.session_state.bout_list if x["bout_num"] == bn)

                            early_prefix = "🔥🔥⏰ EARLY MATCH ⏰🔥🔥  |  " if b["is_early"] else ""

                            color_name1 = team_color_for_roster.get(b["w1_team"])
                            color_name2 = team_color_for_roster.get(b["w2_team"])
                            icon1 = COLOR_ICON.get(color_name1, "●")
                            icon2 = COLOR_ICON.get(color_name2, "●")

                            label = (
                                f"{early_prefix}"
                                f"Bout {bn:>3} | "
                                f"{icon1} {b['w1_name']} ({b['w1_team']})  vs  "
                                f"{icon2} {b['w2_name']} ({b['w2_team']})"
                                f"  |  Lvl {b['w1_level']:.1f}/{b['w2_level']:.1f}"
                                f"  |  Wt {b['w1_weight']:.0f}/{b['w2_weight']:.0f}"
                                f"  |  Score {b['score']:.1f}"
                            )
                            row_labels.append(label)
                            label_to_bout[label] = bn

                        sorted_labels = sort_items(
                            row_labels,
                            direction="vertical",
                            key=f"mat_{mat}_sortable_v{st.session_state.sortable_version}",
                            custom_style=SORTABLE_STYLE,
                        )

                        new_order = []
                        for label in sorted_labels:
                            bn = label_to_bout.get(label)
                            if bn is not None and bn in bout_nums_in_mat and bn not in new_order:
                                new_order.append(bn)

                        if new_order != prev_order:
                            # Save snapshot of current mat_order for drag undo
                            snapshot = {
                                m: order.copy() for m, order in st.session_state.mat_order.items()
                            }
                            st.session_state.mat_order_history.append(snapshot)

                            st.session_state.mat_order[mat] = new_order
                            st.session_state.sortable_version += 1
                            st.rerun()
                        else:
                            st.session_state.mat_order[mat] = new_order

                        st.caption("Drag rows above – top row is Slot 1, next is Slot 2, etc. for this mat.")

                        # Per-mat remove
                        bout_label_map = {}
                        for idx2, bn in enumerate(st.session_state.mat_order[mat], start=1):
                            if bn not in bout_nums_in_mat:
                                continue
                            b = next(x for x in st.session_state.bout_list if x["bout_num"] == bn)
                            bout_label_map[bn] = (
                                f"Slot {idx2} – Bout {bn}: "
                                f"{b['w1_name']} ({b['w1_team']}) vs {b['w2_name']} ({b['w2_team']})"
                            )

                        valid_bouts = list(bout_label_map.keys())
                        if not valid_bouts:
                            st.caption("No bouts left on this mat.")
                        else:
                            selected_bout = st.selectbox(
                                "Remove bout on this mat:",
                                options=valid_bouts,
                                format_func=lambda v: bout_label_map[v],
                                key=f"remove_select_mat_{mat}"
                            )
                            if st.button(
                                "Remove selected bout",
                                key=f"remove_button_mat_{mat}",
                                help="Removes the selected bout from this meet (Undo available at bottom)."
                            ):
                                remove_bout(selected_bout)

                        # Per-mat rest warnings (all wrestlers)
                        mat_conflicts = [
                            c for c in visible_conflicts if c["mat"] == mat
                        ]
                        if mat_conflicts:
                            st.markdown("**Rest warnings on this mat:**")
                            for c in mat_conflicts:
                                st.markdown(
                                    f"- {c['wrestler']} ({c['team']}): "
                                    f"Bout {c['bout1']} (Slot {c['slot1']}) → "
                                    f"Bout {c['bout2']} (Slot {c['slot2']}) "
                                    f"(gap {c['gap']} < required {rest_gap})"
                                )

        # ----- Undo -----
        st.markdown("---")
        col_undo_remove, col_undo_drag = st.columns(2)
        with col_undo_remove:
            if st.session_state.undo_stack:
                if st.button("Undo Last Remove", help="Restore last removed match"):
                    undo_last()
            else:
                st.caption("No removals yet to undo.")
        with col_undo_drag:
            if st.session_state.mat_order_history:
                if st.button("Undo Last Drag / Reorder", help="Undo last drag change to mat order"):
                    undo_last_drag()
            else:
                st.caption("No drag changes yet to undo.")

        # ---- GENERATE MEET ----
        if st.button("Generate Matches", type="primary", help="Generate Excel + PDF for download"):
            with st.spinner("Generating files..."):
                try:
                    final_sched = apply_mat_order_to_global_schedule()
                    st.session_state.mat_schedules = final_sched

                    # Excel
                    out = io.BytesIO()
                    with pd.ExcelWriter(out, engine="openpyxl") as writer:
                        roster_df = pd.DataFrame(st.session_state.active)
                        roster_df.to_excel(writer, sheet_name='Roster', index=False)

                        matchups_df = pd.DataFrame(st.session_state.bout_list)
                        matchups_df.to_excel(writer, sheet_name='Matchups', index=False)

                        suggestions_df = pd.DataFrame(st.session_state.suggestions)
                        suggestions_df.to_excel(writer, sheet_name='Remaining Suggestions', index=False)

                        for m in range(1, CONFIG["NUM_MATS"] + 1):
                            data = [e for e in final_sched if e["mat"] == m]
                            if not data:
                                pd.DataFrame(
                                    [["", "", ""]],
                                    columns=["#", "Wrestler 1 (Team)", "Wrestler 2 (Team)"]
                                ).to_excel(writer, f"Mat {m}", index=False)
                                continue
                            df = pd.DataFrame(data)[["mat_bout_num", "w1", "w2"]]
                            df.columns = ["#", "Wrestler 1 (Team)", "Wrestler 2 (Team)"]
                            df.to_excel(writer, f"Mat {m}", index=False)
                            if _EXCEL_AVAILABLE:
                                ws = writer.book[f"Mat {m}"]
                                fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
                                for i, _ in df.iterrows():
                                    if next(
                                        b for b in st.session_state.bout_list
                                        if b["bout_num"] == data[i]["bout_num"]
                                    )["is_early"]:
                                        for c in range(1, 3 + 1):
                                            ws.cell(row=i + 2, column=c).fill = fill

                    st.session_state.excel_bytes = out.getvalue()

                    # PDF
                    buf = io.BytesIO()
                    doc = SimpleDocTemplate(buf, pagesize=letter)
                    elements = []
                    styles = getSampleStyleSheet()
                    for m in range(1, CONFIG["NUM_MATS"] + 1):
                        data = [e for e in final_sched if e["mat"] == m]
                        if not data:
                            elements.append(Paragraph(f"Mat {m} - No matches", styles["Title"]))
                            elements.append(PageBreak())
                            continue
                        table = [["#", "Wrestler 1", "Wrestler 2"]]
                        for e in data:
                            b = next(
                                x for x in st.session_state.bout_list
                                if x["bout_num"] == e["bout_num"]
                            )
                            table.append([
                                e["mat_bout_num"],
                                Paragraph(
                                    f'<font color="{TEAM_COLORS.get(b["w1_team"], "#000")}">'
                                    f'<b>{b["w1_name"]}</b></font> ({b["w1_team"]})',
                                    styles["Normal"]
                                ),
                                Paragraph(
                                    f'<font color="{TEAM_COLORS.get(b["w2_team"], "#000")}">'
                                    f'<b>{b["w2_name"]}</b></font> ({b["w2_team"]})',
                                    styles["Normal"]
                                )
                            ])
                        t = Table(table, colWidths=[0.5 * inch, 3 * inch, 3 * inch])
                        s = TableStyle([
                            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.black),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.lightgrey),
                            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
                        ])
                        for r, _ in enumerate(table[1:], 1):
                            if next(
                                b for b in st.session_state.bout_list
                                if b["bout_num"] == data[r - 1]["bout_num"]
                            )["is_early"]:
                                s.add("BACKGROUND", (0, r), (-1, r), HexColor("#FFFF99"))
                        t.setStyle(s)
                        elements += [Paragraph(f"Mat {m}", styles["Title"]), Spacer(1, 12), t]
                        if m < CONFIG["NUM_MATS"]:
                            elements.append(PageBreak())
                    doc.build(elements)
                    st.session_state.pdf_bytes = buf.getvalue()
                    st.toast("Files generated!")
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    st.toast("Error – check console.")

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

    # ==========================================================
    # TAB 2 – MEET SUMMARY
    # ==========================================================
    with tab_summary:
        st.subheader("Meet Summary")

        full_schedule = apply_mat_order_to_global_schedule() if st.session_state.bout_list else []
        rest_gap = CONFIG.get("REST_GAP", 4)
        conflicts_all = compute_rest_conflicts(full_schedule, rest_gap) if full_schedule else []

        num_wrestlers = len(st.session_state.active)
        total_bouts = len([b for b in st.session_state.bout_list if b["manual"] != "Manually Removed"])
        avg_matches = (
            total_bouts * 2 / num_wrestlers if num_wrestlers > 0 else 0.0
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("Active Wrestlers", num_wrestlers)
        c2.metric("Total Bouts", total_bouts)
        c3.metric("Avg Matches / Wrestler", f"{avg_matches:.2f}")

        st.markdown("---")

        st.markdown("#### Mats Overview")
        if not full_schedule:
            st.caption("No schedule yet. Go to **Match Builder** to create matchups.")
        else:
            mat_rows = []
            for m in range(1, CONFIG["NUM_MATS"] + 1):
                mat_entries = [e for e in full_schedule if e["mat"] == m]
                count = len(mat_entries)
                early_count = sum(
                    1 for e in mat_entries
                    if next(b for b in st.session_state.bout_list if b["bout_num"] == e["bout_num"])["is_early"]
                )
                mat_rows.append({
                    "Mat": m,
                    "# Bouts": count,
                    "Early Matches": early_count
                })
            st.dataframe(pd.DataFrame(mat_rows), use_container_width=True)

        st.markdown("---")

        st.markdown("#### Rest Gap Warnings")
        if not conflicts_all:
            st.caption(f"No rest conflicts detected (min gap {rest_gap} matches).")
        else:
            conflicts_df = pd.DataFrame(conflicts_all)
            conflicts_df = conflicts_df[
                ["wrestler", "team", "mat", "bout1", "slot1", "bout2", "slot2", "gap"]
            ].rename(columns={
                "wrestler": "Wrestler",
                "team": "Team",
                "mat": "Mat",
                "bout1": "Bout A",
                "slot1": "Slot A",
                "bout2": "Bout B",
                "slot2": "Slot B",
                "gap": "Gap"
            })
            st.warning(
                f"There are **{len(conflicts_df)}** potential rest issues "
                f"(gap < {rest_gap} matches on the same mat)."
            )
            st.dataframe(conflicts_df, use_container_width=True)

    # ==========================================================
    # TAB 3 – HELP
    # ==========================================================
    with tab_help:
        st.subheader("How to Use This Tool")

        st.markdown("##### 1. Build Your Roster CSV")
        st.markdown(
            """
Your CSV **must** include these columns:

| Column          | Description                                          | Example      |
|-----------------|------------------------------------------------------|--------------|
| `id`            | Unique ID per wrestler (number)                      | `1`          |
| `name`          | Wrestler name                                        | `John Doe`   |
| `team`          | Team name (used for colors & legends)                | `Stillwater` |
| `grade`         | Numeric grade (5–8, etc)                             | `7`          |
| `level`         | Level / experience (float, e.g. 1.0, 1.5, 2.0)       | `1.5`        |
| `weight`        | Weight in pounds (numeric)                           | `75`         |
| `early_matches` | `Y`/`N` or `1`/`0` – needs early match?             | `Y`          |
| `scratch`       | `Y`/`N` or `1`/`0` – remove from meet?              | `N`          |

Download the template in **Step 1**, fill it out, and upload in **Step 2**.
            """
        )

        st.markdown("##### 2. Tune Meet Settings (Sidebar)")
        st.markdown(
            """
- **Min / Max Matches** – target range for bouts per wrestler.
- **Number of Mats** – how many mats are running at once.
- **Max Level Diff / Weight Diff** – how strict the matching is.
- **Min Rest Gap** – how many bouts must be between two matches for the same wrestler.
- **Team Colors** – after you upload a roster, each team appears here so you can assign colors used in:
  - Circle emojis in the drag rows
  - PDF/Excel exports
  - Legends in the mat previews
            """
        )

        st.markdown("##### 3. Build & Adjust the Meet")
        st.markdown(
            """
- Use **Pre-Meet Scratches** to quickly remove wrestlers from the meet.
- Use **Manual Match Creator** when coaches want specific bouts.
- Use **Suggested Matches** to fill gaps for wrestlers under the minimum.
- In **Mat Previews**:
  - Drag to reorder bouts on each mat.
  - Use the per-mat dropdown to remove a bout.
  - Watch the *rest warnings* to avoid back-to-back matches.
            """
        )

        st.markdown("##### 4. Exports")
        st.markdown(
            """
- Click **Generate Matches** to build:
  - An **Excel** file with roster, all matchups, remaining suggestions, and mat sheets.
  - A **PDF** with mat-by-mat bout sheets, including early-match highlighting and team colors.
- Then use the **Download Excel / Download PDF** buttons at the bottom of the *Match Builder* tab.
            """
        )

else:
    st.info("Upload a roster CSV in **Step 2** to unlock Match Builder, Meet Summary, and Help tabs.")

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")
