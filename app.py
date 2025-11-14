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
        slots = [None] * len(mat_bouts)  # Track actual placement

        while queue:
            bout = queue.pop(0)
            w1, w2 = bout["w1_id"], bout["w2_id"]

            # Try to find a safe slot
            placed_slot = None
            for s in range(len(slots)):
                if slots[s] is not None:
                    continue
                # Check REST_GAP from last known placement
                if (cooldown.get(w1, 0) > 0 or cooldown.get(w2, 0) > 0):
                    continue
                # Check ±REST_GAP slots
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

            # Decrease cooldowns
            for w in list(cooldown.keys()):
                cooldown[w] = max(0, cooldown[w] - 1)

        # Fallback: place remaining in first open slot
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
