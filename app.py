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
    "REST_GAP": 4,
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
            loaded_config = json.load(f)
            CONFIG = {**DEFAULT_CONFIG, **loaded_config}
    except Exception:
        CONFIG = DEFAULT_CONFIG.copy()
        with open(CONFIG_FILE, "w") as f:
            json.dump(CONFIG, f, indent=4)
else:
    CONFIG = DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)

if "REST_GAP" not in CONFIG:
    CONFIG["REST_GAP"] = DEFAULT_CONFIG["REST_GAP"]
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

def generate_mat_schedule(bout_list):
    valid = [b for b in bout_list if b["manual"] != "Manually Removed"]
    
    # 1. SORT BY AVERAGE WEIGHT FIRST (lightest to heaviest)
    valid.sort(key=lambda x: x["avg_weight"])
    
    # 2. DISTRIBUTE EVENLY ACROSS MATS
    per_mat = len(valid) // CONFIG["NUM_MATS"]
    extra = len(valid) % CONFIG["NUM_MATS"]
    mats = []
    start = 0
    for i in range(CONFIG["NUM_MATS"]):
        end = start + per_mat + (1 if i < extra else 0)
        mats.append(valid[start:end])
        start = end

    schedules = []
    st.session_state.mat_order = {}

    for mat_num, mat_bouts in enumerate(mats, 1):
        if not mat_bouts:
            continue

        # Step 1: Pre-sort by total match count
        match_counts = {}
        for bout in mat_bouts:
            count = len([b for b in mat_bouts if b["w1_id"] == bout["w1_id"] or b["w2_id"] == bout["w1_id"]])
            count += len([b for b in mat_bouts if b["w1_id"] == bout["w2_id"] or b["w2_id"] == bout["w2_id"]])
            match_counts[bout["bout_num"]] = count

        mat_bouts.sort(key=lambda x: match_counts.get(x["bout_num"], 0), reverse=True)

        # Step 2: Greedy cooldown scheduler with SLOT CHECK
        cooldown = {}
        placed = []
        queue = mat_bouts[:]
        slots = [None] * len(mat_bouts)

        while queue:
            bout = queue.pop(0)
            w1, w2 = bout["w1_id"], bout["w2_id"]

            placed_slot = None
            for s in range(len(slots)):
                if slots[s] is not None:
                    continue
                if cooldown.get(w1, 0) > 0 or cooldown.get(w2, 0) > 0:
                    continue
                safe = True
                for check in range(max(0, s - CONFIG["REST_GAP"]), min(len(slots), s + CONFIG["REST_GAP"] + 1)):
                    if check == s: continue
                    existing = slots[check]
                    if existing and (existing["w1_id"] in (w1, w2) or existing["w2_id"] in (w1, w2)):
                        safe = False
                        break
                if safe:
                    placed_slot = s
                    break

            if placed_slot is not None:
                slots[placed_slot] = bout
                placed.append(bout)
                cooldown[w1] = CONFIG["REST_GAP"] + 1
                cooldown[w2] = CONFIG["REST_GAP"] + 1
            else:
                queue.append(bout)

            for w in list(cooldown.keys()):
                cooldown[w] = max(0, cooldown[w] - 1)

        # Fallback
        for bout in mat_bouts:
            if bout not in placed:
                for s in range(len(slots)):
                    if slots[s] is None:
                        slots[s] = bout
                        placed.append(bout)
                        break

        # Build schedule
        for slot_idx, bout in enumerate(slots, 1):
            if bout:
                schedules.append({
                    "mat": mat_num,
                    "slot": slot_idx,
                    "bout_num": bout["bout_num"],
                    "w1": f"{bout['w1_name']} ({bout['w1_team']})",
                    "w2": f"{bout['w2_name']} ({bout['w2_team']})",
                    "w1_team": bout["w1_team"],
                    "w2_team": bout["w2_team"],
                    "is_early": bout["is_early"]
                })

        st.session_state.mat_order[mat_num] = [b["bout_num"] for b in placed if b]

    # ASSIGN MAT BOUT NUMBERS
    for mat_num in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [m for m in schedules if m["mat"] == mat_num]
        mat_entries.sort(key=lambda x: x["slot"])
        for idx, entry in enumerate(mat_entries, 1):
            entry["mat_bout_num"] = idx

    return schedules

# ----------------------------------------------------------------------
# DEBUG: Verify rest gaps
# ----------------------------------------------------------------------
def verify_rest_gaps():
    violations = []
    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [e for e in st.session_state.mat_schedules if e["mat"] == mat]
        wrestler_slots = {}
        for e in mat_entries:
            b = next(x for x in st.session_state.bout_list if x["bout_num"] == e["bout_num"])
            for wid in [b["w1_id"], b["w2_id"]]:
                if wid not in wrestler_slots:
                    wrestler_slots[wid] = []
                wrestler_slots[wid].append(e["slot"])
        for wid, slots in wrestler_slots.items():
            slots.sort()
            for i in range(1, len(slots)):
                if slots[i] - slots[i-1] <= CONFIG["REST_GAP"]:
                    name = next(w for w in st.session_state.active if w["id"] == wid)["name"]
                    violations.append(f"Mat {mat}: {name} in slots {slots[i-1]} and {slots[i]} (gap {slots[i]-slots[i-1]})")
    if violations:
        st.error("REST_GAP VIOLATIONS:\n" + "\n".join(violations[:10]))
    else:
        st.success(f"REST_GAP={CONFIG['REST_GAP']} enforced across all mats!")

# ----------------------------------------------------------------------
# HELPERS (unchanged)
# ----------------------------------------------------------------------
# ... (remove_match, undo_last, move_up, move_down)

# ----------------------------------------------------------------------
# STREAMLIT APP
# ----------------------------------------------------------------------
# ... (same as before)

# After schedule generation, call verify_rest_gaps()
if st.session_state.initialized:
    # ... (upload, settings, etc.)
    st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
    verify_rest_gaps()  # ADD THIS LINE
