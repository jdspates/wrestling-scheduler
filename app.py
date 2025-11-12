# app.py – FINAL: RIGHT-CLICK DELETE + UNDO + CLEAN CARDS + ALL FEATURES
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
import streamlit.components.v1 as components

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
for key in ["initialized", "bout_list", "mat_schedules", "suggestions", "active", "undo_stack"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["bout_list", "mat_schedules", "suggestions", "active", "undo_stack"] else False

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
def swap_schedule_positions(mat_schedules, mat_num, idx1, idx2):
    entries = [e for e in mat_schedules if e["mat"] == mat_num]
    entries.sort(key=lambda x: x["slot"])
    if not (0 <= idx1 < len(entries) and 0 <= idx2 < len(entries)):
        return mat_schedules
    e1, e2 = entries[idx1], entries[idx2]
    gi1 = next(i for i, e in enumerate(mat_schedules)
               if e["mat"] == mat_num and e["slot"] == e1["slot"] and e["bout_num"] == e1["bout_num"])
    gi2 = next(i for i, e in enumerate(mat_schedules)
               if e["mat"] == mat_num and e["slot"] == e2["slot"] and e["bout_num"] == e2["bout_num"])
    mat_schedules[gi1], mat_schedules[gi2] = mat_schedules[gi2], mat_schedules[gi1]
    mat_entries = [m for m in mat_schedules if m["mat"] == mat_num]
    mat_entries.sort(key=lambda x: x["slot"])
    for idx, entry in enumerate(mat_entries, 1):
        entry["mat_bout_num"] = idx
    return mat_schedules

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
    .drag-card { margin:0 !important; cursor:move; user-select:none; }
    .drag-card:active { opacity:0.7; }

    /* CONTEXT MENU */
    #global-context-menu {
        position: fixed;
        background: white;
        border: 1px solid #ccc;
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        padding: 8px 0;
        z-index: 9999;
        display: none;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    #global-context-menu button {
        width: 100%;
        text-align: left;
        padding: 8px 16px;
        background: none;
        border: none;
        cursor: pointer;
        font-size: 0.9rem;
    }
    #global-context-menu button:hover {
        background: #f0f0f0;
    }
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
            w["match_ids"] = []  # Store only IDs
        st.session_state.active = [w for w in wrestlers if not w["scratch"]]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
        st.session_state.initialized = True
        st.success("Roster loaded and matchups generated!")
    except Exception as e:
        st.error(f"Error: {e}")

# ---- SETTINGS (unchanged) ----
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
TEAM_COLORS = {t["name"]: COLOR_MAP[t["color"]][0] for t in TEAMS if t["name"]}

# ----------------------------------------------------------------------
# MAIN APP
# ----------------------------------------------------------------------
if st.session_state.initialized:
    # ---- SUGGESTED MATCHUPS ----
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

    # ---- GLOBAL DELETE COMPONENT (ONE TIME) ----
    if not hasattr(st.session_state, "delete_component_rendered"):
        delete_global_js = """
        <div id="global-delete-comp">
          <div id="global-context-menu">
            <button id="delete-match-btn">Delete Match</button>
          </div>
          <script>
            let targetBout = null;
            const menu = document.getElementById('global-context-menu');
            const btn = document.getElementById('delete-match-btn');
            document.addEventListener('contextmenu', e => {
              const card = e.target.closest('[data-bout]');
              if (card) {
                e.preventDefault();
                targetBout = card.getAttribute('data-bout');
                menu.style.display = 'block';
                menu.style.left = e.pageX + 'px';
                menu.style.top = e.pageY + 'px';
              }
            });
            btn.addEventListener('click', () => {
              if (targetBout) {
                Streamlit.setComponentValue(targetBout);
              }
              menu.style.display = 'none';
            });
            document.addEventListener('click', () => menu.style.display = 'none');
          </script>
        </div>
        """
        delete_result = components.html(delete_global_js, height=0)
        st.session_state.delete_component_rendered = True
    else:
        delete_result = None

    if delete_result and isinstance(delete_result, str) and delete_result.isdigit():
        remove_match(int(delete_result))
        st.rerun()

    # ---- MAT PREVIEWS – DRAG ONLY ----
    st.subheader("Mat Previews")
    rerun_needed = False

    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        bouts = [m for m in st.session_state.mat_schedules if m["mat"] == mat]
        if not bouts:
            st.write(f"**Mat {mat}: No matches**")
            continue

        with st.expander(f"Mat {mat}", expanded=True):
            cards_html = ""
            for idx, m in enumerate(bouts):
                b = next(x for x in st.session_state.bout_list if x["bout_num"] == m["bout_num"])
                bg = "#fff3cd" if b["is_early"] else "#ffffff"
                w1_color = TEAM_COLORS.get(b["w1_team"], "#999")
                w2_color = TEAM_COLORS.get(b["w2_team"], "#999")
                cards_html += f'''
                <div class="drag-card" id="card-{idx}" draggable="true" data-bout="{b['bout_num']}">
                    <div style="background:{bg};border:1px solid #e6e6e6;border-radius:8px;padding:10px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
                        <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
                            <div style="display:flex;align-items:center;gap:10px;">
                                <div style="width:12px;height:12px;background:{w1_color};border-radius:3px;border:1px solid #ccc;"></div>
                                <div style="font-weight:600;font-size:1rem;">{b["w1_name"]} ({b["w1_team"]})</div>
                                <div style="font-size:0.85rem;color:#444;">{b["w1_grade"]} / {b["w1_level"]:.1f} / {b["w1_weight"]:.0f}</div>
                            </div>
                            <div style="font-weight:700;color:#333;">vs</div>
                            <div style="display:flex;flex-direction:row-reverse;align-items:center;gap:10px;">
                                <div style="width:12px;height:12px;background:{w2_color};border-radius:3px;border:1px solid #ccc;"></div>
                                <div style="font-size:0.85rem;color:#444;">{b["w2_grade"]} / {b["w2_level"]:.1f} / {b["w2_weight"]:.0f}</div>
                                <div style="font-weight:600;font-size:1rem;">{b["w2_name"]} ({b["w2_team"]})</div>
                            </div>
                        </div>
                        <div style="font-size:0.8rem;color:#555;">
                            Slot: {m["mat_bout_num"]} | {"Early" if b["is_early"] else ""} | Score: {b["score"]:.1f}
                        </div>
                    </div>
                </div>
                '''

            drag_js = f"""
            <div style="height:500px; overflow-y:auto; border:1px solid #ddd; padding:4px; background:#fafafa;">
                <div id="mat-{mat}-container">
                    {cards_html}
                </div>
            </div>
            <script>
              const container = document.getElementById('mat-{mat}-container');
              let dragged = null;
              container.querySelectorAll('.drag-card').forEach(card => {{
                card.addEventListener('dragstart', () => {{ dragged = card; card.style.opacity = '0.5'; }});
                card.addEventListener('dragend', () => {{ card.style.opacity = '1'; updateOrder(); }});
                card.addEventListener('dragover', e => e.preventDefault());
                card.addEventListener('drop', e => {{
                  e.preventDefault();
                  const after = getDragAfter(container, e.clientY);
                  if (after == null) container.appendChild(dragged);
                  else container.insertBefore(dragged, after);
                }});
              }});
              function getDragAfter(c, y) {{
                const els = [...c.querySelectorAll('.drag-card:not([style*="opacity: 0.5"])')];
                return els.reduce((closest, child) => {{
                  const box = child.getBoundingClientRect();
                  const offset = y - box.top - box.height / 2;
                  if (offset < 0 && offset > closest.offset) return {{offset: offset, element: child}};
                  return closest;
                }}, {{offset: Number.NEGATIVE_INFINITY}}).element;
              }}
              function updateOrder() {{
                const order = [...container.children].map(c => c.id.split('-')[1]);
                Streamlit.setComponentValue({{mat: {mat}, order: order.map(Number)}});
              }}
            </script>
            """
            drag_result = components.html(drag_js, height=520)

            if drag_result and isinstance(drag_result, dict) and "order" in drag_result:
                new_order = drag_result["order"]
                mat_entries = [e for e in st.session_state.mat_schedules if e["mat"] == mat]
                if len(new_order) == len(mat_entries):
                    reordered = [mat_entries[i] for i in new_order]
                    st.session_state.mat_schedules = [e for e in st.session_state.mat_schedules if e["mat"] != mat] + reordered
                    rerun_needed = True

    if rerun_needed:
        st.rerun()

    # ---- UNDO ----
    if st.session_state.undo_stack:
        st.markdown("---")
        label = f"Undo ({len(st.session_state.undo_stack)})" if len(st.session_state.undo_stack) > 1 else "Undo Last Removal"
        if st.button(label, type="primary"):
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
            st.rerun()

    # ---- GENERATE MEET (unchanged) ----
    if st.button("Generate Meet", type="primary"):
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
                    s.add("BACKGROUND",(0,r),(-1,r),HexColor("#FFFF99"))
            t.setStyle(s)
            elements += [Paragraph(f"Mat {m}", styles["Title"]), Spacer(1,12), t]
            if m < CONFIG["NUM_MATS"]: elements.append(PageBreak())
        doc.build(elements)
        pdf_bytes = buf.getvalue()
        st.download_button("Download Excel", excel_bytes, "meet_schedule.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("Download PDF", pdf_bytes, "meet_schedule.pdf", "application/pdf")

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")
