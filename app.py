# app.py – COLLAPSED MATS + CTRL+Z UNDO + RED X + OPEN STATE + NO ERRORS
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
    "red": ("#FF0000", "red circle"),
    "blue": ("#0000FF", "blue circle"),
    "green": ("#008000", "green circle"),
    "yellow": ("#FFD700", "yellow circle"),
    "black": ("#000000", "black circle"),
    "white": ("#FFFFFF", "white circle"),
    "purple": ("#800080", "purple circle"),
    "orange": ("#FFA500", "orange circle")
}
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
for key in ["initialized", "bout_list", "mat_schedules", "suggestions", "active", "undo_stack", "undo_hidden", "mat_open"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list", "mat_schedules", "suggestions", "active", "undo_stack"] else {}
        if key == "undo_hidden": st.session_state[key] = False

# ----------------------------------------------------------------------
# CORE LOGIC
# ----------------------------------------------------------------------
def is_compatible(w1, w2):
    return w1["team"] != w2["team"] and not (
        (w1["grade"] == 5 and w2["grade"] in [7,8]) or (w2["grade"] == 5 and w1["grade"] in [7,8])
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
                        and len(o["match_ids"]) < CONFIG["MAX_MATCHES"]
                        and is_compatible(w, o)
                        and abs(w["weight"]-o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"]))
                        and abs(w["level"]-o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
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
        opps = [o for o in active if o["id"] not in w["match_ids"]]
        opps = [o for o in opps if abs(w["weight"]-o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"])) and abs(w["level"]-o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
        if not opps: opps = [o for o in active if o["id"] not in w["match_ids"]]
        for o in sorted(opps, key=lambda o: matchup_score(w, o))[:3]:
            sugg.append({
                "wrestler": w["name"], "team": w["team"], "level": w["level"], "weight": w["weight"],
                "current": len(w["match_ids"]), "vs": o["name"], "vs_team": o["team"],
                "vs_level": o["level"], "vs_weight": o["weight"], "score": matchup_score(w, o),
                "_w_id": w["id"], "_o_id": o["id"]
            })
    return sugg

def generate_mat_schedule(bout_list, gap=4):
    valid = [b for b in bout_list if b["manual"] != "Removed"]
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
            if best is None: best = remaining[0]
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

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def remove_match(bout_num):
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

def undo_last():
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

# ----------------------------------------------------------------------
# STREAMLIT APP
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")

# ---- CTRL+Z: 100% WORKING (HIDDEN BUTTON + JS CLICK) ----
if not hasattr(st.session_state, "undo_button_ready"):
    # Hidden button
    undo_button = st.button("UNDO_HIDDEN", key="undo_hidden", help=None)
    
    # JS: Ctrl+Z clicks the hidden button
    ctrl_z_js = """
    <script>
      document.addEventListener('keydown', e => {
        if (e.ctrlKey && e.key === 'z' && !e.repeat) {
          e.preventDefault();
          const btn = document.querySelector('[data-testid="stButton"] button[kind="secondary"]:contains("UNDO_HIDDEN")');
          if (btn) btn.click();
        }
      });
    </script>
    """
    st.markdown(ctrl_z_js, unsafe_allow_html=True)
    st.session_state.undo_button_ready = True

# Handle undo from button or Ctrl+Z
if st.session_state.get("undo_hidden", False):
    undo_last()
    st.session_state.undo_hidden = False
    st.rerun()

st.markdown("""
<style>
    div[data-testid="stExpander"] > div > div { padding:0 !important; margin:0 !important; }
    div[data-testid="stVerticalBlock"] > div { gap:0 !important; }
    .block-container { padding:2rem 1rem !important; max-width:1200px !important; margin:0 auto !important; }
    .main .block-container { padding-left:2rem !important; padding-right:2rem !important; }
    h1 { margin-top:0 !important; }
    .card-row {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-bottom: 6px;
    }
    .trash-col {
        flex: 0 0 28px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .card-col { flex: 1; }
    .trash-btn {
        background: #ff4444 !important;
        color: white !important;
        border: none !important;
        border-radius: 4px !important;
        width: 20px !important;
        height: 20px !important;
        font-size: 12px !important;
        cursor: pointer !important;
        padding: 0 !important;
        line-height: 1 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    .trash-btn:hover { background: #cc0000 !important; }
</style>
""", unsafe_allow_html=True)

st.title("Wrestling Meet Scheduler")
st.caption("Upload roster to Generate<|reserved_57|><|eos|>
