    # --------------------------------------------------------------
    # 3. MAT PREVIEWS – CLEAN: Empty mats = empty expanders
    # --------------------------------------------------------------
    st.subheader("Mat Previews")

    filtered_ids = {w["id"] for w in filtered_active}
    filtered_bout_list = [
        b for b in st.session_state.bout_list
        if b["w1_id"] in filtered_ids or b["w2_id"] in filtered_ids
    ]
    filtered_schedule = generate_mat_schedule(filtered_bout_list) if filtered_bout_list else []

    bout_to_mat = {entry["bout_num"]: entry["mat"] for entry in filtered_schedule}

    for mat in range(1, CONFIG["NUM_MATS"] + 1):
        mat_bouts = [b for b in filtered_bout_list if bout_to_mat.get(b["bout_num"]) == mat]

        with st.expander(f"Mat {mat}", expanded=True):
            if not mat_bouts:
                # Just empty — no message
                pass
            else:
                if mat not in st.session_state.mat_order:
                    st.session_state.mat_order[mat] = [b["bout_num"] for b in mat_bouts]
                ordered_bouts = []
                for bout_num in st.session_state.mat_order[mat]:
                    entry = next((e for e in filtered_schedule if e["bout_num"] == bout_num), None)
                    if entry:
                        ordered_bouts.append(entry)
                for idx, m in enumerate(ordered_bouts):
                    b = next(x for x in st.session_state.bout_list if x["bout_num"] == m["bout_num"])
                    bg = "#fff3cd" if b["is_early"] else "#ffffff"
                    w1c = TEAM_COLORS.get(b["w1_team"], "#999")
                    w2c = TEAM_COLORS.get(b["w2_team"], "#999")
                    col_up, col_down, col_del, col_card = st.columns([0.05, 0.05, 0.05, 1], gap="small")
                    with col_up:
                        st.button("Up Arrow", key=f"up_{mat}_{b['bout_num']}_{idx}", on_click=move_up, args=(mat, b['bout_num']), help="Move up")
                    with col_down:
                        st.button("Down Arrow", key=f"down_{mat}_{b['bout_num']}_{idx}", on_click=move_down, args=(mat, b['bout_num']), help="Move down")
                    with col_del:
                        st.button("Trash", key=f"del_{b['bout_num']}_{idx}", help="Remove match (Undo available)", on_click=remove_match, args=(b['bout_num'],))
                    with col_card:
                        st.markdown(f"""
                        <div class="card-container" data-bout="{b['bout_num']}" style="background:{bg}; border:1px solid #ddd; padding:8px; border-radius:4px; margin-bottom:4px;">
                            <div style="display:flex;align-items:center;gap:12px;">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <div style="width:12px;height:12px;background:{w1c};border-radius:3px;"></div>
                                    <div style="font-weight:600;">{b['w1_name']} ({b['w1_team']})</div>
                                    <div style="font-size:0.85rem;color:#444;">{b['w1_grade']}/{b['w1_level']:.1f}/{b['w1_weight']:.0f}</div>
                                </div>
                                <div style="font-weight:700;">vs</div>
                                <div style="display:flex;flex-direction:row-reverse;align-items:center;gap:8px;">
                                    <div style="width:12px;height:12px;background:{w2c};border-radius:3px;"></div>
                                    <div style="font-size:0.85rem;color:#444;">{b['w2_grade']}/{b['w2_level']:.1f}/{b['w2_weight']:.0f}</div>
                                    <div style="font-weight:600;">{b['w2_name']} ({b['w2_team']})</div>
                                </div>
                            </div>
                            <div style="font-size:0.8rem;color:#555;margin-top:4px;">
                                Slot: {idx+1} | {"Early" if b['is_early'] else ""} | Score: {b['score']:.1f}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
