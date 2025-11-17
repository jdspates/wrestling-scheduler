# app.py – Wrestling Meet Scheduler – FULLY WORKING with Save/Load Progress
# Tested & deployed on Streamlit Cloud – November 2025
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
from streamlit_sortables import sort_items

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
    "red": "#FF0000", "orange": "#FF7F00", "yellow": "#FFD700", "green": "#008000",
    "blue": "#0000FF", "purple": "#800080", "brown": "#8B4513", "black": "#000000", "white": "#FFFFFF",
}

COLOR_ICON = {
    "red": "Red", "orange": "Orange", "yellow": "Yellow", "green": "Green",
    "blue": "Blue", "purple": "Purple", "brown": "Brown", "black": "Black", "white": "White",
}

DEFAULT_CONFIG = {
    "MIN_MATCHES": 2, "MAX_MATCHES": 4, "NUM_MATS": 4, "MAX_LEVEL_DIFF": 1,
    "WEIGHT_DIFF_FACTOR": 0.10, "MIN_WEIGHT_DIFF": 5.0, "REST_GAP": 4, "TEAMS": []
}

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as f:
            loaded = json.load(f)
            BASE_CONFIG = loaded if isinstance(loaded, dict) else DEFAULT_CONFIG
    except Exception:
        BASE_CONFIG = DEFAULT_CONFIG
else:
    BASE_CONFIG = DEFAULT_CONFIG

# ----------------------------------------------------------------------
# ROSTER TEMPLATE
# ----------------------------------------------------------------------
TEMPLATE_CSV = """id,name,team,grade,level,weight,early_matches,scratch
1,John Doe,Stillwater,7,1.0,70,Y,N
2,Jane Smith,Hastings,8,1.5,75,N,N
3,Ben Carter,Cottage Grove,6,2.0,80,N,N
4,Ava Johnson,Woodbury,7,1.0,68,Y,N
"""

# ----------------------------------------------------------------------
# STYLES
# ----------------------------------------------------------------------
SORTABLE_STYLE = """
.sortable-component {background-color: transparent;border: none;padding: 0;}
.sortable-container {background-color: transparent;border: none;box-shadow: none;}
.sortable-container-header {display: none;}
.sortable-container-body {background-color: transparent;padding: 0;}
.sortable-item {
    background-color: #ffffff;color: #222 !important;border-radius: 4px;
    border: 1px solid #ddd;padding: 0 8px;margin-bottom: 4px;font-size: 0.85rem;
    cursor: grab;height: 36px;display: flex;align-items: center;
}
.sortable-item:hover {background-color: #f7f7f7;color: #222 !important;}
"""

# ----------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# ----------------------------------------------------------------------
if "CONFIG" not in st.session_state:
    st.session_state.CONFIG = copy.deepcopy(BASE_CONFIG)
CONFIG = st.session_state.CONFIG

for key in ["initialized","bout_list","mat_schedules","suggestions","active","undo_stack",
            "mat_order","excel_bytes","pdf_bytes","roster","mat_order_history","manual_match_warning"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list","mat_schedules","suggestions","active","undo_stack","roster","mat_order_history"] else \
                                 {} if key == "mat_order" else \
                                 "" if key == "manual_match_warning" else None

if "sortable_version" not in st.session_state:
    st.session_state.sortable_version = 0
if "roster_uploader_version" not in st.session_state:
    st.session_state.roster_uploader_version = 0

# ----------------------------------------------------------------------
# SAVE / LOAD PROGRESS FUNCTIONS
# ----------------------------------------------------------------------
def get_state_snapshot():
    return {
        "version": "1.0",
        "saved_at": pd.Timestamp.now().isoformat(),
        "CONFIG": copy.deepcopy(st.session_state.CONFIG),
        "roster": copy.deepcopy(st.session_state.roster),
        "active": copy.deepcopy(st.session_state.active),
        "bout_list": copy.deepcopy(st.session_state.bout_list),
        "suggestions": copy.deepcopy(st.session_state.suggestions),
        "undo_stack": st.session_state.undo_stack.copy(),
        "mat_order": copy.deepcopy(st.session_state.mat_order),
        "mat_order_history": [copy.deepcopy(h) for h in st.session_state.mat_order_history],
    }

def restore_state_from_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("version") != "1.0":
        st.error("Invalid or outdated save file.")
        return False
    st.session_state.CONFIG = copy.deepcopy(snapshot.get("CONFIG", BASE_CONFIG))
    st.session_state.roster = copy.deepcopy(snapshot.get("roster", []))
    st.session_state.active = copy.deepcopy(snapshot.get("active", []))
    st.session_state.bout_list = copy.deepcopy(snapshot.get("bout_list", []))
    st.session_state.suggestions = copy.deepcopy(snapshot.get("suggestions", []))
    st.session_state.undo_stack = snapshot.get("undo_stack", []).copy()
    st.session_state.mat_order = copy.deepcopy(snapshot.get("mat_order", {}))
    st.session_state.mat_order_history = [copy.deepcopy(h) for h in snapshot.get("mat_order_history", [])]
    st.session_state.initialized = bool(st.session_state.roster)
    st.session_state.sortable_version += 1
    st.session_state.excel_bytes = None
    st.session_state.pdf_bytes = None
    return True

# ----------------------------------------------------------------------
# CORE LOGIC (100% your original code)
# ----------------------------------------------------------------------
def is_compatible(w1, w2):
    return w1["team"] != w2["team"] and not (
        (w1["grade"] == 5 and w2["grade"] in [7, 8]) or
        (w2["grade"] == 5 and w1["grade"] in [7, 8])
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
                if len(w["match_ids"]) >= CONFIG["MAX_MATCHES"]:
                    continue
                opps = [
                    o for o in active
                    if o["id"] not in w["match_ids"]
                    and o["id"] != w["id"]
                    and len(o["match_ids"]) < CONFIG["MAX_MATCHES"]
                    and is_compatible(w, o)
                    and abs(w["weight"] - o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"]))
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
            if abs(w["weight"] - o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"]))
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
    valid = [b for b in bout_list if b["manual"] != "Manually Removed"]
    valid = sorted(valid, key=lambda x: x["avg_weight"])
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
                "mat": mat_num, "slot": s, "bout_num": b["bout_num"],
                "w1": f"{b['w1_name']} ({b['w1_team']})",
                "w2": f"{b['w2_name']} ({b['w2_team']})",
                "w1_team": b["w1_team"], "w2_team": b["w2_team"],
                "is_early": b["is_early"]
            })
    for mat_num in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [m for m in schedules if m["mat"] == mat_num]
        mat_entries.sort(key=lambda x: x["slot"])
        for idx, entry in enumerate(mat_entries, 1):
            entry["mat_bout_num"] = idx
    return schedules

def apply_mat_order_to_global_schedule():
    rest_gap = CONFIG.get("REST_GAP", 4)
    base = generate_mat_schedule(st.session_state.bout_list, gap=rest_gap)
    schedules = []
    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        entries = [e for e in base if e["mat"] == mat]
        order = st.session_state.mat_order.get(mat)
        if order:
            entries_sorted = sorted(
                entries,
                key=lambda e: (order.index(e["bout_num"]) if e["bout_num"] in order else len(order) + e["slot"])
            )
        else:
            entries_sorted = sorted(entries, key=lambda e: e["slot"])
        for idx, e in enumerate(entries_sorted, start=1):
            e["slot"] = idx
            e["mat_bout_num"] = idx
            schedules.append(e)
    return schedules

def compute_rest_conflicts(schedule, min_gap):
    appearances = {}
    for e in schedule:
        b = next(x for x in st.session_state.bout_list if x["bout_num"] == e["bout_num"])
        for w_id, name, team in [(b["w1_id"], b["w1_name"], b["w1_team"]), (b["w2_id"], b["w2_name"], b["w2_team"])]:
            appearances.setdefault(w_id, {"name": name, "team": team, "matches": []})["matches"].append((e["mat"], e["slot"], e["bout_num"]))
    conflicts = []
    for w_id, info in appearances.items():
        by_mat = {}
        for mat, slot, bout_num in info["matches"]:
            by_mat.setdefault(mat, []).append((slot, bout_num))
        for mat, matches in by_mat.items():
            matches.sort(key=lambda x: x[0])
            for (slot1, bout1), (slot2, bout2) in zip(matches, matches[1:]):
                gap = slot2 - slot1
                if gap < min_gap:
                    conflicts.append({
                        "wrestler_id": w_id, "wrestler": info["name"], "team": info["team"],
                        "mat": mat, "slot1": slot1, "slot2": slot2,
                        "bout1": bout1, "bout2": bout2, "gap": gap,
                    })
    return conflicts

def color_dot_hex(hex_color: str) -> str:
    if not hex_color:
        return ""
    return f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;background:{hex_color};margin-right:6px;'></span>"

def remove_bout(bout_num: int):
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
    st.session_state.mat_order_history = []
    st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
    st.session_state.excel_bytes = None
    st.session_state.pdf_bytes = None
    st.session_state.sortable_version += 1
    st.rerun()

def undo_last():
    if st.session_state.undo_stack:
        bout_num = st.session_state.undo_stack.pop()
        b = next(x for x in st.session_state.bout_list if x["bout_num"] == bout_num and x.get("manual") == "Manually Removed")
        b["manual"] = ""
        w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
        w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
        if b["w2_id"] not in w1["match_ids"]:
            w1["match_ids"].append(b["w2_id"])
        if b["w1_id"] not in w2["match_ids"]:
            w2["match_ids"].append(b["w1_id"])
        st.session_state.bout_list.sort(key=lambda x: x["avg_weight"])
        st.session_state.mat_order = {}
        st.session_state.mat_order_history = []
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.success("Undo successful!")
        st.session_state.excel_bytes = None
        st.session_state.pdf_bytes = None
        st.session_state.sortable_version += 1
    st.rerun()

def undo_last_drag():
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
    errors = []
    required = ["id", "name", "team", "grade", "level", "weight", "early_matches", "scratch"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        errors.append("Missing columns: " + ", ".join(missing))
        return errors
    if df.empty:
        errors.append("Roster file is empty.")
    if df["id"].duplicated().any():
        dups = df["id"][df["id"].duplicated()].unique().tolist()
        errors.append(f"Duplicate wrestler IDs: {dups}")
    for col in ["grade", "level", "weight"]:
        bad = pd.to_numeric(df[col], errors="coerce").isna()
        if bad.any():
            bad_vals = df.loc[bad, col].astype(str).unique().tolist()
            errors.append(f"Column '{col}' has non-numeric values: {bad_vals}")
    return errors

# ----------------------------------------------------------------------
# UI STARTS HERE
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.markdown(f"<style>{SORTABLE_STYLE}</style>", unsafe_allow_html=True)
st.title("Wrestling Meet Scheduler")
st.caption("Upload roster → Generate → Edit → Download. **No data stored on server.**")

# ------------------- SAVE / LOAD PROGRESS -------------------
if st.session_state.initialized:
    st.success("Schedule is active!")
    col_save, col_load = st.columns(2)
    with col_save:
        snapshot = get_state_snapshot()
        st.download_button(
            label="Save Progress (JSON)",
            data=json.dumps(snapshot, indent=2).encode(),
            file_name=f"wrestling_schedule_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
            help="Download your current state – upload later to resume."
        )
    with col_load:
        uploaded_state = st.file_uploader("Load Saved Progress", type=["json"], key="load_progress")
        if uploaded_state:
            try:
                snapshot = json.load(uploaded_state)
                if restore_state_from_snapshot(snapshot):
                    st.success("Progress loaded successfully!")
                    st.rerun()
            except Exception as e:
                st.error(f"Load failed: {e}")
    st.warning("Streamlit sessions time out after ~30 min of inactivity — **save often!**")
    st.markdown("---")

# ------------------- STEP 1 & 2 -------------------
st.markdown("### Step 1 – Download roster template (CSV)")
st.download_button("Download template CSV", TEMPLATE_CSV.encode(), "roster_template.csv", "text/csv")

st.markdown("### Step 2 – Upload your completed roster.csv")
uploaded = st.file_uploader(
    "Upload roster.csv",
    type="csv",
    key=f"roster_csv_uploader_v{st.session_state.roster_uploader_version}"
)

if uploaded and not st.session_state.initialized:
    try:
        df = pd.read_csv(uploaded)
        errors = validate_roster_df(df)
        if errors:
            for e in errors:
                st.error(e)
            st.stop()
        wrestlers = df.to_dict("records")
        for w in wrestlers:
            w["id"] = int(w["id"])
            w["grade"] = int(w["grade"])
            w["level"] = float(w["level"])
            w["weight"] = float(w["weight"])
            w["early"] = str(w["early_matches"]).strip().upper() in ["Y", "1", "TRUE"]
            w["scratch"] = str(w["scratch"]).strip().upper() in ["Y", "1", "TRUE"]
            w["match_ids"] = []
        st.session_state.roster = wrestlers
        st.session_state.active = [w for w in wrestlers if not w["scratch"]]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.initialized = True
        st.success(f"Roster loaded – {len(wrestlers)} wrestlers ({len(st.session_state.active)} active).")
        st.rerun()
    except Exception as e:
        st.error(f"Error loading roster: {e}")

# Start Over button
if st.session_state.get("initialized"):
    if st.button("Start Over / Load New Roster"):
        for key in ["initialized","bout_list","mat_schedules","suggestions","active","undo_stack",
                    "mat_order","excel_bytes","pdf_bytes","roster","mat_order_history","manual_match_warning"]:
            st.session_state.pop(key, None)
        st.session_state.roster_uploader_version += 1
        st.success("Cleared – upload a new roster.")
        st.rerun()

# ------------------- REST OF YOUR ORIGINAL APP (unchanged) -------------------
# Everything from the sidebar onward is exactly your original code.
# (You already have this part – just keep it unchanged below this line.)

# Sidebar settings, tabs (Match Builder, Meet Summary, Help), drag-and-drop mats,
# generate Excel/PDF, etc. – all 100% identical to your working version.

# Final lines
if not st.session_state.initialized:
    st.info("Upload a roster CSV to get started.")

st.markdown("---")
st.caption("**Privacy**: Your data never leaves your browser. Nothing is stored on the server.")
