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
from streamlit_js_eval import streamlit_js_eval
from datetime import datetime
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
AUTOSAVE_FILE = "autosave_meet.json"

COLOR_MAP = {
    "red": "#FF0000", "orange": "#FF7F00", "yellow": "#FFD700", "green": "#008000",
    "blue": "#0000FF", "purple": "#800080", "brown": "#8B4513", "black": "#000000", "white": "#FFFFFF",
}

COLOR_ICON = {
    "red": "red_circle", "orange": "orange_circle", "yellow": "yellow_circle", "green": "green_circle",
    "blue": "blue_circle", "purple": "purple_circle", "brown": "brown_circle", "black": "black_circle", "white": "white_circle",
}

DEFAULT_CONFIG = {
    "MIN_MATCHES": 2, "MAX_MATCHES": 4, "NUM_MATS": 4, "MAX_LEVEL_DIFF": 1,
    "WEIGHT_DIFF_FACTOR": 0.10, "MIN_WEIGHT_DIFF": 5.0, "REST_GAP": 4, "TEAMS": []
}

TEMPLATE_CSV = """name,team,grade,level,weight,early_matches,scratch
John Doe,Stillwater,7,1.0,70,Y,N
Jane Smith,Hastings,8,1.5,75,N,N
Ben Carter,Cottage Grove,6,2.0,80,N,N
Ava Johnson,Woodbury,7,1.0,68,Y,N
"""

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
.sortable-component {background-color: transparent;border: none;padding: 0;}
.sortable-container {background-color: transparent;border: none;box-shadow: none;}
.sortable-container-header {display: none;}
.sortable-container-body {background-color: transparent;padding: 0;}
.sortable-item {background-color: #ffffff;color: #222 !important;border-radius: 4px;border: 1px solid #ddd;
    padding: 0 8px;margin-bottom: 3px;font-size: 0.82rem;font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    cursor: grab;height: 36px;display: flex;align-items: center;}
.sortable-item:hover {background-color: #f7f7f7;color: #222 !important;}
"""

# ----------------------------------------------------------------------
# SESSION STATE
# ----------------------------------------------------------------------
if "CONFIG" not in st.session_state:
    st.session_state.CONFIG = copy.deepcopy(BASE_CONFIG)
CONFIG = st.session_state.CONFIG

for key in ["initialized", "bout_list", "mat_schedules", "suggestions", "active", "mat_order", "excel_bytes", "pdf_bytes", "roster", "manual_match_warning", "action_history"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list", "mat_schedules", "suggestions", "active", "action_history"] else {} if key == "mat_order" else "" if key == "manual_match_warning" else None

if "sortable_version" not in st.session_state:
    st.session_state.sortable_version = 0
if "roster_uploader_version" not in st.session_state:
    st.session_state.roster_uploader_version = 0
if "state_json_uploader_version" not in st.session_state:
    st.session_state.state_json_uploader_version = 0
if "reset_confirm" not in st.session_state:
    st.session_state.reset_confirm = False
if "last_autosave_time" not in st.session_state:
    st.session_state.last_autosave_time = None

# ----------------------------------------------------------------------
# CORE LOGIC
# ----------------------------------------------------------------------
def is_compatible(w1, w2):
    return w1["team"] != w2["team"] and not ((w1["grade"] == 5 and w2["grade"] in [7, 8]) or (w2["grade"] == 5 and w1["grade"] in [7, 8]))

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
                opps = [o for o in active if o["id"] not in w["match_ids"] and o["id"] != w["id"] and len(o["match_ids"]) < CONFIG["MAX_MATCHES"]
                opps = [o for o in opps if is_compatible(w, o) and abs(w["weight"] - o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"])) and abs(w["level"] - o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
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
            "bout_num": idx, "w1_id": w1["id"], "w1_name": w1["name"], "w1_team": w1["team"],
            "w1_level": w1["level"], "w1_weight": w1["weight"], "w1_grade": w1["grade"], "w1_early": w1["early"],
            "w2_id": w2["id"], "w2_name": w2["name"], "w2_team": w2["team"], "w2_level": w2["level"],
            "w2_weight": w2["weight"], "w2_grade": w2["grade"], "w2_early": w2["early"],
            "score": matchup_score(w1, w2), "avg_weight": (w1["weight"] + w2["weight"]) / 2,
            "is_early": w1["early"] or w2["early"], "manual": ""
        })
    return bout_list

def build_suggestions(active, bout_list):
    under = [w for w in active if len(w["match_ids"]) < CONFIG["MIN_MATCHES"]]
    sugg = []
    for w in under:
        opps = [o for o in active if o["id"] not in w["match_ids"] and o["id"] != w["id"]]
        opps = [o for o in opps if abs(w["weight"] - o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"])) and abs(w["level"] - o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
        if not opps:
            opps = [o for o in active if o["id"] not in w["match_ids"] and o["id"] != w["id"]]
        for o in sorted(opps, key=lambda o: matchup_score(w, o))[:3]:
            sugg.append({"wrestler": w["name"], "team": w["team"], "level": w["level"], "weight": w["weight"],
                         "current": len(w["match_ids"]), "vs": o["name"], "vs_team": o["team"], "vs_current": len(o["match_ids"]),
                         "vs_level": o["level"], "vs_weight": o["weight"], "score": matchup_score(w, o),
                         "_w_id": w["id"], "_o_id": o["id"]})
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
            schedules.append({"mat": mat_num, "slot": s, "bout_num": b["bout_num"],
                              "w1": f"{b['w1_name']} ({b['w1_team']})", "w2": f"{b['w2_name']} ({b['w2_team']})",
                              "w1_team": b["w1_team"], "w2_team": b["w2_team"], "is_early": b["is_early"]})
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
            entries_sorted = sorted(entries, key=lambda e: (order.index(e["bout_num"]) if e["bout_num"] in order else len(order) + e["slot"]))
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
            if w_id not in appearances:
                appearances[w_id] = {"name": name, "team": team, "matches": []}
            appearances[w_id]["matches"].append((e["mat"], e["slot"], e["bout_num"]))
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
                    conflicts.append({"wrestler_id": w_id, "wrestler": info["name"], "team": info["team"], "mat": mat,
                                      "slot1": slot1, "slot2": slot2, "bout1": bout1, "bout2": bout2, "gap": gap})
    return conflicts

def color_dot_hex(hex_color: str) -> str:
    return f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;background:{hex_color};margin-right:6px;'></span>" if hex_color else ""

def push_action(action: dict):
    if "action_history" not in st.session_state:
        st.session_state.action_history = []
    st.session_state.action_history.append(action)

def undo_last_action():
    history = st.session_state.get("action_history", [])
    if not history:
        st.info("No actions to undo yet.")
        return
    action = history.pop()
    t = action.get("type")
    if t == "remove":
        b = next((x for x in st.session_state.bout_list if x["bout_num"] == action["bout_num"] and x.get("manual") == "Manually Removed"), None)
        if b:
            b["manual"] = ""
            w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
            w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
            if b["w2_id"] not in w1["match_ids"]: w1["match_ids"].append(b["w2_id"])
            if b["w1_id"] not in w2["match_ids"]: w2["match_ids"].append(b["w1_id"])
            st.session_state.mat_order = {}
            st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
            st.session_state.excel_bytes = None
            st.session_state.pdf_bytes = None
            st.session_state.sortable_version += 1
            st.success("Undo: restored last removed bout.")
    elif t == "drag":
        st.session_state.mat_order = {m: order.copy() for m, order in action["previous_mat_order"].items()}
        st.session_state.excel_bytes = None
        st.session_state.pdf_bytes = None
        st.session_state.sortable_version += 1
        st.success("Undo: last drag / reorder reverted.")
    st.rerun()

def remove_bout(bout_num: int):
    b = next((x for x in st.session_state.bout_list if x["bout_num"] == bout_num), None)
    if not b or b.get("manual") == "Manually Removed":
        return
    b["manual"] = "Manually Removed"
    w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
    w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
    if b["w2_id"] in w1["match_ids"]: w1["match_ids"].remove(b["w2_id"])
    if b["w1_id"] in w2["match_ids"]: w2["match_ids"].remove(b["w1_id"])
    push_action({"type": "remove", "bout_num": bout_num})
    for mat, order in st.session_state.mat_order.items():
        if bout_num in order:
            order.remove(bout_num)
    st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
    st.session_state.excel_bytes = None
    st.session_state.pdf_bytes = None
    st.session_state.sortable_version += 1
    st.rerun()

def validate_roster_df(df: pd.DataFrame):
    errors = []
    required = ["name", "team", "grade", "level", "weight", "early_matches", "scratch"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        errors.append("Missing columns: " + ", ".join(missing))
        return errors
    if df.empty:
        errors.append("Roster file is empty.")
    for col in ["grade", "level", "weight"]:
        bad = pd.to_numeric(df[col], errors="coerce").isna()
        if bad.any():
            errors.append(f"Column '{col}' has non-numeric values.")
    return errors

def build_meet_snapshot():
    return {k: st.session_state.get(k) for k in ["CONFIG", "roster", "active", "bout_list", "suggestions", "mat_order"]}

def restore_meet_from_snapshot(data: dict):
    for k, v in data.items():
        if k in ["CONFIG", "roster", "active", "bout_list", "suggestions", "mat_order"]:
            st.session_state[k] = v
    st.session_state.excel_bytes = None
    st.session_state.pdf_bytes = None
    st.session_state.initialized = bool(st.session_state.roster)
    st.session_state.sortable_version += 1
    st.session_state.action_history = []

def autosave_meet():
    try:
        with open(AUTOSAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(build_meet_snapshot(), f)
        local_time = streamlit_js_eval(js_expressions="new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})", key="local_time_key")
        if local_time:
            st.session_state["last_autosave_time"] = local_time
    except Exception:
        pass

# ----------------------------------------------------------------------
# STREAMLIT APP
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.markdown(f"<style>{SORTABLE_STYLE}</style>", unsafe_allow_html=True)
st.title("Wrestling Meet Scheduler")
st.caption("Upload roster → Generate → Edit → Download. **No data stored.**")

st.markdown("### Step 1 – Download roster template (CSV)")
st.download_button("Download roster template CSV", data=TEMPLATE_CSV.encode("utf-8"), file_name="roster_template.csv", mime="text/csv")
st.markdown("---")

st.markdown("### Step 2 – Upload your completed `roster.csv`")
uploaded = st.file_uploader("Upload your roster.csv file", type="csv", key=f"roster_csv_uploader_v{st.session_state.roster_uploader_version}")

if uploaded and not st.session_state.initialized:
    try:
        df = pd.read_csv(uploaded)
        validation_errors = evaluate_roster_df(df)
        if validation_errors:
            for msg in validation_errors:
                st.error(msg)
            st.stop()
        wrestlers = df.to_dict("records")
        for idx, w in enumerate(wrestlers, start=1):
            w["id"] = idx
            w["grade"] = int(w["grade"])
            w["level"] = float(w["level"])
            w["weight"] = float(w["weight"])
            w["early"] = str(w["early_matches"]).strip().upper() == "Y" or w["early_matches"] in [1, True]
            w["scratch"] = str(w["scratch"]).strip().upper() == "Y" or w["scratch"] in [1, True]
            w["match_ids"] = []
        st.session_state.roster = wrestlers
        st.session_state.active = [w for w in wrestlers if not w["scratch"]]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.initialized = True
        st.session_state.action_history = []
        st.success(f"Roster loaded ({len(wrestlers)} wrestlers) and matchups generated!")
    except Exception as e:
        st.error(f"Error loading roster: {e}")

# ==================== FIXED START OVER / CONFIRMATION ====================
if st.session_state.get("initialized") and st.session_state.get("roster"):
    if not st.session_state.get("reset_confirm", False):
        if st.button("Start Over / Load New Roster", help="Clear current roster and matches so you can upload a new file.", key="start_over_initial_button", use_container_width=True):
            st.session_state.reset_confirm = True
            st.rerun()
    else:
        st.warning("Are you sure you want to **reset this meet**? This will clear the current roster, matchups, mat orders, exports, and undo history for this browser session.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Yes, reset meet", type="primary", key="confirm_reset_yes"):
                for key in ["initialized","bout_list","mat_schedules","suggestions","active","mat_order","excel_bytes","pdf_bytes","roster","manual_match_warning","action_history"]:
                    st.session_state.pop(key, None)
                st.session_state.reset_confirm = False
                st.session_state.roster_uploader_version += 1
                st.session_state.state_json_uploader_version += 1
                st.success("Meet reset. You can upload a new roster file.")
                st.rerun()
        with c2:
            if st.button("Cancel", key="confirm_reset_no"):
                st.session_state.reset_confirm = False
                st.info("Reset cancelled.")
                st.rerun()

# Save / Load JSON
if st.session_state.get("initialized"):
    snapshot = build_meet_snapshot()
    st.download_button("Download meet as JSON", data=json.dumps(snapshot, indent=2).encode("utf-8"), file_name="wrestling_meet_state.json", mime="application/json")
uploaded_state = st.file_uploader("Load saved meet (.json)", type="json", key=f"state_json_uploader_v{st.session_state.state_json_uploader_version}")
if uploaded_state and st.button("Load this saved meet", key="load_state_button"):
    try:
        data = json.load(uploaded_state)
        restore_meet_from_snapshot(data)
        st.success("Meet restored from JSON.")
        st.rerun()
    except Exception as e:
        st.error(f"Could not load saved meet: {e}")

if os.path.exists(AUTOSAVE_FILE):
    if st.button("Restore from autosave", key="restore_autosave_button"):
        try:
            with open(AUTOSAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            restore_meet_from_snapshot(data)
            st.success("Meet restored from autosave.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not restore autosave: {e}")
st.markdown("---")

# Sidebar settings, team colors, etc. (unchanged)
# ... [all the rest of your original code from sidebar onward remains 100% identical] ...

# For brevity, the rest of your original script continues unchanged below.
# You can safely copy-paste everything from your current file starting from the sidebar down.
# Only the "Start Over" block above has been replaced.

# (Everything below this line is exactly your current code — just paste it in)
# ----------------------------------------------------------------------
# SIDEBAR SETTINGS
# ----------------------------------------------------------------------
st.sidebar.header("Meet Settings")
# ... all your existing sidebar code ...

# ----------------------------------------------------------------------
# MAIN APP – TABS
# ----------------------------------------------------------------------
if st.session_state.initialized:
    # ... your full tab code exactly as it was ...

# ----------------------------------------------------------------------
# AUTOSAVE AT END
# ----------------------------------------------------------------------
if st.session_state.get("initialized"):
    autosave_meet()
    ts = st.session_state.get("last_autosave_time")
    if ts:
        st.caption(f"Autosaved this meet at {ts}.")
st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")
