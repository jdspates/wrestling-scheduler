import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import json
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import base64

# ---------- Excel-only imports (safe) ----------
try:
    from openpyxl.styles import PatternFill
    _EXCEL_AVAILABLE = True
except Exception:
    _EXCEL_AVAILABLE = False

# Config for team colors
@st.cache_data
def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        default_config = {
            "team_colors": {
                "Red Team": "#FF0000",
                "Blue Team": "#0000FF",
            }
        }
        with open('config.json', 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config

config = load_config()
TEAM_COLORS = config["team_colors"]

# Custom CSS
st.markdown("""
<style>
    .highlight-early { background-color: yellow !important; }
    .team-color { font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# Session state
if 'roster_df' not in st.session_state:
    st.session_state.roster_df = None
if 'matchups' not in st.session_state:
    st.session_state.matchups = pd.DataFrame()
if 'suggested_matchups' not in st.session_state:
    suggested_matchups = pd.DataFrame()
if 'accepted_matchups' not in st.session_state:
    st.session_state.accepted_matchups = pd.DataFrame()
if 'mat_schedules' not in st.session_state:
    st.session_state.mat_schedules = {f'Mat {i}': pd.DataFrame() for i in range(1, 5)}

# Highlight helpers
def highlight_early(val):
    return 'background-color: yellow' if val == 'Early' else ''

def color_team_name(val):
    if pd.isna(val) or val not in TEAM_COLORS:
        return f'<span class="team-color">{val}</span>' if pd.notna(val) else ''
    return f'<span style="color: {TEAM_COLORS.get(val, "#000000")}">{val}</span>'

# Core logic
@st.cache_data
def generate_matchups(roster_df):
    if roster_df is None or roster_df.empty:
        return pd.DataFrame()
    valid_df = roster_df[roster_df['Scratched'] != 'Yes'].copy()
    valid_df = valid_df.sort_values(['Level', 'Weight'], ascending=[True, True])
    matchups = []
    used = set()
    for i, row1 in valid_df.iterrows():
        if row1['ID'] in used:
            continue
        for j, row2 in valid_df.iterrows():
            if (row2['ID'] in used or row1['Team'] == row2['Team'] or
                abs(row1['Weight'] - row2['Weight']) > 5):
                continue
            matchups.append({
                'Bout': len(matchups) + 1,
                'Wrestler1': f"{row1['Name']} ({row1['Weight']}lbs)",
                'Team1': row1['Team'],
                'Wrestler2': f"{row2['Name']} ({row2['Weight']}lbs)",
                'Team2': row2['Team'],
                'Avg Weight': (row1['Weight'] + row2['Weight']) / 2,
                'Early': 'Early' if len(matchups) < 5 else '',
                'Mat': ''
            })
            used.add(row1['ID'])
            used.add(row2['ID'])
            break
    return pd.DataFrame(matchups)

def assign_to_mats(matchups_df):
    if matchups_df.empty:
        return {f'Mat {i}': pd.DataFrame() for i in range(1, 5)}
    sorted_matchups = matchups_df.sort_values('Avg Weight').reset_index(drop=True)
    mat_schedules = {f'Mat {i}': pd.DataFrame() for i in range(1, 5)}
    for idx, row in sorted_matchups.iterrows():
        mat_num = (idx % 4) + 1
        row = row.copy()
        row['Mat'] = f'Mat {mat_num}'
        mat_schedules[f'Mat {mat_num}'] = pd.concat([mat_schedules[f'Mat {mat_num}'], pd.DataFrame([row])], ignore_index=True)
    return mat_schedules

def create_excel_bytes(matchups, suggested, accepted, mat_schedules):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        matchups.to_excel(writer, sheet_name='All Matchups', index=False)
        suggested.to_excel(writer, sheet_name='Suggestions', index=False)
        accepted.to_excel(writer, sheet_name='Accepted', index=False)

        for mat_name, df in mat_schedules.items():
            sheet = mat_name
            if df.empty:
                pd.DataFrame({'Message': ['No matches assigned']}).to_excel(writer, sheet_name=sheet, index=False)
            else:
                df.to_excel(writer, sheet_name=sheet, index=False)
                if _EXCEL_AVAILABLE:
                    workbook = writer.book
                    ws = writer.sheets[sheet]
                    yellow_fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
                    early_col = df.columns.get_loc("Early") + 1  # 1-based
                    for r_idx, row in df.iterrows():
                        if row["Early"] == "Early":
                            for c_idx in range(1, len(df.columns) + 1):
                                ws.cell(row=r_idx + 2, column=c_idx).fill = yellow_fill  # +2: header + 0-based
    return output.getvalue()

def create_pdf_bytes(df, title, is_mat=False):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], alignment=1, spaceAfter=30)
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 0.2*inch))

    if df.empty:
        story.append(Paragraph("No matches scheduled.", styles['Normal']))
    else:
        data = [['Bout', 'Wrestler1', 'Team1', 'Wrestler2', 'Team2', 'Avg Weight', 'Type']] + \
               df[['Bout', 'Wrestler1', 'Team1', 'Wrestler2', 'Team2', 'Avg Weight', 'Early']].values.tolist()
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        for i in range(1, len(data)):
            if is_mat and data[i][6] == 'Early':
                table.setStyle(TableStyle([('BACKGROUND', (0, i), (-1, i), colors.yellow)]))
            if data[i][2] in TEAM_COLORS:
                table.setStyle(TableStyle([('TEXTCOLOR', (2, i), (2, i), colors.HexColor(TEAM_COLORS[data[i][2]]))]))
            if data[i][4] in TEAM_COLORS:
                table.setStyle(TableStyle([('TEXTCOLOR', (4, i), (4, i), colors.HexColor(TEAM_COLORS[data[i][4]]))]))
        story.append(table)
    doc.build(story)
    return buffer.getvalue()

# UI
st.title("Wrestling Meet Scheduler")

# Upload
uploaded_file = st.file_uploader("Upload Roster (CSV/Excel)", type=['csv', 'xlsx'])
if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            st.session_state.roster_df = pd.read_csv(uploaded_file)
        else:
            st.session_state.roster_df = pd.read_excel(uploaded_file)
        st.success("Roster uploaded!")
        # Reset on new upload
        st.session_state.matchups = pd.DataFrame()
        st.session_state.suggested_matchups = pd.DataFrame()
        st.session_state.accepted_matchups = pd.DataFrame()
        st.session_state.mat_schedules = {f'Mat {i}': pd.DataFrame() for i in range(1, 5)}
    except Exception as e:
        st.error(f"Upload error: {e}")

# Generate button
if st.button("Generate Matches"):
    with st.spinner("Generating matchups and schedules..."):
        try:
            if st.session_state.roster_df is not None:
                st.session_state.matchups = generate_matchups(st.session_state.roster_df)
                st.session_state.suggested_matchups = (
                    st.session_state.matchups.sample(min(5, len(st.session_state.matchups)))
                    if not st.session_state.matchups.empty else pd.DataFrame()
                )
                st.session_state.mat_schedules = assign_to_mats(st.session_state.matchups)
                st.toast("Matchups generated successfully!", icon="Success")

                # Auto Excel download
                excel_bytes = create_excel_bytes(
                    st.session_state.matchups,
                    st.session_state.suggested_matchups,
                    st.session_state.accepted_matchups,
                    st.session_state.mat_schedules,
                )
                st.download_button(
                    label="Download Excel (Auto)",
                    data=excel_bytes,
                    file_name="wrestling_matchups.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="auto_excel",
                    use_container_width=True
                )
            else:
                st.toast("No roster uploaded. Upload first.", icon="Warning")
        except Exception as e:
            st.error(f"Generation failed: {e}")
            st.toast("Error – check console.", icon="Cross")

# Suggestions
if not st.session_state.suggested_matchups.empty:
    st.subheader("Suggested Matchups")
    edited_suggestions = st.data_editor(
        st.session_state.suggested_matchups,
        column_config={
            "Team1": st.column_config.TextColumn("Team1"),
            "Team2": st.column_config.TextColumn("Team2"),
        },
        disabled=["Bout", "Avg Weight", "Early"],
        use_container_width=True,
        hide_index=False,
        key="suggestions_editor"
    )
    if st.button("Accept Selected Suggestions"):
        sel = st.session_state.suggestions_editor.get("selected_rows", [])
        selected_rows = edited_suggestions.iloc[sel]
        st.session_state.accepted_matchups = pd.concat([st.session_state.accepted_matchups, selected_rows], ignore_index=True)
        st.session_state.suggested_matchups = st.session_state.suggested_matchups.drop(selected_rows.index).reset_index(drop=True)
        st.rerun()

# Mat Previews (always expanded)
st.subheader("Mat Previews")
for mat_name, df in st.session_state.mat_schedules.items():
    with st.expander(mat_name, expanded=True):
        if not df.empty:
            styled_df = df.style.applymap(highlight_early, subset=['Early'])\
                                .applymap(color_team_name, subset=['Team1', 'Team2'])
            st.markdown(styled_df.to_html(escape=False), unsafe_allow_html=True)

            edited_df = st.data_editor(
                df,
                column_config={
                    "Team1": st.column_config.TextColumn("Team1"),
                    "Team2": st.column_config.TextColumn("Team2"),
                },
                disabled=["Bout", "Avg Weight", "Mat"],
                use_container_width=True,
                hide_index=False,
                key=f"{mat_name}_editor",
                num_rows="dynamic"
            )
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Up", key=f"up_{mat_name}"):
                    sel = st.session_state[f"{mat_name}_editor"].get("selected_rows", [])
                    if sel and sel[0] > 0:
                        i = sel[0]
                        edited_df.iloc[[i-1, i]] = edited_df.iloc[[i, i-1]].values
                        st.session_state.mat_schedules[mat_name] = edited_df
                        st.rerun()
            with col2:
                if st.button("Down", key=f"down_{mat_name}"):
                    sel = st.session_state[f"{mat_name}_editor"].get("selected_rows", [])
                    if sel and sel[0] < len(edited_df)-1:
                        i = sel[0]
                        edited_df.iloc[[i, i+1]] = edited_df.iloc[[i+1, i]].values
                        st.session_state.mat_schedules[mat_name] = edited_df
                        st.rerun()
            with col3:
                if st.button("Delete", key=f"del_{mat_name}"):
                    sel = st.session_state[f"{mat_name}_editor"].get("selected_rows", [])
                    if sel:
                        edited_df = edited_df.drop(edited_df.index[sel]).reset_index(drop=True)
                        st.session_state.mat_schedules[mat_name] = edited_df
                        st.rerun()
        else:
            st.info("No matches assigned to this mat.")

# Downloads
st.subheader("Downloads")
col_ex, col_pdf = st.columns(2)

with col_ex:
    if not st.session_state.matchups.empty:
        excel_bytes = create_excel_bytes(
            st.session_state.matchups,
            st.session_state.suggested_matchups,
            st.session_state.accepted_matchups,
            st.session_state.mat_schedules,
        )
        st.download_button(
            label="Download Full Excel",
            data=excel_bytes,
            file_name="wrestling_matchups.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

with col_pdf:
    if not st.session_state.matchups.empty:
        all_pdf = create_pdf_bytes(st.session_state.matchups, "All Matchups")
        st.download_button(
            label="Download All Matchups PDF",
            data=all_pdf,
            file_name="all_matchups.pdf",
            mime="application/pdf",
            use_container_width=True
        )
        for mat_name, df in st.session_state.mat_schedules.items():
            if not df.empty:
                mat_pdf = create_pdf_bytes(df, mat_name, is_mat=True)
                st.download_button(
                    label=f"Download {mat_name} PDF",
                    data=mat_pdf,
                    file_name=f"{mat_name.lower().replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"pdf_{mat_name}"
                )
