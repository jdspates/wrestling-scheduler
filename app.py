# app.py - Wrestling Scheduler | Drag-to-Reorder (Pre-1.38 Compatible)
# Compatible with: streamlit, pandas, openpyxl, reportlab==4.0.9

import streamlit as st
import pandas as pd
import io
import random
import json
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak, Spacer
from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from openpyxl.styles import PatternFill

# ----------------------------------------------------------------------
# CONFIG & COLOR MAP
# ----------------------------------------------------------------------
CONFIG_FILE = "config.json"
COLOR_MAP = {
    "red": ("#FF0000", "Red Circle"),
    "blue": ("#0000FF", "Blue Circle"),
    "green": ("#008000", "Green Circle"),
    "yellow": ("#FFD700", "Yellow Circle"),
    "black": ("#000000", "Black Circle"),
    "white": ("#FFFFFF", "White Circle"),
    "purple": ("#800080", "Purple Circle"),
    "orange": ("#FFA500", "Orange Circle")
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
# DRAG-TO-REORDER HELPER
# ----------------------------------------------------------------------
def _reorder_rows_by_selection(df: pd.DataFrame, selected_rows: list[int]) -> pd.DataFrame:
    sel = [i for i in (selected_rows or []) if i < len(df)]
    kept = [i for i in range(len(df)) if i not in sel]
    new_order = sel + kept
    return df.iloc[new_order].reset_index(drop=True)

# ----------------------------------------------------------------------
# SESSION STATE
# ----------------------------------------------------------------------
for key in ["initialized", "bout_list", "mat_schedules", "suggestions", "active", "last_removed"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list", "mat_schedules", "suggestions", "active"] else (False if key == "initialized" else None)

# ----------------------------------------------------------------------
# MEET SETTINGS
# ----------------------------------------------------------------------
st.sidebar.header("Meet Settings")
changed = False
st.sidebar.subheader("Match & Scheduling Rules")
col1, col2 = st.sidebar.columns(2)
with col1:
    new_min = st.number_input("Min Matches", 1, 10, CONFIG["MIN_MATCHES"], key="min_matches")
    new_max = st.number_input("Max Matches", 1, 10, CONFIG["MAX_MATCHES"], key="max_matches")
    new_mats = st.number_input("Number of Mats", 1, 10, CONFIG["NUM_MATS"], key="num_mats")
with col2:
    new_level_diff = st.number_input("Max Level Diff", 0, 5, CONFIG["MAX_LEVEL_DIFF"], key="max_level_diff")
    new_weight_factor = st.slider("Weight % Factor", 0.0, 0.5, CONFIG["WEIGHT_DIFF_FACTOR"], 0.01, format="%.2f", key="weight_factor")
    new_min_weight = st.number_input("Min Weight Diff (lbs)", 0.0, 50.0, CONFIG["MIN_WEIGHT_DIFF"], 0.5, key="min_weight_diff")
if new_min > new_max:
    st.sidebar.error("Min cannot exceed Max!")
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
TEAM_COLORS = {t["name"]: COLOR_MAP[t["color"]][0] for t in TEAMS}
TEAM_EMOJIS = {t["name"]: COLOR_MAP[t["color"]][1] for t in TEAMS}

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
        if not opps: opps = [o for o in active if o != w and o not in w["matches"]]
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
    per_mat = len(valid) // CONFIG["NUM_MATS"]
    extra = len(valid) % CONFIG["NUM_MATS"]
    mats = [valid[i*per_mat + min(i, extra) : (i+1)*per_mat + min(i+1, extra)] for i in range(CONFIG["NUM_MATS"])]
    schedules = []
    last_slot = {}
    for mat_num, mat_bouts in enumerate(mats, 1):
        early, non_early = [b for b in mat_bouts if b["is_early"]], [b for b in mat_bouts if not b["is_early"]]
        first_half_end = (len(mat_bouts) + 1) // 2
        slot = 1
        scheduled = []
        first_half_wrestlers = set()
        if early:
            first = next((b for b in early if last_slot.get(b["w1_id"], -100) < 0 and last_slot.get(b["w2_id"], -100) < 0), None)
            if first:
                early.remove(first)
                scheduled.append((1, first))
                for wid in [first["w1_id"], first["w2_id"]]: last_slot[wid] = 1; first_half_wrestlers.add(wid)
                slot = 2
        while early and len(scheduled) < first_half_end:
            best = max((b for b in early if b["w1_id"] not in first_half_wrestlers and b["w2_id"] not in first_half_wrestlers),
                       key=lambda b: min(slot - last_slot.get(b["w1_id"], -100) - 1, slot - last_slot.get(b["w2_id"], -100) - 1), default=None)
            if not best: break
            early.remove(best)
            scheduled.append((slot, best))
            for wid in [best["w1_id"], best["w2_id"]]: last_slot[wid] = slot; first_half_wrestlers.add(wid)
            slot += 1
        remaining = non_early + early
        while remaining:
            best = max(remaining, key=lambda b: min(slot - last_slot.get(b["w1_id"], -100) - 1, slot - last_slot.get(b["w2_id"], -100) - 1), default=None) or remaining[0]
            remaining.remove(best)
            scheduled.append((slot, best))
            for wid in [best["w1_id"], best["w2_id"]]: last_slot[wid] = slot
            slot += 1
        for s, b in scheduled:
            schedules.append({
                "mat": mat_num, "slot": s, "bout_num": b["bout_num"],
                "w1": f"{b['w1_name']} ({b['w1_team']})",
                "w2": f"{b['w2_name']} ({b['w2_team']})",
                "w1_team": b["w1_team"], "w2_team": b["w2_team"], "is_early": b["is_early"]
            })
    for mat in range(1, CONFIG["NUM_MATS"]+1):
        entries = sorted([e for e in schedules if e["mat"] == mat], key=lambda x: x["slot"])
        for i, e in enumerate(entries, 1): e["mat_bout_num"] = i
    return schedules

# ----------------------------------------------------------------------
# STREAMLIT APP
# ----------------------------------------------------------------------
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.title("Wrestling Meet Scheduler")
st.caption("Upload roster → Generate → Edit → Download. **No data stored.**")

uploaded = st.file_uploader("Upload `roster.csv`", type="csv")
if uploaded and not st.session_state.initialized:
    try:
        df = pd.read_csv(uploaded)
        req = ["id","name","team","grade","level","weight","early_matches","scratch"]
        if not all(c in df.columns for c in req):
            st.error("Missing: " + ", ".join(req)); st.stop()
        wrestlers = df.to_dict("records")
        for w in wrestlers:
            w.update({k: int(w[k]) if k in ["id","grade"] else float(w[k]) if k in ["level","weight"] else
                      (str(w[k]).strip().upper() == "Y" or w[k] in [1,True]) for k in ["early_matches","scratch"]})
            w["early"] = w.pop("early_matches"); w["scratch"] = w.pop("scratch"); w["matches"] = []
        st.session_state.active = [w for w in wrestlers if not w["scratch"]]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
        st.session_state.initialized = True
        st.success("Roster loaded!")
    except Exception as e:
        st.error(f"Error: {e}")

if st.session_state.initialized:
    # ----- SUGGESTIONS -----
    st.subheader("Suggested Matches")
    if st.session_state.suggestions:
        data = [{
            "Add": False,
            "Wrestler": f"{s['wrestler']} ({s['team']})",
            "Lvl": f"{s['level']:.1f}",
            "Wt": f"{s['weight']:.0f}",
            "vs": f"{s['vs']} ({s['vs_team']})",
            "vs_Lvl": f"{s['vs_level']:.1f}",
            "vs_Wt": f"{s['vs_weight']:.0f}",
            "Score": f"{s['score']:.1f}",
            "idx": i
        } for i, s in enumerate(st.session_state.suggestions)]
        full_df = pd.DataFrame(data)
        display_df = full_df.drop(columns=["idx"])
        edited = st.data_editor(
            display_df,
            column_config={
                "Add": st.column_config.CheckboxColumn("Add"),
                "Wrestler": st.column_config.TextColumn("Wrestler"),
                "Lvl": st.column_config.NumberColumn("Lvl"),
                "Wt": st.column_config.NumberColumn("Wt"),
                "vs": st.column_config.TextColumn("vs"),
                "vs_Lvl": st.column_config.NumberColumn("vs_Lvl"),
                "vs_Wt": st.column_config.NumberColumn("vs_Wt"),
                "Score": st.column_config.NumberColumn("Score")
            },
            use_container_width=True,
            hide_index=True,
            key="sugg_editor"
        )
        if st.button("Add Selected"):
            to_add = [st.session_state.suggestions[full_df.iloc[r.name]["idx"]] for _, r in edited.iterrows() if r["Add"]]
            for s in to_add:
                w, o = s["_w"], s["_o"]
                if o not in w["matches"]: w["matches"].append(o)
                if w not in o["matches"]: o["matches"].append(w)
                st.session_state.bout_list.append({
                    "bout_num": len(st.session_state.bout_list) + 1,
                    "w1_id": w["id"], "w1_name": w["name"], "w1_team": w["team"],
                    "w1_level": w["level"], "w1_weight": w["weight"], "w1_grade": w["grade"], "w1_early": w["early"],
                    "w2_id": o["id"], "w2_name": o["name"], "w2_team": o["team"],
                    "w2_level": o["level"], "w2_weight": o["weight"], "w2_grade": o["grade"], "w2_early": o["early"],
                    "score": s["score"],
                    "avg_weight": (w["weight"] + o["weight"]) / 2,
                    "is_early": w["early"] or o["early"],
                    "manual": "Yes"
                })
            st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
            st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
            st.success("Matches added!")
            st.rerun()
    else:
        st.info("All wrestlers have enough matches.")

    # ----- MAT PREVIEWS WITH DRAG-TO-REORDER (PRE-1.38: Checkbox Selection) -----
    st.subheader("Mat Previews")
    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        bouts = [m for m in st.session_state.mat_schedules if m["mat"] == mat]
        if not bouts:
            st.write(f"**Mat {mat}: No matches**")
            continue

        rows = []
        for m in bouts:
            b = next(x for x in st.session_state.bout_list if x["bout_num"] == m["bout_num"])
            rows.append({
                "Remove": False,
                "Slot": m["mat_bout_num"],
                "Early?": "Fire" if b["is_early"] else "",
                "Wrestler 1": f"{TEAM_EMOJIS.get(b['w1_team'], 'Circle')} {b['w1_name']} ({b['w1_team']})",
                "G/L/W": f"{b['w1_grade']} / {b['w1_level']:.1f} / {b['w1_weight']:.0f}",
                "Wrestler 2": f"{TEAM_EMOJIS.get(b['w2_team'], 'Circle')} {b['w2_name']} ({b['w2_team']})",
                "G/L/W 2": f"{b['w2_grade']} / {b['w2_level']:.1f} / {b['w2_weight']:.0f}",
                "Score": f"{b['score']:.1f}",
                "bout_num": b["bout_num"]
            })
        full_df = pd.DataFrame(rows)
        disp_df = full_df.drop(columns=["bout_num"])

        # === WORKAROUND: Add Temporary "Select" Column for Drag ===
        select_df = disp_df.copy()
        select_df.insert(0, "Select", False)  # Temporary column for selections

        editor_key = f"mat_editor_{mat}"
        with st.expander(f"Mat {mat} – Check rows, then drag to reorder", expanded=True):
            edited = st.data_editor(
                select_df,
                column_config={
                    "Select": st.column_config.CheckboxColumn("Select", default=False, required=False),
                    "Remove": st.column_config.CheckboxColumn("Remove", default=False),
                    "Slot": st.column_config.NumberColumn("Slot", disabled=True),
                    "Early?": st.column_config.TextColumn("Early?"),
                    "Wrestler 1": st.column_config.TextColumn("Wrestler 1"),
                    "G/L/W": st.column_config.TextColumn("G/L/W"),
                    "Wrestler 2": st.column_config.TextColumn("Wrestler 2"),
                    "G/L/W 2": st.column_config.TextColumn("G/L/W 2"),
                    "Score": st.column_config.NumberColumn("Score", disabled=True),
                },
                use_container_width=True,
                hide_index=True,
                key=editor_key,
                # No selection_mode/on_select – uses checkbox workaround
            )

        # === DRAG REORDER LOGIC (From Checkbox Selections) ===
        selected_indices = edited[edited["Select"]].index.tolist()
        if selected_indices:
            # Reorder based on selected rows (move to top)
            reordered_full = _reorder_rows_by_selection(full_df, selected_indices)
            new_schedule = []
            for idx, row in reordered_full.iterrows():
                sched_entry = next(e for e in st.session_state.mat_schedules
                                   if e["mat"] == mat and e["bout_num"] == row["bout_num"])
                sched_entry["mat_bout_num"] = idx + 1
                new_schedule.append(sched_entry)
            st.session_state.mat_schedules = [e for e in st.session_state.mat_schedules if e["mat"] != mat] + new_schedule
            st.success(f"Mat {mat} order updated! (Clear 'Select' checkboxes to reset.)")
            st.rerun()

        # === REMOVE BUTTON ===
        if st.button(f"Apply Removals – Mat {mat}", key=f"rem_mat_{mat}"):
            # Use edited["Remove"] (ignores "Select" column)
            rem_indices = edited[edited["Remove"]].index.tolist()
            rem_bouts = [full_df.iloc[i]["bout_num"] for i in rem_indices]
            if rem_bouts:
                for n in rem_bouts:
                    b = next(x for x in st.session_state.bout_list if x["bout_num"] == n)
                    b["manual"] = "Removed"
                    for p in [(b["w1_id"], b["w2_id"]), (b["w2_id"], b["w1_id"])]:
                        w1 = next(w for w in st.session_state.active if w["id"] == p[0])
                        w2 = next(w for w in st.session_state.active if w["id"] == p[1])
                        if w2 in w1["matches"]:
                            w1["matches"].remove(w2)
                st.session_state.last_removed = rem_bouts[0]
                st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
                st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
                st.success(f"Removed {len(rem_bouts)} match(es)!")
                st.rerun()

    # ----- UNDO -----
    if st.session_state.last_removed:
        st.markdown("---")
        if st.button("Undo Last Removal", type="primary"):
            b = next(x for x in st.session_state.bout_list if x["bout_num"] == st.session_state.last_removed and x["manual"] == "Removed")
            b["manual"] = ""
            for p in [(b["w1_id"], b["w2_id"]), (b["w2_id"], b["w1_id"])]:
                w1 = next(w for w in st.session_state.active if w["id"] == p[0])
                w2 = next(w for w in st.session_state.active if w["id"] == p[1])
                if w2 not in w1["matches"]: w1["matches"].append(w2)
            st.session_state.last_removed = None
            st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list)
            st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
            st.success("Undo successful!")
            st.rerun()

    # ----- GENERATE MEET -----
    if st.button("Generate Meet", type="primary"):
        # Excel
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            pd.DataFrame(st.session_state.bout_list).to_excel(writer, "Matchups", index=False)
            for m in range(1, CONFIG["NUM_MATS"]+1):
                data = [e for e in st.session_state.mat_schedules if e["mat"] == m]
                if not data:
                    pd.DataFrame([["", "", ""]], columns=["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]).to_excel(writer, f"Mat {m}", index=False)
                    continue
                df = pd.DataFrame(data)[["mat_bout_num","w1","w2"]]
                df.columns = ["#","Wrestler 1 (Team)","Wrestler 2 (Team)"]
                df.to_excel(writer, f"Mat {m}", index=False)
                ws = writer.book[f"Mat {m}"]
                fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
                for i, _ in df.iterrows():
                    if next(b for b in st.session_state.bout_list if b["bout_num"] == data[i]["bout_num"])["is_early"]:
                        for c in range(1,4): ws.cell(row=i+2, column=c).fill = fill
        excel_bytes = out.getvalue()

        # PDF
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()
        for m in range(1, CONFIG["NUM_MATS"]+1):
            data = [e for e in st.session_state.mat_schedules if e["mat"] == m]
            if not data:
                elements.append(Paragraph(f"Mat {m} - No matches", styles["Title"]))
                elements.append(PageBreak())
                continue
            table = [["#","Wrestler 1","Wrestler 2"]]
            for e in data:
                b = next(x for x in st.session_state.bout_list if x["bout_num"] == e["bout_num"])
                table.append([
                    e["mat_bout_num"],
                    Paragraph(f'<font color="{TEAM_COLORS.get(b["w1_team"],"#000")}"><b>{b["w1_name"]}</b></font> ({b["w1_team"]})', styles["Normal"]),
                    Paragraph(f'<font color="{TEAM_COLORS.get(b["w2_team"],"#000")}"><b>{b["w2_name"]}</b></font> ({b["w2_team"]})', styles["Normal"])
                ])
            t = Table(table, colWidths=[0.5*inch, 3*inch, 3*inch])
            s = TableStyle([
                ("GRID",(0,0),(-1,-1),0.5,rl_colors.black),
                ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
                ("BACKGROUND",(0,0),(-1,0),rl_colors.lightgrey),
                ("ALIGN",(0,0),(-1,-1),"LEFT"),
                ("VALIGN",(0,0),(-1,-1),"MIDDLE")
            ])
            for r, _ in enumerate(table[1:], 1):
                if next(b for b in st.session_state.bout_list if b["bout_num"] == data[r-1]["bout_num"])["is_early"]:
                    s.add("BACKGROUND",(0,r),(-1,r),HexColor("#FFFF99"))
            t.setStyle(s)
            elements += [Paragraph(f"Mat {m}", styles["Title"]), Spacer(1,12), t]
            if m < CONFIG["NUM_MATS"]: elements.append(PageBreak())
        doc.build(elements)
        pdf_bytes = buf.getvalue()

        # Download Buttons
        st.download_button("Download Excel", excel_bytes, "meet_schedule.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("Download PDF", pdf_bytes, "meet_schedule.pdf", "application/pdf")

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")
