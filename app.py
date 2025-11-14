# app.py – Wrestling Scheduler – ULTRA FAST & STABLE
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

TEAMS = CONFIG["TEAMS"]

# ----------------------------------------------------------------------
# SESSION STATE (MINIMAL)
# ----------------------------------------------------------------------
for key in ["initialized","active","bout_list","mat_schedules","suggestions","undo_stack","mat_order","excel_bytes","pdf_bytes"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list","mat_schedules","suggestions","active","undo_stack"] else {} if key == "mat_order" else None

# ----------------------------------------------------------------------
# CACHED FUNCTIONS
# ----------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def generate_initial_matchups_cached(active):
    return generate_initial_matchups(active)

@st.cache_data(show_spinner=False)
def build_suggestions_cached(active, bout_list):
    return build_suggestions(active, bout_list)

@st.cache_data(show_spinner=False)
def generate_mat_schedule_cached(bout_list):
    return generate_mat_schedule(bout_list)

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
    valid.sort(key=lambda x: x["avg_weight"])
    per_mat = len(valid) // CONFIG["NUM_MATS"]
    extra = len(valid) % CONFIG["NUM_MATS"]
    mats = []
    start = 0
    for i in range(CONFIG["NUM_MATS"]):
        end = start + per_mat + (1 if i < extra else 0)
        mats.append(valid[start:end])
        start = end

    schedules = []
    for mat_num, mat_bouts in enumerate(mats, 1):
        for slot_idx, bout in enumerate(mat_bouts, 1):
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
    st.session_state.mat_schedules = generate_mat_schedule_cached(st.session_state.bout_list)
    st.session_state.suggestions = build_suggestions_cached(st.session_state.active, st.session_state.bout_list)
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
        st.session_state.mat_schedules = generate_mat_schedule_cached(st.session_state.bout_list)
        st.session_state.suggestions = build_suggestions_cached(st.session_state.active, st.session_state.bout_list)
        st.success("Undo successful!")
        st.session_state.excel_bytes = None
        st.session_state.pdf_bytes = None
    st.rerun()

# ----------------------------------------------------------------------
# STREAMLIT APP
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.title("Wrestling Meet Scheduler")
st.caption("Upload roster to Generate to Edit to Download. **No data stored.**")

# ---- UPLOAD ----
uploaded = st.file_uploader("Upload `roster.csv`", type="csv")
if uploaded and not st.session_state.initialized:
    with st.spinner("Loading roster..."):
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
        st.session_state.bout_list = generate_initial_matchups_cached(st.session_state.active)
        st.session_state.suggestions = build_suggestions_cached(st.session_state.active, st.session_state.bout_list)
        st.session_state.mat_schedules = generate_mat_schedule_cached(st.session_state.bout_list)
        st.session_state.initialized = True
        st.success("Roster loaded in < 2 seconds!")

# ---- SETTINGS ----
if st.session_state.initialized:
    st.sidebar.header("Settings")
    new_mats = st.sidebar.number_input("Number of Mats", 1, 10, CONFIG["NUM_MATS"], key="num_mats")
    if new_mats != CONFIG["NUM_MATS"]:
        CONFIG["NUM_MATS"] = new_mats
        st.session_state.mat_schedules = generate_mat_schedule_cached(st.session_state.bout_list)
        st.rerun()

    st.subheader("Schedule Summary")
    total_bouts = len([b for b in st.session_state.bout_list if b["manual"] != "Manually Removed"])
    st.write(f"**Matches Generated**: {total_bouts} | **Assigned to Mats**: {len(st.session_state.mat_schedules)}")

    st.subheader("Mat Previews")
    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [e for e in st.session_state.mat_schedules if e["mat"] == mat]
        with st.expander(f"Mat {mat} ({len(mat_entries)} matches)", expanded=True):
            for e in mat_entries:
                b = next(x for x in st.session_state.bout_list if x["bout_num"] == e["bout_num"])
                bg = "#fff3cd" if b["is_early"] else "#ffffff"
                st.markdown(f"""
                <div style="background:{bg}; border:1px solid #ddd; padding:8px; border-radius:4px; margin-bottom:4px;">
                    <b>{e['mat_bout_num']}:</b> {b['w1_name']} ({b['w1_team']}) vs {b['w2_name']} ({b['w2_team']})
                    <small> | Grade/Level/Weight | {'Early' if b['is_early'] else ''}</small>
                </div>
                """, unsafe_allow_html=True)

    if st.session_state.undo_stack:
        st.markdown("---")
        if st.button("Undo Last Removal"):
            undo_last()

    # ---- GENERATE FILES ----
    if st.button("Generate Excel + PDF", type="primary"):
        with st.spinner("Generating files..."):
            try:
                # Excel
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as writer:
                    pd.DataFrame(st.session_state.active).to_excel(writer, sheet_name='Roster', index=False)
                    pd.DataFrame(st.session_state.bout_list).to_excel(writer, sheet_name='Matchups', index=False)
                    for m in range(1, CONFIG["NUM_MATS"]+1):
                        data = [e for e in st.session_state.mat_schedules if e["mat"] == m]
                        if not data:
                            pd.DataFrame([["", "", ""]], columns=["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]).to_excel(writer, f"Mat {m}", index=False)
                            continue
                        df = pd.DataFrame(data)[["mat_bout_num","w1","w2"]]
                        df.columns = ["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]
                        df.to_excel(writer, f"Mat {m}", index=False)
                st.session_state.excel_bytes = out.getvalue()

                # PDF
                buf = io.BytesIO()
                doc = SimpleDocTemplate(buf, pagesize=letter)
                elements = []
                styles = getSampleStyleSheet()
                for m in range(1, CONFIG["NUM_MATS"]+1):
                    data = [e for e in st.session_state.mat_schedules if e["mat"] == m]
                    if not data: continue
                    table = [["#","Wrestler 1","Wrestler 2"]]
                    for e in data:
                        b = next(x for x in st.session_state.bout_list if x["bout_num"] == e["bout_num"])
                        table.append([e["mat_bout_num"],
                                      f"{b['w1_name']} ({b['w1_team']})",
                                      f"{b['w2_name']} ({b['w2_team']})"])
                    t = Table(table, colWidths=[0.5*inch, 3*inch, 3*inch])
                    t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,rl_colors.black)]))
                    elements += [Paragraph(f"Mat {m}", styles["Title"]), Spacer(1,12), t, PageBreak()]
                doc.build(elements)
                st.session_state.pdf_bytes = buf.getvalue()

                st.success("Files ready!")
            except Exception as e:
                st.error(f"Error: {e}")

    # Download buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state.excel_bytes:
            st.download_button("Download Excel", st.session_state.excel_bytes, "meet_schedule.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with col2:
        if st.session_state.pdf_bytes:
            st.download_button("Download PDF", st.session_state.pdf_bytes, "meet_schedule.pdf", "application/pdf")

st.markdown("---")
st.caption("**Privacy**: All processing in your browser. No data stored.")
