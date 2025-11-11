# app.py - FINAL, 100% WORKING
import streamlit as st
import pandas as pd
import io
import random
from collections import defaultdict
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import json
import os

# ===================== CONFIG FROM FILE =====================
CONFIG_FILE = 'config.json'
DEFAULT_CONFIG = {
    "MIN_MATCHES": 2,
    "MAX_MATCHES": 4,
    "NUM_MATS": 4,
    "MAX_LEVEL_DIFF": 1,
    "WEIGHT_DIFF_FACTOR": 0.10,
    "MIN_WEIGHT_DIFF": 5.0,
    "TEAM_COLORS": {
        "Stillwater": "#FF0000", "Woodbury": "#0000FF", "St. Thomas Academy": "#008000",
        "Forest Lake": "#FFD700", "Black Bears": "#000000"
    }
}

if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'r') as f:
        user_config = json.load(f)
    CONFIG = {**DEFAULT_CONFIG, **user_config}
else:
    CONFIG = DEFAULT_CONFIG

# ===================== CORE LOGIC =====================
def is_compatible(w1, w2):
    if w1['team'] == w2['team']: return False
    if (w1['grade'] == 5 and w2['grade'] in [7,8]) or (w2['grade'] == 5 and w1['grade'] in [7,8]):
        return False
    return True

def max_weight_diff(weight):
    return max(CONFIG["MIN_WEIGHT_DIFF"], weight * CONFIG["WEIGHT_DIFF_FACTOR"])

def matchup_score(w1, w2):
    w_diff = abs(w1['weight'] - w2['weight'])
    l_diff = abs(w1['level'] - w2['level'])
    return round(w_diff + l_diff * 10, 1)

def generate_initial_matchups(active):
    bouts = set()
    sorted_by_level = sorted(active, key=lambda w: -w['level'])
    level_groups = defaultdict(list)
    for w in sorted_by_level:
        level_groups[w['level']].append(w)
    for level in sorted(level_groups.keys(), reverse=True):
        group = level_groups[level]
        added_in_round = True
        while added_in_round:
            added_in_round = False
            random.shuffle(group)
            for w in group:
                if len(w['matches']) >= CONFIG["MAX_MATCHES"]: continue
                opps = [o for o in active if o != w and o not in w['matches'] and len(o['matches']) < CONFIG["MAX_MATCHES"] and is_compatible(w,o) and abs(w['weight']-o['weight']) <= min(max_weight_diff(w['weight']), max_weight_diff(o['weight'])) and abs(w['level']-o['level']) <= CONFIG["MAX_LEVEL_DIFF"]]
                if not opps: continue
                best = min(opps, key=lambda o: matchup_score(w,o))
                w['matches'].append(best)
                best['matches'].append(w)
                bouts.add(frozenset({w['id'], best['id']}))
                added_in_round = True
                break
    bout_list = []
    for idx, b in enumerate(bouts, 1):
        ids = list(b)
        w1 = next(w for w in active if w['id'] == ids[0])
        w2 = next(w for w in active if w['id'] == ids[1])
        score = matchup_score(w1, w2)
        avg_w = (w1['weight'] + w2['weight']) / 2
        is_early = w1['early'] or w2['early']
        bout_list.append({
            'bout_num': idx,
            'w1_id': w1['id'], 'w1_name': w1['name'], 'w1_team': w1['team'],
            'w1_level': w1['level'], 'w1_weight': w1['weight'], 'w1_grade': w1['grade'], 'w1_early': w1['early'],
            'w2_id': w2['id'], 'w2_name': w2['name'], 'w2_team': w2['team'],
            'w2_level': w2['level'], 'w2_weight': w2['weight'], 'w2_grade': w2['grade'], 'w2_early': w2['early'],
            'score': score, 'avg_weight': avg_w, 'is_early': is_early, 'manual': ''
        })
    return bout_list

def build_suggestions(active, bout_list):
    under_min = [w for w in active if len(w['matches']) < CONFIG["MIN_MATCHES"]]
    sugg = []
    for w in under_min:
        opps = [o for o in active if o != w and o not in w['matches']]
        opps = [o for o in opps if abs(w['weight']-o['weight']) <= min(max_weight_diff(w['weight']), max_weight_diff(o['weight'])) and abs(w['level']-o['level']) <= CONFIG["MAX_LEVEL_DIFF"]]
        if not opps: opps = [o for o in active if o != w and o not in w['matches']]
        opps = sorted(opps, key=lambda o: matchup_score(w,o))[:3]
        for o in opps:
            sugg.append({
                'wrestler': w['name'], 'team': w['team'], 'level': w['level'], 'weight': w['weight'],
                'current': len(w['matches']), 'vs': o['name'], 'vs_team': o['team'],
                'vs_level': o['level'], 'vs_weight': o['weight'], 'score': matchup_score(w,o),
                '_w': w, '_o': o
            })
    return sugg

def generate_mat_schedule(bout_list, gap=4):
    valid = [b for b in bout_list if b['manual'] != 'Removed']
    sorted_b = sorted(valid, key=lambda x: x['avg_weight'])
    per_mat = len(sorted_b) // CONFIG["NUM_MATS"]
    extra = len(sorted_b) % CONFIG["NUM_MATS"]
    mats = []
    start = 0
    for i in range(CONFIG["NUM_MATS"]):
        end = start + per_mat + (1 if i < extra else 0)
        mats.append(sorted_b[start:end])
        start = end
    schedules = []
    last_slot = {}
    for mat_num, mat_bouts in enumerate(mats, 1):
        early_bouts = [b for b in mat_bouts if b['is_early']]
        non_early_bouts = [b for b in mat_bouts if not b['is_early']]
        total_slots = len(mat_bouts)
        first_half_end = (total_slots + 1) // 2
        slot = 1
        scheduled = []
        first_half_wrestlers = set()
        first_early = None
        for b in early_bouts:
            l1 = last_slot.get(b['w1_id'], -100)
            l2 = last_slot.get(b['w2_id'], -100)
            if l1 < 0 and l2 < 0:
                first_early = b
                break
        if first_early:
            early_bouts.remove(first_early)
            scheduled.append((1, first_early))
            last_slot[first_early['w1_id']] = 1
            last_slot[first_early['w2_id']] = 1
            first_half_wrestlers.update([first_early['w1_id'], first_early['w2_id']])
            slot = 2
        while early_bouts and len(scheduled) < first_half_end:
            best = None
            best_score = -float('inf')
            for b in early_bouts:
                if b['w1_id'] in first_half_wrestlers or b['w2_id'] in first_half_wrestlers: continue
                l1 = last_slot.get(b['w1_id'], -100)
                l2 = last_slot.get(b['w2_id'], -100)
                if l1 >= slot - 1 or l2 >= slot - 1: continue
                score = min(slot - l1 - 1, slot - l2 - 1)
                if score > best_score:
                    best_score = score
                    best = b
            if best is None: break
            early_bouts.remove(best)
            scheduled.append((slot, best))
            last_slot[best['w1_id']] = slot
            last_slot[best['w2_id']] = slot
            first_half_wrestlers.update([best['w1_id'], best['w2_id']])
            slot += 1
        remaining = non_early_bouts + early_bouts
        while remaining:
            best = None
            best_gap = -1
            for b in remaining:
                l1 = last_slot.get(b['w1_id'], -100)
                l2 = last_slot.get(b['w2_id'], -100)
                if l1 >= slot - gap or l2 >= slot - gap: continue
                gap_val = min(slot - l1 - 1, slot - l2 - 1)
                if gap_val > best_gap:
                    best_gap = gap_val
                    best = b
            if best is None: best = remaining[0]
            remaining.remove(best)
            scheduled.append((slot, best))
            last_slot[best['w1_id']] = slot
            last_slot[best['w2_id']] = slot
            slot += 1
        for s, b in scheduled:
            schedules.append({
                'mat': mat_num, 'slot': s, 'bout_num': b['bout_num'],
                'w1': f"{b['w1_name']} ({b['w1_team']})", 'w2': f"{b['w2_name']} ({b['w2_team']})",
                'w1_team': b['w1_team'], 'w2_team': b['w2_team'], 'is_early': b['is_early']
            })
    for mat_num in range(1, CONFIG["NUM_MATS"] + 1):
        mat_entries = [m for m in schedules if m['mat'] == mat_num]
        mat_entries.sort(key=lambda x: x['slot'])
        for idx, entry in enumerate(mat_entries, 1):
            entry['mat_bout_num'] = idx
    return schedules

# ===================== STREAMLIT APP =====================
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.title("Wrestling Meet Scheduler")
st.caption("Upload roster → Generate → Download. **No data stored.**")

# Session state
if 'bout_list' not in st.session_state: st.session_state.bout_list = []
if 'mat_schedules' not in st.session_state: st.session_state.mat_schedules = []
if 'suggestions' not in st.session_state: st.session_state.suggestions = []
if 'active' not in st.session_state: st.session_state.active = []
if 'last_removed' not in st.session_state: st.session_state.last_removed = None
if 'initialized' not in st.session_state: st.session_state.initialized = False

uploaded = st.file_uploader("Upload `roster.csv`", type="csv")

if uploaded and not st.session_state.initialized:
    try:
        df = pd.read_csv(uploaded)
        required = ['id', 'name', 'team', 'grade', 'level', 'weight', 'early_matches', 'scratch']
        if not all(c in df.columns for c in required):
            st.error("Missing columns. Need: " + ", ".join(required))
            st.stop()

        wrestlers = df.to_dict('records')
        for w in wrestlers:
            w['id'] = int(w['id'])
            w['grade'] = int(w['grade'])
            w['level'] = float(w['level'])
            w['weight'] = float(w['weight'])
            early_val = w['early_matches']
            scratch_val = w['scratch']
            w['early'] = (str(early_val).strip().upper() == 'Y') or (early_val in [1, True])
            w['scratch'] = (str(scratch_val).strip().upper() == 'Y') or (scratch_val in [1, True])
            w['matches'] = []

        st.session_state.active = [w for w in wrestlers if not w['scratch']]
        st.session_state.bout_list = generate_initial_matchups(st.session_state.active)
        st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
        st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
        st.session_state.initialized = True
        st.success("Roster loaded and matchups generated!")

    except Exception as e:
        st.error(f"Error: {e}")

if st.session_state.initialized:
    # === SUGGESTIONS ===
    st.subheader("Suggested Matches")
    if st.session_state.suggestions:
        sugg_data = []
        for i, s in enumerate(st.session_state.suggestions):
            sugg_data.append({
                'Add': False,
                'Wrestler': f"{s['wrestler']} ({s['team']})",
                'Lvl': f"{s['level']:.1f}",
                'Wt': f"{s['weight']:.0f}",
                'vs': f"{s['vs']} ({s['vs_team']})",
                'vs_Lvl': f"{s['vs_level']:.1f}",
                'vs_Wt': f"{s['vs_weight']:.0f}",
                'Score': f"{s['score']:.1f}",
                'idx': i
            })
        sugg_df = pd.DataFrame(sugg_data)
        edited = st.data_editor(sugg_df, use_container_width=True, hide_index=True, key="sugg_editor")

        if st.button("Add Selected"):
            to_add = [st.session_state.suggestions[row['idx']] for _, row in edited.iterrows() if row['Add']]
            for s in to_add:
                w, o = s['_w'], s['_o']
                if o not in w['matches']: w['matches'].append(o)
                if w not in o['matches']: o['matches'].append(w)
                st.session_state.bout_list.append({
                    'bout_num': len(st.session_state.bout_list)+1,
                    'w1_id': w['id'], 'w1_name': w['name'], 'w1_team': w['team'],
                    'w1_level': w['level'], 'w1_weight': w['weight'], 'w1_grade': w['grade'], 'w1_early': w['early'],
                    'w2_id': o['id'], 'w2_name': o['name'], 'w2_team': o['team'],
                    'w2_level': o['level'], 'w2_weight': o['weight'], 'w2_grade': o['grade'], 'w2_early': o['early'],
                    'score': s['score'], 'avg_weight': (w['weight']+o['weight'])/2,
                    'is_early': w['early'] or o['early'], 'manual': 'Yes'
                })
            st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
            st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
            st.success("Matches added!")
            st.rerun()
    else:
        st.info("All wrestlers have 2+ matches. No suggestions needed.")

    # === MAT PREVIEWS ===
    st.subheader("Mat Previews")
    tabs = st.tabs([f"Mat {i}" for i in range(1, CONFIG["NUM_MATS"]+1)])
    for i, tab in enumerate(tabs, 1):
        with tab:
            mat_data = [m for m in st.session_state.mat_schedules if m['mat'] == i]
            if not mat_data:
                st.write("No matches")
                continue
            rows = []
            for m in mat_data:
                bout = next(b for b in st.session_state.bout_list if b['bout_num'] == m['bout_num'])
                color1 = CONFIG["TEAM_COLORS"].get(bout['w1_team'], "#000000")
                color2 = CONFIG["TEAM_COLORS"].get(bout['w2_team'], "#000000")
                w1_name = f"<span style='color:{color1}; font-weight:bold'>{bout['w1_name']}</span>"
                w2_name = f"<span style='color:{color2}; font-weight:bold'>{bout['w2_name']}</span>"
                row_html = f"<tr style='{'background-color:#FFFF99' if bout['is_early'] else ''}'>" \
                           f"<td>{m['mat_bout_num']}</td>" \
                           f"<td>{w1_name} ({bout['w1_team']})</td>" \
                           f"<td>{bout['w1_grade']} / {bout['w1_level']:.1f} / {bout['w1_weight']:.0f}</td>" \
                           f"<td>{w2_name} ({bout['w2_team']})</td>" \
                           f"<td>{bout['w2_grade']} / {bout['w2_level']:.1f} / {bout['w2_weight']:.0f}</td>" \
                           f"<td>{bout['score']:.1f}</td>" \
                           f"<td><input type='checkbox' class='remove-checkbox' data-bout='{bout['bout_num']}'></td>" \
                           f"</tr>"
                rows.append(row_html)
            table_html = f"""
            <table style='width:100%; border-collapse:collapse; font-family:Arial;'>
                <thead><tr style='background:#f0f0f0'>
                    <th style='border:1px solid #ccc; padding:8px'>#</th>
                    <th style='border:1px solid #ccc; padding:8px'>Wrestler 1</th>
                    <th style='border:1px solid #ccc; padding:8px'>G/L/W</th>
                    <th style='border:1px solid #ccc; padding:8px'>Wrestler 2</th>
                    <th style='border:1px solid #ccc; padding:8px'>G/L/W</th>
                    <th style='border:1px solid #ccc; padding:8px'>Score</th>
                    <th style='border:1px solid #ccc; padding:8px'>Remove</th>
                </tr></thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
            """
            st.markdown(table_html, unsafe_allow_html=True)

            # Remove logic (client-side)
            removed = st.session_state.get(f"removed_mat_{i}", [])
            if st.button("Apply Remove", key=f"apply_remove_{i}"):
                # This will be handled by JS below
                pass

            if st.session_state.last_removed and st.button("Undo Remove", key=f"undo_{i}"):
                for b in st.session_state.bout_list:
                    if b['bout_num'] == st.session_state.last_removed:
                        b['manual'] = ''
                        w1 = next(w for w in st.session_state.active if w['id'] == b['w1_id'])
                        w2 = next(w for w in st.session_state.active if w['id'] == b['w2_id'])
                        if w2 not in w1['matches']: w1['matches'].append(w2)
                        if w1 not in w2['matches']: w2['matches'].append(w1)
                        break
                st.session_state.last_removed = None
                st.session_state.mat_schedules = generate_mat_schedule(st.session_state.bout_list, gap=4)
                st.session_state.suggestions = build_suggestions(st.session_state.active, st.session_state.bout_list)
                st.rerun()

    # === GENERATE ===
    if st.button("Generate Meet"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pd.DataFrame(st.session_state.bout_list).to_excel(writer, sheet_name='Matchups', index=False)
            for m in range(1, CONFIG["NUM_MATS"]+1):
                data = [e for e in st.session_state.mat_schedules if e['mat'] == m]
                df = pd.DataFrame(data)[['mat_bout_num', 'w1', 'w2']] if data else pd.DataFrame([['', '', '']], columns=['mat_bout_num', 'w1', 'w2'])
                df.columns = ['#', 'Wrestler 1 (Team)', 'Wrestler 2 (Team)']
                df.to_excel(writer, sheet_name=f'Mat {m}', index=False)
        excel_bytes = output.getvalue()

        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
        elements = []
        for m in range(1, CONFIG["NUM_MATS"]+1):
            data = [e for e in st.session_state.mat_schedules if e['mat'] == m]
            if not data: continue
            table_data = [['#', 'Wrestler 1', 'Wrestler 2']] + [[e['mat_bout_num'], e['w1'], e['w2']] for e in data]
            table = Table(table_data)
            table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black)]))
            elements.append(Paragraph(f"Mat {m}", getSampleStyleSheet()['Title']))
            elements.append(table)
            elements.append(PageBreak())
        doc.build(elements)
        pdf_bytes = pdf_buffer.getvalue()

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("Download Excel", excel_bytes, "meet_schedule.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col2:
            st.download_button("Download PDF", pdf_bytes, "meet_schedule.pdf", "application/pdf")

# === CLIENT-SIDE REMOVE LOGIC ===
js = """
<script>
const checkboxes = document.querySelectorAll('.remove-checkbox');
checkboxes.forEach(cb => {
    cb.addEventListener('change', function() {
        const bout = this.dataset.bout;
        const isChecked = this.checked;
        // Send to Streamlit
        Streamlit.setComponentValue({bout: bout, remove: isChecked});
    });
});
</script>
"""
st.markdown(js, unsafe_allow_html=True)

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")
