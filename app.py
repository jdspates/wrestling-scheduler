# app.py
import streamlit as st
import pandas as pd
import io
import json
import csv
from collections import defaultdict
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

# ===================== CONFIG =====================
CONFIG = {
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

# ===================== CORE LOGIC =====================
def is_compatible(w1, w2):
    if w1['team'] == w2['team']: return False
    if (w1['grade'] == 5 and w2['grade'] in [7,8]) or (w2['grade'] == 5 and w1['grade'] in [7,8]):
        return False
    return True

def max_weight_diff(w): return max(CONFIG["MIN_WEIGHT_DIFF"], w * CONFIG["WEIGHT_DIFF_FACTOR"])

def matchup_score(w1, w2):
    return round(abs(w1['weight'] - w2['weight']) + abs(w1['level'] - w2['level']) * 10, 1)

def generate_initial_matchups(active):
    bouts = set()
    sorted_w = sorted(active, key=lambda x: -x['level'])
    groups = defaultdict(list)
    for w in sorted_w: groups[w['level']].append(w)
    for level in sorted(groups.keys(), reverse=True):
        group = groups[level]
        added = True
        while added:
            added = False
            random.shuffle(group)
            for w in group:
                if len(w['matches']) >= CONFIG["MAX_MATCHES"]: continue
                opps = [o for o in active if o != w and o not in w['matches'] and len(o['matches']) < CONFIG["MAX_MATCHES"]
                opps = [o for o in opps if is_compatible(w,o) and
                        abs(w['weight']-o['weight']) <= min(max_weight_diff(w['weight']), max_weight_diff(o['weight'])) and
                        abs(w['level']-o['level']) <= CONFIG["MAX_LEVEL_DIFF"]]
                if not opps:
                    opps = [o for o in active if o != w and o not in w['matches']]
                if not opps: continue
                best = min(opps, key=lambda o: matchup_score(w,o))
                w['matches'].append(best)
                best['matches'].append(w)
                bouts.add(frozenset({w['id'], best['id']}))
                added = True
                break
    bout_list = []
    for idx, b in enumerate(bouts, 1):
        ids = list(b)
        w1 = next(w for w in active if w['id'] == ids[0])
        w2 = next(w for w in active if w['id'] == ids[1])
        bout_list.append({
            'bout_num': idx,
            'w1_id': w1['id'], 'w1_name': w1['name'], 'w1_team': w1['team'],
            'w1_level': w1['level'], 'w1_weight': w1['weight'], 'w1_grade': w1['grade'], 'w1_early': w1['early'],
            'w2_id': w2['id'], 'w2_name': w2['name'], 'w2_team': w2['team'],
            'w2_level': w2['level'], 'w2_weight': w2['weight'], 'w2_grade': w2['grade'], 'w2_early': w2['early'],
            'score': matchup_score(w1,w2), 'avg_weight': (w1['weight']+w2['weight'])/2,
            'is_early': w1['early'] or w2['early'], 'manual': ''
        })
    return bout_list

def build_suggestions(active, bout_list):
    under = [w for w in active if len(w['matches']) < CONFIG["MIN_MATCHES"]]
    sugg = []
    for w in under:
        opps = [o for o in active if o != w and o not in w['matches']]
        opps = [o for o in opps if abs(w['weight']-o['weight']) <= min(max_weight_diff(w['weight']), max_weight_diff(o['weight'])) and
                abs(w['level']-o['level']) <= CONFIG["MAX_LEVEL_DIFF"]]
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

def generate_mat_schedule(bout_list, gap):
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
        early = [b for b in mat_bouts if b['is_early']]
        normal = [b for b in mat_bouts if not b['is_early']]
        slot = 1
        scheduled = []
        # Early in first half
        half = (len(mat_bouts) + 1) // 2
        used = set()
        first = next((b for b in early if b['w1_id'] not in used and b['w2_id'] not in used), None)
        if first:
            early.remove(first)
            scheduled.append((1, first))
            last_slot[first['w1_id']] = 1
            last_slot[first['w2_id']] = 1
            used.update([first['w1_id'], first['w2_id']])
            slot = 2
        while early and len(scheduled) < half:
            best = None
            best_gap = -1
            for b in early:
                if b['w1_id'] in used or b['w2_id'] in used: continue
                g1 = slot - last_slot.get(b['w1_id'], -100) - 1
                g2 = slot - last_slot.get(b['w2_id'], -100) - 1
                if g1 < 0 or g2 < 0: continue
                gap = min(g1, g2)
                if gap > best_gap:
                    best_gap = gap
                    best = b
            if not best: break
            early.remove(best)
            scheduled.append((slot, best))
            last_slot[best['w1_id']] = slot
            last_slot[best['w2_id']] = slot
            used.update([best['w1_id'], best['w2_id']])
            slot += 1
        remaining = normal + early
        while remaining:
            best = None
            best_gap = -1
            for b in remaining:
                g1 = slot - last_slot.get(b['w1_id'], -100) - 1
                g2 = slot - last_slot.get(b['w2_id'], -100) - 1
                if g1 < gap or g2 < gap: continue
                gap_val = min(g1, g2)
                if gap_val > best_gap:
                    best_gap = gap_val
                    best = b
            if not best: best = remaining[0]
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
    for m in range(1, CONFIG["NUM_MATS"]+1):
        entries = [e for e in schedules if e['mat'] == m]
        entries.sort(key=lambda x: x['slot'])
        for i, e in enumerate(entries, 1): e['mat_bout_num'] = i
    return schedules

# ===================== STREAMLIT APP =====================
st.set_page_config(page_title="Wrestling Scheduler", layout="wide")
st.title("Wrestling Meet Scheduler")
st.caption("Upload roster → Generate → Download. **No data stored.**")

uploaded = st.file_uploader("Upload `roster.csv`", type="csv")

if uploaded:
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
            w['early'] = w['early_matches'].strip().upper() == 'Y'
            w['matches'] = []

        active = [w for w in wrestlers if not w['scratch']]
        bout_list = generate_initial_matchups(active)
        suggestions = build_suggestions(active, bout_list)
        mat_schedules = generate_mat_schedule(bout_list, gap=4)

        # === SUGGESTIONS ===
        st.subheader("Suggested Matches")
        sugg_df = pd.DataFrame([{
            '#': i+1,
            'Wrestler': f"{s['wrestler']} ({s['team']})",
            'Lvl': f"{s['level']:.1f}",
            'Wt': f"{s['weight']:.0f}",
            'vs': f"{s['vs']} ({s['vs_team']})",
            'vs_Lvl': f"{s['vs_level']:.1f}",
            'vs_Wt': f"{s['vs_weight']:.0f}",
            'Score': f"{s['score']:.1f}"
        } for i, s in enumerate(suggestions)])
        selected = st.data_editor(sugg_df, use_container_width=True, hide_index=True)

        if st.button("Add Selected"):
            to_add = [suggestions[i-1] for i in selected['#'] if i <= len(suggestions)]
            for s in to_add:
                w, o = s['_w'], s['_o']
                if o not in w['matches']: w['matches'].append(o)
                if w not in o['matches']: o['matches'].append(w)
                bout_list.append({
                    'bout_num': len(bout_list)+1,
                    'w1_id': w['id'], 'w1_name': w['name'], 'w1_team': w['team'],
                    'w1_level': w['level'], 'w1_weight': w['weight'], 'w1_grade': w['grade'], 'w1_early': w['early'],
                    'w2_id': o['id'], 'w2_name': o['name'], 'w2_team': o['team'],
                    'w2_level': o['level'], 'w2_weight': o['weight'], 'w2_grade': o['grade'], 'w2_early': o['early'],
                    'score': s['score'], 'avg_weight': (w['weight']+o['weight'])/2,
                    'is_early': w['early'] or o['early'], 'manual': 'Yes'
                })
            suggestions = build_suggestions(active, bout_list)
            mat_schedules = generate_mat_schedule(bout_list, gap=4)
            st.success("Matches added!")
            st.rerun()

        # === MAT PREVIEWS ===
        st.subheader("Mat Previews")
        tabs = st.tabs([f"Mat {i}" for i in range(1, CONFIG["NUM_MATS"]+1)])
        for i, tab in enumerate(tabs, 1):
            with tab:
                mat_data = [m for m in mat_schedules if m['mat'] == i]
                if not mat_data:
                    st.write("No matches")
                    continue
                rows = []
                for m in mat_data:
                    bout = next(b for b in bout_list if b['bout_num'] == m['bout_num'])
                    rows.append({
                        '#': m['mat_bout_num'],
                        'Wrestler 1': m['w1'],
                        'G/L/W': f"{bout['w1_grade']} / {bout['w1_level']:.1f} / {bout['w1_weight']:.0f}",
                        'Wrestler 2': m['w2'],
                        'G/L/W2': f"{bout['w2_grade']} / {bout['w2_level']:.1f} / {bout['w2_weight']:.0f}",
                        'Score': f"{bout['score']:.1f}"
                    })
                df_mat = pd.DataFrame(rows)
                st.dataframe(df_mat, use_container_width=True, hide_index=True)

        # === GENERATE ===
        if st.button("Generate Meet"):
            # Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                pd.DataFrame(bout_list).to_excel(writer, sheet_name='Matchups', index=False)
                for m in range(1, CONFIG["NUM_MATS"]+1):
                    data = [e for e in mat_schedules if e['mat'] == m]
                    df = pd.DataFrame(data)[['mat_bout_num', 'w1', 'w2']] if data else pd.DataFrame([['', '', '']], columns=['mat_bout_num', 'w1', 'w2'])
                    df.columns = ['#', 'Wrestler 1 (Team)', 'Wrestler 2 (Team)']
                    df.to_excel(writer, sheet_name=f'Mat {m}', index=False)
            excel_bytes = output.getvalue()

            # PDFs (simplified)
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
            elements = []
            for m in range(1, CONFIG["NUM_MATS"]+1):
                data = [e for e in mat_schedules if e['mat'] == m]
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

    except Exception as e:
        st.error(f"Error: {e}")

st.markdown("---")
st.caption("**Privacy**: Your roster is processed in your browser. Nothing is uploaded or stored.")
