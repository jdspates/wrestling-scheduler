# app.py - FINAL: TEAM COLORS + EARLY MATCHES IN MAT PREVIEWS (NO GLOBAL HTML)
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

# Add hex color to each team
for t in TEAMS:
    t["color_hex"] = COLOR_MAP.get(t["color"], ("#000000", ""))[0]

# ----------------------------------------------------------------------
# SESSION STATE
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
# MEET SETTINGS
# ----------------------------------------------------------------------
st.sidebar.header("Meet Settings")
changed = False
st.sidebar.subheader("Match & Scheduling Rules")
col1, col2 = st.sidebar.columns(2)
with col1:
    new_min = st.number_input("Min Matches per Wrestler", 1, 10, CONFIG["MIN_MATCHES"], key="min_matches")
    new_max = st.number_input("Max Matches per Wrestler", 1, 10, CONFIG["MAX_MATCHES"], key="max_matches")
    new_mats = st.number_input("Number of Mats", 1, 10, CONFIG["NUM_MATS"], key="num_mats")
with col2:
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
    new_color = st.sidebar.selectbox(
        "Color",
        list(COLOR_MAP.keys()),
        index=list(COLOR_MAP.keys()).index(team["color"]),
        format_func=lambda x: x.capitalize(),
        key=f"color_{i}",
        label_visibility="collapsed"
    )
    if new_name != team["name"]: team["name"], changed = new_name, True
    if new_color != team["color"]: team["color"], changed = new_color, True

if (new_min != CONFIG["MIN_MATCHES"] or new_max != CONFIG["MAX_MATCHES"] or
    new_mats != CONFIG["NUM_MATS"] or new_level_diff != CONFIG["MAX_LEVEL_DIFF"] or
    new_weight_factor != CONFIG["WEIGHT_DIFF_FACTOR"] or new_min_weight != CONFIG["MIN_WEIGHT_DIFF"]):
    CONFIG.update({
        "MIN_MATCHES": new_min, "MAX_MATCHES": new_max, "NUM_MATS": new_mats,
        "MAX_LEVEL_DIFF": new_level_diff, "WEIGHT_DIFF_FACTOR": new_weight_factor,
        "MIN_WEIGHT_DIFF": new_min_weight
    })
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

TEAM_NAMES = [t["name"] for t in TEAMS if t["name"].strip()]
TEAM_COLORS = {t["name"]: t["color_hex"] for t in TEAMS}
TEAM_EMOJIS = {t["name"]: COLOR_MAP[t["color"]][1] for t in TEAMS}

# ----------------------------------------------------------------------
# HELPER: Colored team badge
# ----------------------------------------------------------------------
def color_badge(team_name: str) -> str:
    if not team_name or team_name not in TEAM_COLORS:
        return team_name
    color = TEAM_COLORS[team_name]
    return (
        f'<div style="display:inline-block;'
        f'width:12px;height:12px;background:{color};'
        f'border-radius:2px;margin-right:4px;vertical-align:middle;"></div>'
        f'<small>{team_name}</small>'
    )

# ----------------------------------------------------------------------
# CORE LOGIC
# ----------------------------------------------------------------------
def is_compatible(w1, w2):
    return w1["team"] != w2["team"] and not (
        (w1["grade"] == 5 and w2["grade"] in [7,8]) or (w2["grade"] == 5 and w1["grade"] in [7,8])
    )

def max_weight_diff(w): return max(CONFIG["MIN_WEIGHT_DIFF"], w * CONFIG["WEIGHT_DIFF_FACTOR"])

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
                added = True
                break
            if not added: break
    bout_list = []
    for idx, b in enumerate(bouts, 1):
        w1, w2 = (next(w for w in active if w["id"] == i) for i in b)
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
    under = [w for w in active if len(w["matches"]) < CONFIG["MIN_MATCHES"]]
    sugg = []
    for w in under:
        opps = [o for o in active if o != w and o not in w["matches"]]
        opps = [o for o in opps if abs(w["weight"]-o["weight"]) <= min(max_weight_diff(w["weight"]), max_weight_diff(o["weight"])) and abs(w["level"]-o["level"]) <= CONFIG["MAX_LEVEL_DIFF"]]
        if not opps:
            opps = [o for o in active if o != w and o not in w["matches"]]
        for o in sorted(opps, key=lambda o: matchup_score(w, o))[:3]:
            sugg.append({
                "wrestler": w["name"], "team": w["team"], "level": w["level"], "weight": w["weight"],
                "current": len(w["matches"]), "vs": o["name"], "vs_team": o["team"],
                "vs_level": o["level"], "vs_weight": o["weight"], "score": matchup_score(w, o),
                "_w": w, "_o": o
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
    for mat_num in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [m for m in schedules if m["mat"] == mat_num]
        mat_entries.sort(key=lambda x: x["slot"])
        for idx, entry in enumerate(mat_entries, 1):
            entry["mat_bout_num"] = idx
    return schedules

# ----------------------------------------------------------------------
# STREAMLIT in APP
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.title("Wrestling Meet Scheduler")
st.caption("Upload roster to Generate to Edit to Download. **No data stored.**")

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
            w["matches"] = []
        st.session_state.active = [w for w in wrestlers if not w["scratch"]]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
        st.session_state.initialized = True
        st.success("Roster loaded and matchups generated!")
    except Exception as e:
        st.error(f"Error: {e}")

if st.session_state.initialized:
    # ----- SUGGESTIONS -----
    st.subheader("Suggested Matches")
    if st.session_state.suggestions:
        sugg_data = []
        for i, s in enumerate(st.session_state.suggestions):
            sugg_data.append({
                "Add": False,
                "Wrestler": f"{s['wrestler']} ({s['team']})",
                "Lvl": f"{s['level']:.1f}",
                "Wt": f"{s['weight']:.0f}",
                "vs": f"{s['vs']} ({s['vs_team']})",
                "vs_Lvl": f"{s['vs_level']:.1f}",
                "vs_Wt": f"{s['vs_weight']:.0f}",
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
            to_add = [st.session_state.suggestions[sugg_full_df.iloc[row.name]["idx"]] for _, row in edited.iterrows() if row["Add"]]
            for s in to_add:
                w, o = s["_w"], s["_o"]
                if o not in w["matches"]: w["matches"].append(o)
                if w not in o["matches"]: o["matches"].append(w)
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

    # ----- MAT PREVIEWS WITH COLOR BADGES -----
    st.subheader("Mat Previews")
    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        mat_bouts = [m for m in st.session_state.mat_schedules if m["mat"] == mat]
        if not mat_bouts:
            with st.expander(f"**Mat {mat}**", expanded=True):
                st.write("No matches")
            continue

        rows = []
        for m in mat_bouts:
            b = next(x for x in st.session_state.bout_list if x["bout_num"] == m["bout_num"])
            rows.append({
                "Remove": False,
                "Slot": m["mat_bout_num"],
                "Early": "fire" if b["is_early"] else "",
                "W1": f"**{b['w1_name']}**<br>{color_badge(b['w1_team'])}",
                "G/L/W": f"{b['w1_grade']} / {b['w1_level']:.1f} / {b['w1_weight']:.0f}",
                "W2": f"**{b['w2_name']}**<br>{color_badge(b['w2_team'])}",
                "G/L/W 2": f"{b['w2_grade']} / {b['w2_level']:.1f} / {b['w2_weight']:.0f}",
                "Score": round(b["score"], 1),
                "_bout_num": b["bout_num"]
            })

        df_full = pd.DataFrame(rows)
        df_disp = df_full.drop(columns=["_bout_num"])

        with st.expander(f"**Mat {mat}**", expanded=True):
            edited = st.data_editor(
                df_disp,
                column_config={
                    "Remove": st.column_config.CheckboxColumn("Remove"),
                    "Slot": st.column_config.NumberColumn("Slot", disabled=True),
                    "Early": st.column_config.TextColumn("Early"),
                    "W1": st.column_config.TextColumn("Wrestler 1", unsafe_allow_html=True),
                    "W2": st.column_config.TextColumn("Wrestler 2", unsafe_allow_html=True),
                    "G/L/W": st.column_config.TextColumn("G/L/W"),
                    "G/L/W 2": st.column_config.TextColumn("G/L/W 2"),
                    "Score": st.column_config.NumberColumn("Score", disabled=True),
                },
                use_container_width=True,
                hide_index=True,
                key=f"mat_edit_{mat}",
            )

            if st.button(f"Apply Removals – Mat {mat}", key=f"apply_mat_{mat}"):
                to_remove = df_full.loc[edited["Remove"], "_bout_num"].tolist()
                if to_remove:
                    for num in to_remove:
                        b = next(x for x in st.session_state.bout_list if x["bout_num"] == num)
                        b["manual"] = "Removed"
                        w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
                        w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
                        if w2 in w1["matches"]: w1["matches"].remove(w2)
                        if w1 in w2["matches"]: w2["matches"].remove(w1)
                    st.session_state.last_removed = to_remove[0]
                    st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
                    st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
                    st.success(f"Removed {len(to_remove)} match(es)!")
                    st.rerun()

    # ----- UNDO -----
    if st.session_state.last_removed:
        st.markdown("---")
        if st.button("Undo Last Removal", type="primary"):
            b = next(x for x in st.session_state.bout_list if x["bout_num"] == st.session_state.last_removed and x["manual"] == "Removed")
            b["manual"] = ""
            w1 = next(w for w in st.session_state.active if w["id"] == b["w1_id"])
            w2 = next(w for w in st.session_state.active if w["id"] == b["w2_id"])
            if w2 not in w1["matches"]: w1["matches"].append(w2)
            if w1 not in w2["matches"]: w2["matches"].append(w1)
            st.session_state.last_removed = None
            st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
            st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
            st.success("Undo successful!")
            st.rerun()

    # ----- GENERATE MEET + PDF UNDER EXCEL -----
    if st.button("Generate Meet", type="primary"):
        # EXCEL
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            pd.DataFrame(st.session_state.bout_list).to_excel(writer, "Matchups", index=False)
            for m in range(1, CONFIG["NUM_MATS"]+1):
                data = [e for e in st.session_state.mat_schedules if e["mat"] == m]
                if not data:
                    pd.DataFrame([["", "", ""]], columns=["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]).to_excel(writer, f"Mat {m}", index=False)
                    continue
                df = pd.DataFrame(data)[["mat_bout_num","w1","w2"]]; df.columns = ["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]
                df.to_excel(writer, f"Mat {m}", index=False)
                ws = writer.book[f"Mat {m}"]
                fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
                for i, _ in df.iterrows():
                    if next(b for b in st.session_state.bout_list if b["bout_num"] == data[i]["bout_num"])["is_early"]:
                        for c in range(1,4): ws.cell(row=i+2, column=c).fill = fill
        excel_bytes = out.getvalue()

        # PDF
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
                              Paragraph(f'<font color="{TEAM_COLORS.get(b["w1_team"],"#000")}"><b>{b["w1_name"]}</b></font> <i>({b["w1_team"]})</i>', styles["Normal"]),
                              Paragraph(f'<font color="{TEAM_COLORS.get(b["w2_team"],"#000")}"><b>{b["w2_name"]}</b></font> <i>({b["w2_team"]})</i>', styles["Normal"])])
            t = Table(table, colWidths=[0.5*inch, 3*inch, 3*inch])
            s = TableStyle([("GRID",(0,0),(-1,-1),0.5,rl_colors.black), ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
                            ("BACKGROUND",(0,0),(-1,0),rl_colors.lightgrey), ("ALIGN",(0,0),(-1,-1),"LEFT"), ("VALIGN",(0,0),(-1,-1),"MIDDLE")])
            for r, _ in enumerate(table[1:], 1):
                if next(b for b in st.session_state.bout_list if b["bout_num"] == data[r-1]["bout_num"])["is_early"]:
                    s.add("BACKGROUND",(0,r),(-1,r),HexColor("#FFFF99"))
            t.setStyle(s)
            elements += [Paragraph(f"Mat {m}", styles["Title"]), Spacer(1,12), t]
            if m < CONFIG["NUM_MATS"]: elements.append(PageBreak())
        doc.build(elements)
        pdf_bytes = buf.getvalue()

        # DOWNLOADS
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("Download Excel", excel_bytes, "meet_schedule.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col2:
            st.download_button("Download PDF", pdf_bytes, "meet_schedule.pdf", "application/pdf")

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")

