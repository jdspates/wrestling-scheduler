# generate_matchups_gui.py
# ALL OUTPUT IN SAME FOLDER AS EXE — 100% WORKING
# --------------------------------------------------------------
import sys
import os
import json
import csv
import random
import pandas as pd
from collections import defaultdict
from openpyxl.styles import Font, PatternFill
from openpyxl import load_workbook
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from threading import Thread
# --------------------------------------------------------------
# PYINSTALLER FIXES
# --------------------------------------------------------------
if getattr(sys, 'frozen', False):
    import win32com
    gen_py = type(sys)('win32com.gen_py')
    gen_py.__path__ = [os.path.join(sys._MEIPASS, 'win32com', 'gen_py')]
    sys.modules['win32com.gen_py'] = gen_py
# --------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------
CONFIG_FILE = 'config.json'
COLOR_NAME_TO_HEX = {
    "red": "#FF0000", "blue": "#0000FF", "green": "#008000", "yellow": "#FFFF00",
    "gold": "#FFD700", "black": "#000000", "white": "#FFFFFF", "gray": "#808080",
    "purple": "#800080", "orange": "#FFA500", "pink": "#FFC1CC", "brown": "#A52A2A",
    "lime": "#00FF00", "cyan": "#00FFFF", "magenta": "#FF00FF", "navy": "#000080",
    "teal": "#008080", "maroon": "#800000", "olive": "#808000", "silver": "#C0C0C0"
}
DEFAULT_CONFIG = {
    "MIN_MATCHES": 2,
    "MAX_MATCHES": 4,
    "NUM_MATS": 4,
    "MAX_LEVEL_DIFF": 1,
    "WEIGHT_DIFF_FACTOR": 0.10,
    "MIN_WEIGHT_DIFF": 5.0,
    "DEBUG_CSV": False,
    "TEAM_COLORS": {
        "Stillwater": "red",
        "Woodbury": "blue",
        "St. Thomas Academy": "green",
        "Forest Lake": "gold",
        "Black Bears": "black"
    }
}
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)
MIN_MATCHES = config.get("MIN_MATCHES", 2)
MAX_MATCHES = config.get("MAX_MATCHES", 4)
NUM_MATS = config.get("NUM_MATS", 4)
MAX_LEVEL_DIFF = config.get("MAX_LEVEL_DIFF", 1)
WEIGHT_DIFF_FACTOR = config.get("WEIGHT_DIFF_FACTOR", 0.10)
MIN_WEIGHT_DIFF = config.get("MIN_WEIGHT_DIFF", 5.0)
DEBUG_CSV_ENABLED = config.get("DEBUG_CSV", False)
raw_colors = config.get("TEAM_COLORS", {})
TEAM_COLORS = {}
for team, color in raw_colors.items():
    c = str(color).strip()
    if c.startswith("#") and len(c) == 7:
        TEAM_COLORS[team] = c.upper()
    elif c.lower() in COLOR_NAME_TO_HEX:
        TEAM_COLORS[team] = COLOR_NAME_TO_HEX[c.lower()]
    else:
        TEAM_COLORS[team] = "#000000"
DEFAULT_COLOR = '#000000'
# --------------------------------------------------------------
# GLOBAL DATA
# --------------------------------------------------------------
wrestlers_data = []
active_wrestlers = []
bout_list = []
mat_schedules = []
suggestions = []
# --------------------------------------------------------------
# CORE FUNCTIONS
# --------------------------------------------------------------
def is_compatible(w1, w2, allow_teammates=False):
    if not allow_teammates and w1['team'] == w2['team']:
        return False
    if (w1['grade'] == 5 and w2['grade'] in [7, 8]) or (w2['grade'] == 5 and w1['grade'] in [7, 8]):
        return False
    return True
def max_weight_diff(weight):
    return max(MIN_WEIGHT_DIFF, weight * WEIGHT_DIFF_FACTOR)
def matchup_score(w1, w2):
    w_diff = abs(w1['weight'] - w2['weight'])
    l_diff = abs(w1['level'] - w2['level'])
    return round(w_diff + l_diff * 10, 1)
def generate_initial_matchups():
    global bout_list
    bouts = set()
    sorted_by_level = sorted(active_wrestlers, key=lambda w: -w['level'])
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
                if len(w['matches']) >= MAX_MATCHES:
                    continue
                opps = [
                    o for o in active_wrestlers
                    if o != w and o not in w['matches'] and len(o['matches']) < MAX_MATCHES
                    and is_compatible(w, o)
                    and abs(w['weight'] - o['weight']) <= min(max_weight_diff(w['weight']), max_weight_diff(o['weight']))
                    and abs(w['level'] - o['level']) <= MAX_LEVEL_DIFF
                ]
                if not opps:
                    continue
                best = min(opps, key=lambda o: matchup_score(w, o))
                w['matches'].append(best)
                best['matches'].append(w)
                bouts.add(frozenset({w['id'], best['id']}))
                added_in_round = True
                break
    bout_list.clear()
    for idx, b in enumerate(bouts, 1):
        id_list = list(b)
        w1 = next(w for w in active_wrestlers if w['id'] == id_list[0])
        w2 = next(w for w in active_wrestlers if w['id'] == id_list[1])
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
def build_suggestions():
    under_min = [w for w in active_wrestlers if len(w['matches']) < MIN_MATCHES]
    sugg = []
    for w in under_min:
        opps = [
            o for o in active_wrestlers
            if o != w and o not in w['matches']
            and abs(w['weight'] - o['weight']) <= min(max_weight_diff(w['weight']), max_weight_diff(o['weight']))
            and abs(w['level'] - o['level']) <= MAX_LEVEL_DIFF
        ]
        if not opps:
            opps = [o for o in active_wrestlers if o != w and o not in w['matches']]
        opps = sorted(opps, key=lambda o: matchup_score(w, o))[:3]
        for o in opps:
            score = matchup_score(w, o)
            team_note = "SAME TEAM" if w['team'] == o['team'] else ""
            sugg.append({
                'wrestler': w['name'], 'level': w['level'], 'weight': w['weight'], 'team': w['team'],
                'current_matches': len(w['matches']), 'early': w['early'],
                'vs': o['name'], 'vs_level': o['level'], 'vs_weight': o['weight'], 'vs_team': o['team'],
                'opponent_matches': len(o['matches']), 'vs_early': o['early'],
                'score': score, 'note': team_note,
                '_w': w, '_o': o
            })
    return sugg
# --------------------------------------------------------------
# GUI CLASS
# --------------------------------------------------------------
class WrestlingGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Wrestling Meet Scheduler")
        self.root.geometry("1350x820")
        self.root.minsize(1100, 700)
        self.root.configure(bg="#f0f0f0")
        self.gap_var = tk.IntVar(value=4)
        self.min_matches_var = tk.IntVar(value=MIN_MATCHES)
        self.max_matches_var = tk.IntVar(value=MAX_MATCHES)
        self.num_mats_var = tk.IntVar(value=NUM_MATS)
        self.max_level_diff_var = tk.IntVar(value=MAX_LEVEL_DIFF)
        self.weight_factor_var = tk.DoubleVar(value=WEIGHT_DIFF_FACTOR)
        self.min_weight_diff_var = tk.DoubleVar(value=MIN_WEIGHT_DIFF)
        self.debug_var = tk.BooleanVar(value=DEBUG_CSV_ENABLED)
        self.mat_trees = []
        self.drag_data = {}
        self.last_removed = None  # For undo
        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_ui(self):
        top = tk.Frame(self.root, bg="#f0f0f0")
        top.pack(fill="x", padx=15, pady=10)
        tk.Label(top, text="Roster CSV:", font=("Arial", 10), bg="#f0f0f0").pack(side="left")
        self.roster_var = tk.StringVar(value="roster.csv")
        tk.Entry(top, textvariable=self.roster_var, width=50).pack(side="left", padx=5)
        tk.Button(top, text="Browse", command=self.browse_roster).pack(side="left", padx=5)
        tk.Button(top, text="Load Roster", bg="#1976D2", fg="white", command=self.load_roster).pack(side="left", padx=10)
        tk.Button(top, text="Settings", bg="#555", fg="white", command=self.show_settings).pack(side="right", padx=5)
        sugg_frame = tk.LabelFrame(self.root, text="Suggested Matches (click to select)", font=("Arial", 11, "bold"))
        sugg_frame.pack(fill="both", expand=True, padx=15, pady=5)
        cols = ("row", "wrestler", "current_matches", "wt", "lvl", "vs", "opponent_matches", "vs_wt", "vs_lvl", "score", "note")
        self.tree = ttk.Treeview(sugg_frame, columns=cols, show="headings", height=10)
        self.tree.heading("row", text="#")
        self.tree.heading("wrestler", text="Wrestler")
        self.tree.heading("current_matches", text="Matches")
        self.tree.heading("wt", text="Wt")
        self.tree.heading("lvl", text="Lvl")
        self.tree.heading("vs", text="vs")
        self.tree.heading("opponent_matches", text="Opp Matches")
        self.tree.heading("vs_wt", text="Wt")
        self.tree.heading("vs_lvl", text="Lvl")
        self.tree.heading("score", text="Score")
        self.tree.heading("note", text="Note")
        self.tree.column("row", width=40, anchor="center")
        self.tree.column("wrestler", width=200)
        self.tree.column("current_matches", width=70, anchor="center")
        self.tree.column("wt", width=50, anchor="center")
        self.tree.column("lvl", width=50, anchor="center")
        self.tree.column("vs", width=200)
        self.tree.column("opponent_matches", width=70, anchor="center")
        self.tree.column("vs_wt", width=50, anchor="center")
        self.tree.column("vs_lvl", width=50, anchor="center")
        self.tree.column("score", width=70, anchor="center")
        self.tree.column("note", width=100)
        self.tree.pack(fill="both", expand=True, padx=10, pady=5)
        btns = tk.Frame(self.root, bg="#f0f0f0")
        btns.pack(pady=8)
        tk.Button(btns, text="Add Selected", bg="#4CAF50", fg="white", width=16, command=self.add_selected).pack(side="left", padx=6)
        tk.Button(btns, text="Generate Meet", bg="#FF9800", fg="white", width=16, command=self.generate_meet).pack(side="left", padx=6)
        tk.Button(btns, text="Open Output", bg="#2196F3", fg="white", width=16, command=self.open_output_folder).pack(side="left", padx=6)
        mat_frame = tk.LabelFrame(self.root, text="Mat Previews (drag to reorder)", font=("Arial", 11, "bold"))
        mat_frame.pack(fill="both", expand=True, padx=15, pady=5)
        self.notebook = ttk.Notebook(mat_frame)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)
        for i in range(1, NUM_MATS + 1):
            tab = tk.Frame(self.notebook)
            self.notebook.add(tab, text=f"Mat {i}")
            tree = ttk.Treeview(tab, columns=("num", "w1", "w1_info", "w2", "w2_info", "score"), show="headings", height=12)
            tree.heading("num", text="#")
            tree.heading("w1", text="Wrestler 1")
            tree.heading("w1_info", text="G / L / Wt")
            tree.heading("w2", text="Wrestler 2")
            tree.heading("w2_info", text="G / L / Wt")
            tree.heading("score", text="Score")
            tree.column("num", width=40, anchor="center")
            tree.column("w1", width=220)
            tree.column("w1_info", width=80, anchor="center")
            tree.column("w2", width=220)
            tree.column("w2_info", width=80, anchor="center")
            tree.column("score", width=70, anchor="center")
            tree.pack(fill="both", expand=True, padx=5, pady=5)
            tree.bind("<ButtonPress-1>", lambda e, t=tree: self.on_tree_press(e, t))
            tree.bind("<B1-Motion>", lambda e, t=tree: self.on_tree_drag(e, t))
            tree.bind("<ButtonRelease-1>", lambda e, t=tree: self.on_tree_release(e, t))
            tree.bind("<Button-3>", lambda e, t=tree: self.show_remove_menu(e, t))
            tree.tag_configure("early", background="#FFFF99", font=("Arial", 9, "bold"))
            tree.tag_configure("dragging", background="#d0d0d0")
            self.mat_trees.append(tree)
        status_frame = tk.Frame(self.root, bg="#f0f0f0")
        status_frame.pack(fill="x", padx=15, pady=5)
        self.progress = ttk.Progressbar(status_frame, mode="determinate", length=600)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.status = tk.StringVar(value="Ready")
        tk.Label(status_frame, textvariable=self.status, fg="gray", bg="#f0f0f0").pack(side="right")

    def show_remove_menu(self, event, tree):
        item = tree.identify_row(event.y)
        menu = tk.Menu(self.root, tearoff=0)
        if item:
            menu.add_command(label="Remove Match", command=lambda: self.remove_match_from_gui(tree, item))
        if self.last_removed:
            menu.add_separator()
            menu.add_command(label="Undo Remove", command=self.undo_last_remove)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def remove_match_from_gui(self, tree, item):
        values = tree.item(item, "values")
        w1_name = values[1]
        w2_name = values[3]
        bout_num = next((b['bout_num'] for b in bout_list
                         if f"{b['w1_name']} ({b['w1_team']})" == w1_name
                         and f"{b['w2_name']} ({b['w2_team']})" == w2_name), None)
        if not bout_num:
            return

        # Save for undo
        self.last_removed = {
            'bout_num': bout_num,
            'w1_name': w1_name,
            'w2_name': w2_name
        }

        # Mark as removed
        for bout in bout_list:
            if bout['bout_num'] == bout_num:
                bout['manual'] = 'Removed'
                w1 = next(w for w in active_wrestlers if w['id'] == bout['w1_id'])
                w2 = next(w for w in active_wrestlers if w['id'] == bout['w2_id'])
                if w2 in w1['matches']: w1['matches'].remove(w2)
                if w1 in w2['matches']: w2['matches'].remove(w1)
                break

        global mat_schedules
        mat_schedules = [m for m in mat_schedules if m['bout_num'] != bout_num]

        self.generate_meet_preview()
        self.refresh_suggestions()
        messagebox.showinfo("Removed", f"Match removed: {w1_name} vs {w2_name}\n(Right-click → Undo Remove to restore)")

    def undo_last_remove(self):
        if not self.last_removed:
            return
        bout_num = self.last_removed['bout_num']
        for bout in bout_list:
            if bout['bout_num'] == bout_num:
                bout['manual'] = ''
                w1 = next(w for w in active_wrestlers if w['id'] == bout['w1_id'])
                w2 = next(w for w in active_wrestlers if w['id'] == bout['w2_id'])
                if w2 not in w1['matches']: w1['matches'].append(w2)
                if w1 not in w2['matches']: w2['matches'].append(w1)
                break
        self.last_removed = None
        self.generate_meet_preview()
        self.refresh_suggestions()
        messagebox.showinfo("Undo", "Last removed match restored!")

    def show_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Match Settings")
        dialog.geometry("420x520")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="#f8f8f8")
        tk.Label(dialog, text="Configure Match Generation", font=("Arial", 14, "bold"), bg="#f8f8f8").pack(pady=15)
        frame = tk.Frame(dialog, bg="#f8f8f8")
        frame.pack(fill="both", expand=True, padx=20, pady=10)
        def add_setting(label, var, type_="spin", from_=None, to=None, increment=None):
            row = tk.Frame(frame, bg="#f8f8f8")
            row.pack(fill="x", pady=6)
            tk.Label(row, text=label, width=20, anchor="w", bg="#f8f8f8").pack(side="left")
            if type_ == "spin":
                spin = tk.Spinbox(row, from_=from_, to=to, increment=increment, textvariable=var, width=8)
                spin.pack(side="right")
            elif type_ == "entry":
                entry = tk.Entry(row, textvariable=var, width=10)
                entry.pack(side="right")
        add_setting("Min Matches", self.min_matches_var, "spin", 1, 5, 1)
        add_setting("Max Matches", self.max_matches_var, "spin", 2, 6, 1)
        add_setting("Min Rest Gap", self.gap_var, "spin", 2, 6, 1)
        add_setting("Number of Mats", self.num_mats_var, "spin", 2, 6, 1)
        add_setting("Max Level Diff", self.max_level_diff_var, "spin", 0, 2, 1)
        add_setting("Weight Factor", self.weight_factor_var, "entry")
        add_setting("Min Weight Diff", self.min_weight_diff_var, "entry")
        debug_row = tk.Frame(frame, bg="#f8f8f8")
        debug_row.pack(fill="x", pady=6)
        tk.Label(debug_row, text="Generate Debug CSV", width=20, anchor="w", bg="#f8f8f8").pack(side="left")
        tk.Checkbutton(debug_row, variable=self.debug_var, bg="#f8f8f8").pack(side="right")
        btn_frame = tk.Frame(dialog, bg="#f8f8f8")
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Save & Close", bg="#4CAF50", fg="white", command=lambda: self.save_settings(dialog)).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Cancel", bg="#f44336", fg="white", command=dialog.destroy).pack(side="left", padx=10)

    def save_settings(self, dialog):
        global MIN_MATCHES, MAX_MATCHES, NUM_MATS, MAX_LEVEL_DIFF, WEIGHT_DIFF_FACTOR, MIN_WEIGHT_DIFF, DEBUG_CSV_ENABLED
        MIN_MATCHES = self.min_matches_var.get()
        MAX_MATCHES = self.max_matches_var.get()
        NUM_MATS = self.num_mats_var.get()
        MAX_LEVEL_DIFF = self.max_level_diff_var.get()
        WEIGHT_DIFF_FACTOR = self.weight_factor_var.get()
        MIN_WEIGHT_DIFF = self.min_weight_diff_var.get()
        DEBUG_CSV_ENABLED = self.debug_var.get()
        new_config = {
            "MIN_MATCHES": MIN_MATCHES,
            "MAX_MATCHES": MAX_MATCHES,
            "NUM_MATS": NUM_MATS,
            "MAX_LEVEL_DIFF": MAX_LEVEL_DIFF,
            "WEIGHT_DIFF_FACTOR": WEIGHT_DIFF_FACTOR,
            "MIN_WEIGHT_DIFF": MIN_WEIGHT_DIFF,
            "DEBUG_CSV": DEBUG_CSV_ENABLED,
            "TEAM_COLORS": config.get("TEAM_COLORS", {})
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=4)
        current_tab = self.notebook.index(self.notebook.select())
        for tab in self.notebook.tabs():
            self.notebook.forget(tab)
        self.mat_trees.clear()
        for i in range(1, NUM_MATS + 1):
            tab = tk.Frame(self.notebook)
            self.notebook.add(tab, text=f"Mat {i}")
            tree = ttk.Treeview(tab, columns=("num", "w1", "w1_info", "w2", "w2_info", "score"), show="headings", height=12)
            tree.heading("num", text="#")
            tree.heading("w1", text="Wrestler 1")
            tree.heading("w1_info", text="G / L / Wt")
            tree.heading("w2", text="Wrestler 2")
            tree.heading("w2_info", text="G / L / Wt")
            tree.heading("score", text="Score")
            tree.column("num", width=40, anchor="center")
            tree.column("w1", width=220)
            tree.column("w1_info", width=80, anchor="center")
            tree.column("w2", width=220)
            tree.column("w2_info", width=80, anchor="center")
            tree.column("score", width=70, anchor="center")
            tree.pack(fill="both", expand=True, padx=5, pady=5)
            tree.bind("<ButtonPress-1>", lambda e, t=tree: self.on_tree_press(e, t))
            tree.bind("<B1-Motion>", lambda e, t=tree: self.on_tree_drag(e, t))
            tree.bind("<ButtonRelease-1>", lambda e, t=tree: self.on_tree_release(e, t))
            tree.bind("<Button-3>", lambda e, t=tree: self.show_remove_menu(e, t))
            tree.tag_configure("early", background="#FFFF99", font=("Arial", 9, "bold"))
            tree.tag_configure("dragging", background="#d0d0d0")
            self.mat_trees.append(tree)
        if current_tab < NUM_MATS:
            self.notebook.select(current_tab)
        dialog.destroy()
        messagebox.showinfo("Settings Saved", "Settings updated and saved to config.json")

    def on_tree_press(self, event, tree):
        item = tree.identify_row(event.y)
        if not item: return
        self.drag_data = {
            "tree": tree,
            "item": item,
            "start_y": event.y,
            "original_tags": tree.item(item, "tags")
        }
        tree.item(item, tags=("dragging",))

    def on_tree_drag(self, event, tree):
        if "item" not in self.drag_data: return
        if self.drag_data["tree"] != tree: return
        y = event.y
        target = tree.identify_row(y)
        if not target or target == self.drag_data["item"]: return
        children = tree.get_children()
        target_idx = children.index(target)
        drag_idx = children.index(self.drag_data["item"])
        new_idx = target_idx if y < tree.bbox(target)[1] + tree.bbox(target)[3]//2 else target_idx + 1
        if new_idx != drag_idx and new_idx != drag_idx + 1:
            tree.move(self.drag_data["item"], '', new_idx)

    def on_tree_release(self, event, tree):
        if "item" not in self.drag_data: return
        item = self.drag_data["item"]
        tree.item(item, tags=self.drag_data["original_tags"])
        self.drag_data = {}
        self.update_mat_schedules_from_gui()

    def update_mat_schedules_from_gui(self):
        global mat_schedules
        new_schedules = []
        for mat_num, tree in enumerate(self.mat_trees, 1):
            for idx, iid in enumerate(tree.get_children(), 1):
                values = tree.item(iid, "values")
                bout = next((b for b in bout_list
                            if f"{b['w1_name']} ({b['w1_team']})" == values[1]
                            and f"{b['w2_name']} ({b['w2_team']})" == values[3]), None)
                if bout and bout['manual'] != 'Removed':
                    new_schedules.append({
                        'mat': mat_num, 'slot': idx, 'bout_num': bout['bout_num'],
                        'w1': values[1], 'w2': values[3], 'w1_team': bout['w1_team'], 'w2_team': bout['w2_team'],
                        'is_early': bout['is_early'], 'mat_bout_num': idx
                    })
        mat_schedules = new_schedules

    def refresh_mat_previews(self):
        for tree in self.mat_trees:
            for i in tree.get_children():
                tree.delete(i)
        for entry in mat_schedules:
            mat_num = entry['mat']
            tree = self.mat_trees[mat_num - 1]
            tags = ("early",) if entry['is_early'] else ()
            bout = next((b for b in bout_list if b['bout_num'] == entry['bout_num']), None)
            if not bout or bout['manual'] == 'Removed':
                continue
            w1_info = f"{bout['w1_grade']} / {bout['w1_level']:.1f} / {bout['w1_weight']:.0f}"
            w2_info = f"{bout['w2_grade']} / {bout['w2_level']:.1f} / {bout['w2_weight']:.0f}"
            score_str = f"{bout['score']:.1f}"
            tree.insert("", "end", values=(
                entry['mat_bout_num'],
                entry['w1'],
                w1_info,
                entry['w2'],
                w2_info,
                score_str
            ), tags=tags)

    def open_output_folder(self):
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
        os.startfile(exe_dir)

    def browse_roster(self):
        f = filedialog.askopenfilename(title="Select Roster CSV", filetypes=[("CSV Files", "*.csv")], initialdir=".")
        if f: self.roster_var.set(f)

    def load_roster(self):
        path = self.roster_var.get()
        if not os.path.exists(path):
            messagebox.showerror("File not found", f"{path}\nPlace the CSV next to the EXE.")
            return
        self.status.set("Loading roster...")
        self.progress.config(value=0)
        Thread(target=self._load_thread, args=(path,), daemon=True).start()

    def _load_thread(self, path):
        try:
            global wrestlers_data, active_wrestlers
            wrestlers_data = []
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row['id'] = int(row['id'])
                    row['grade'] = int(row['grade'])
                    row['level'] = float(row['level'])
                    row['weight'] = float(row['weight'])
                    row['early'] = row['early_matches'].strip().upper() == 'Y'
                    row['scratch'] = row['scratch'].strip().upper() == 'Y'
                    row['matches'] = []
                    wrestlers_data.append(row)
            active_wrestlers = [w for w in wrestlers_data if not w['scratch']]
            generate_initial_matchups()
            for w in wrestlers_data:
                w['match_count'] = len(w.get('matches', []))
            self.root.after(0, self.refresh_suggestions)
            self.root.after(0, lambda: self.status.set(f"Loaded {len(active_wrestlers)} wrestlers"))
            self.root.after(0, lambda: self.progress.config(value=100))
            self.root.after(0, self.generate_meet_preview)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Load error", str(e)))
            self.root.after(0, lambda: self.status.set("Load failed"))

    def refresh_suggestions(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        global suggestions
        suggestions = build_suggestions()
        for i, s in enumerate(suggestions, 1):
            self.tree.insert("", "end", iid=str(i),
                             values=(i,
                                     f"{s['wrestler']} ({s['team']})",
                                     s['current_matches'],
                                     f"{s['weight']:.0f}",
                                     f"{s['level']:.1f}",
                                     f"{s['vs']} ({s['vs_team']})",
                                     s['opponent_matches'],
                                     f"{s['vs_weight']:.0f}",
                                     f"{s['vs_level']:.1f}",
                                     f"{s['score']:.1f}",
                                     s['note']))

    def add_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Nothing selected", "Select rows in the table first.")
            return
        new_matches = []
        for iid in sel:
            idx = int(iid) - 1
            s = suggestions[idx]
            w, o = s['_w'], s['_o']
            if o not in w.get('matches', []) and w not in o.get('matches', []):
                new_matches.append((w, o, s))
        if not new_matches:
            messagebox.showinfo("No new matches", "All selected matches are already added.")
            return
        confirm_dialog = tk.Toplevel(self.root)
        confirm_dialog.title("Confirm Matches to Add")
        confirm_dialog.geometry("560x420")
        confirm_dialog.transient(self.root)
        confirm_dialog.grab_set()
        confirm_dialog.configure(bg="#f8f8f8")
        tk.Label(confirm_dialog, text="These matches will be added:", font=("Arial", 11, "bold"), bg="#f8f8f8").pack(pady=(15, 8))
        frame = tk.Frame(confirm_dialog, bg="#f8f8f8")
        frame.pack(fill="both", expand=True, padx=20, pady=5)
        text = tk.Text(frame, height=14, width=65, font=("Consolas", 9), wrap="word")
        scrollbar = tk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for w, o, s in new_matches:
            text.insert("end", f"{w['name']} vs {o['name']} (Score: {s['score']:.1f})\n")
        text.config(state="disabled")
        btn_frame = tk.Frame(confirm_dialog, bg="#f8f8f8")
        btn_frame.pack(pady=15)
        result = {"confirmed": False}
        def on_add(): result["confirmed"] = True; confirm_dialog.destroy()
        def on_cancel(): confirm_dialog.destroy()
        tk.Button(btn_frame, text="Add Selected", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), width=16, command=on_add).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Cancel", bg="#f44336", fg="white", font=("Arial", 10, "bold"), width=16, command=on_cancel).pack(side="left", padx=10)
        confirm_dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        self.root.wait_window(confirm_dialog)
        if not result["confirmed"]: return
        added = []
        for w, o, s in new_matches:
            w.setdefault('matches', []).append(o)
            o.setdefault('matches', []).append(w)
            new_bout = {
                'bout_num': len(bout_list) + 1, 'w1_id': w['id'], 'w1_name': w['name'], 'w1_team': w['team'],
                'w1_level': w['level'], 'w1_weight': w['weight'], 'w1_grade': w['grade'], 'w1_early': w['early'],
                'w2_id': o['id'], 'w2_name': o['name'], 'w2_team': o['team'],
                'w2_level': o['level'], 'w2_weight': o['weight'], 'w2_grade': o['grade'], 'w2_early': o['early'],
                'score': s['score'], 'avg_weight': (w['weight'] + o['weight']) / 2,
                'is_early': w['early'] or o['early'], 'manual': 'Yes'
            }
            bout_list.append(new_bout)
            added.append(f"{w['name']} vs {o['name']}")
        messagebox.showinfo("Added", "\n".join(added))
        self.refresh_suggestions()
        self.generate_meet_preview()

    def generate_meet_preview(self):
        self.status.set("Generating preview...")
        Thread(target=self._generate_preview_thread, daemon=True).start()

    def _generate_preview_thread(self):
        global mat_schedules
        MIN_GAP = self.gap_var.get()
        sorted_bouts = sorted([b for b in bout_list if b['manual'] != 'Removed'], key=lambda x: x['avg_weight'])
        total_bouts = len(sorted_bouts)
        per_quarter = total_bouts // NUM_MATS
        remainder = total_bouts % NUM_MATS
        mats = []
        start = 0
        for i in range(NUM_MATS):
            extra = 1 if i < remainder else 0
            end = start + per_quarter + extra
            mats.append(sorted_bouts[start:end])
            start = end
        mat_schedules.clear()
        wrestler_last_slot = {}
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
                l1 = wrestler_last_slot.get(b['w1_id'], -100)
                l2 = wrestler_last_slot.get(b['w2_id'], -100)
                if l1 < 0 and l2 < 0:
                    first_early = b
                    break
            if first_early:
                early_bouts.remove(first_early)
                scheduled.append((1, first_early))
                wrestler_last_slot[first_early['w1_id']] = 1
                wrestler_last_slot[first_early['w2_id']] = 1
                first_half_wrestlers.update([first_early['w1_id'], first_early['w2_id']])
                slot = 2
            while early_bouts and len(scheduled) < first_half_end:
                best = None
                best_score = -float('inf')
                for b in early_bouts:
                    if b['w1_id'] in first_half_wrestlers or b['w2_id'] in first_half_wrestlers:
                        continue
                    l1 = wrestler_last_slot.get(b['w1_id'], -100)
                    l2 = wrestler_last_slot.get(b['w2_id'], -100)
                    if l1 >= slot - 1 or l2 >= slot - 1:
                        continue
                    score = min(slot - l1 - 1, slot - l2 - 1)
                    if score > best_score:
                        best_score = score
                        best = b
                if best is None: break
                early_bouts.remove(best)
                scheduled.append((slot, best))
                wrestler_last_slot[best['w1_id']] = slot
                wrestler_last_slot[best['w2_id']] = slot
                first_half_wrestlers.update([best['w1_id'], best['w2_id']])
                slot += 1
            remaining = non_early_bouts + early_bouts
            while remaining:
                best = None
                best_gap = -1
                for b in remaining:
                    l1 = wrestler_last_slot.get(b['w1_id'], -100)
                    l2 = wrestler_last_slot.get(b['w2_id'], -100)
                    if l1 >= slot - MIN_GAP or l2 >= slot - MIN_GAP:
                        continue
                    gap = min(slot - l1 - 1, slot - l2 - 1)
                    if gap > best_gap:
                        best_gap = gap
                        best = b
                if best is None:
                    best = remaining[0]
                remaining.remove(best)
                scheduled.append((slot, best))
                wrestler_last_slot[best['w1_id']] = slot
                wrestler_last_slot[best['w2_id']] = slot
                slot += 1
            for s, b in scheduled:
                mat_schedules.append({
                    'mat': mat_num, 'slot': s, 'bout_num': b['bout_num'],
                    'w1': f"{b['w1_name']} ({b['w1_team']})", 'w2': f"{b['w2_name']} ({b['w2_team']})",
                    'w1_team': b['w1_team'], 'w2_team': b['w2_team'], 'is_early': b['is_early']
                })
        for mat_num in range(1, NUM_MATS + 1):
            mat_entries = [m for m in mat_schedules if m['mat'] == mat_num]
            mat_entries.sort(key=lambda x: x['slot'])
            for idx, entry in enumerate(mat_entries, 1):
                entry['mat_bout_num'] = idx
        self.root.after(0, self.refresh_mat_previews)
        self.root.after(0, lambda: self.status.set("Preview ready — drag to reorder!"))

    def generate_meet(self):
        if not bout_list and not mat_schedules:
            messagebox.showwarning("No matches", "Load a roster and generate initial matchups first.")
            return
        self.status.set("Generating meet...")
        self.progress.config(value=0)
        Thread(target=self._generate_thread, daemon=True).start()

    def _generate_thread(self):
        global mat_schedules
        try:
            self.update_mat_schedules_from_gui()
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
            excel_file = os.path.join(exe_dir, "meet_schedule_with_extras.xlsx")
            total_steps = 10 + NUM_MATS + 3
            step = 0
            def update_progress(msg, inc=1):
                nonlocal step
                step += inc
                self.root.after(0, lambda: self.status.set(msg))
                self.root.after(0, lambda: self.progress.config(value=step/total_steps*100))
            update_progress("Saving Excel...", 1)
            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
                pd.DataFrame({'Info': ['Wrestling Meet Generated']}).to_excel(writer, sheet_name='Info', index=False)
                writer.book['Info'].sheet_state = 'visible'
                roster_df = pd.DataFrame(wrestlers_data)
                roster_df = roster_df[['id', 'name', 'team', 'grade', 'level', 'weight', 'match_count', 'early_matches', 'scratch']]
                roster_df = roster_df.sort_values('id')
                roster_df.to_excel(writer, sheet_name='Roster', index=False)
                if bout_list:
                    matchups_df = pd.DataFrame(bout_list)
                    matchups_df = matchups_df[[
                        'bout_num', 'w1_name', 'w1_team', 'w1_level', 'w1_weight', 'w1_early',
                        'w2_name', 'w2_team', 'w2_level', 'w2_weight', 'w2_early',
                        'score', 'manual'
                    ]]
                    matchups_df.columns = [
                        'Bout #', 'Wrestler 1', 'Team 1', 'Lvl 1', 'Wt 1', 'Early1',
                        'Wrestler 2', 'Team 2', 'Lvl 2', 'Wt 2', 'Early2',
                        'Score', 'Manual'
                    ]
                    matchups_df = matchups_df.sort_values('Wt 1')
                    matchups_df.to_excel(writer, sheet_name='Matchups', index=False)
                if suggestions:
                    clean_sugg = [{k: v for k, v in s.items() if not k.startswith('_')} for s in suggestions]
                    pd.DataFrame(clean_sugg).to_excel(writer, sheet_name='Remaining_Suggestions', index=False)
                for mat_num in range(1, NUM_MATS + 1):
                    mat_data = [m for m in mat_schedules if m['mat'] == mat_num]
                    if mat_data:
                        df = pd.DataFrame(mat_data)
                        df = df[['mat_bout_num', 'w1', 'w2']]
                        df.columns = ['Mat Bout', 'Wrestler 1 (Team)', 'Wrestler 2 (Team)']
                        df = df.sort_values('Mat Bout')
                    else:
                        df = pd.DataFrame([['No matches']], columns=['Mat Bout', 'Wrestler 1 (Team)', 'Wrestler 2 (Team)'])
                    df.to_excel(writer, sheet_name=f'Mat {mat_num}', index=False)
                    wb = writer.book
                    ws = writer.sheets[f'Mat {mat_num}']
                    yellow_fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
                    for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
                        if row_idx <= len(mat_data):
                            mat_entry = mat_data[row_idx-2]
                            w1_team = mat_entry['w1_team']
                            w2_team = mat_entry['w2_team']
                            color1 = TEAM_COLORS.get(w1_team, DEFAULT_COLOR)
                            color2 = TEAM_COLORS.get(w2_team, DEFAULT_COLOR)
                            font1 = Font(color=color1[1:])
                            font2 = Font(color=color2[1:])
                            for cell in row[1:2]: cell.font = font1
                            for cell in row[2:3]: cell.font = font2
                            if mat_entry['is_early']:
                                for cell in row: cell.fill = yellow_fill
            update_progress("Generating PDFs...", 1)
            def create_pdf_with_wrap(df, title, filename, mat_schedules_subset, landscape_mode=False):
                update_progress(f"Creating {os.path.basename(filename)}...", 1)
                try:
                    pagesize = landscape(letter) if landscape_mode else letter
                    doc = SimpleDocTemplate(filename, pagesize=pagesize,
                                           leftMargin=0.25*inch, rightMargin=0.25*inch,
                                           topMargin=0.4*inch, bottomMargin=0.2*inch)
                    styles = getSampleStyleSheet()
                    elements = []
                    elements.append(Paragraph(title, styles['Title']))
                    elements.append(Spacer(1, 6))
                    if df.empty or (len(df) == 1 and df.iloc[0,0] == 'No matches'):
                        elements.append(Paragraph("No matches scheduled on this mat.", styles['Normal']))
                    else:
                        data = [df.columns.tolist()] + df.values.tolist()
                        col_widths = [0.7*inch, 3.4*inch, 3.4*inch]
                        ROW_HEIGHT = 0.22*inch
                        row_heights = [0.35*inch] + [ROW_HEIGHT] * len(df)
                        table = Table(data, colWidths=col_widths, rowHeights=row_heights, repeatRows=1)
                        style = TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), rl_colors.grey),
                            ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.whitesmoke),
                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('FONTSIZE', (0, 0), (-1, 0), 9),
                            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
                            ('GRID', (0, 0), (-1, -1), 0.4, rl_colors.black),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('LEFTPADDING', (0, 0), (-1, -1), 3),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                        ])
                        if title.startswith('Mat '):
                            for i, row_vals in enumerate(df.itertuples(index=False), start=1):
                                if row_vals[0] == 'No matches': continue
                                w1_disp = row_vals[1]
                                w2_disp = row_vals[2]
                                mat_entry = next((m for m in mat_schedules_subset
                                                if m['w1'] == w1_disp and m['w2'] == w2_disp), None)
                                if mat_entry:
                                    c1 = rl_colors.HexColor(TEAM_COLORS.get(mat_entry['w1_team'], DEFAULT_COLOR))
                                    c2 = rl_colors.HexColor(TEAM_COLORS.get(mat_entry['w2_team'], DEFAULT_COLOR))
                                    style.add('TEXTCOLOR', (1, i), (1, i), c1)
                                    style.add('TEXTCOLOR', (2, i), (2, i), c2)
                                    if mat_entry['is_early']:
                                        style.add('BACKGROUND', (0, i), (-1, i), rl_colors.HexColor('#FFFF99'))
                        table = Table(data, colWidths=col_widths, rowHeights=row_heights, repeatRows=1)
                        table.setStyle(style)
                        elements.append(table)
                    doc.build(elements)
                except Exception as e:
                    print(f"PDF Error ({filename}): {e}")
            try:
                full_elements = []
                for mat_num in range(1, NUM_MATS + 1):
                    mat_data = [m for m in mat_schedules if m['mat'] == mat_num]
                    if mat_data:
                        df = pd.DataFrame(mat_data)
                        df = df[['mat_bout_num', 'w1', 'w2']]
                        df.columns = ['Mat Bout', 'Wrestler 1 (Team)', 'Wrestler 2 (Team)']
                        df = df.sort_values('Mat Bout')
                    else:
                        df = pd.DataFrame([['No matches']], columns=['Mat Bout', 'Wrestler 1 (Team)', 'Wrestler 2 (Team)'])
                    title = f"Mat {mat_num}"
                    pdf_path = os.path.join(exe_dir, f"{title.replace(' ', '_')}.pdf")
                    create_pdf_with_wrap(df, title, pdf_path, mat_data, landscape_mode=True)
                    full_elements.append(Paragraph(title, getSampleStyleSheet()['Title']))
                    full_elements.append(Spacer(1, 12))
                    data = [df.columns.tolist()] + df.values.tolist()
                    table = Table(data)
                    table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, rl_colors.black)]))
                    full_elements.append(table)
                    full_elements.append(PageBreak())
                full_pdf_path = os.path.join(exe_dir, 'meet_schedule.pdf')
                full_doc = SimpleDocTemplate(full_pdf_path, pagesize=letter)
                full_doc.build(full_elements)
            except Exception as e:
                print(f"PDF Generation Failed: {e}")
            if DEBUG_CSV_ENABLED:
                sorted_bouts = sorted(bout_list, key=lambda x: x['avg_weight'])
                per_quarter = len(sorted_bouts) // NUM_MATS
                remainder = len(sorted_bouts) % NUM_MATS
                debug_data = []
                for i, bout in enumerate(sorted_bouts):
                    quarter = (i // per_quarter) + 1 if i < (NUM_MATS * per_quarter) else NUM_MATS
                    if i >= remainder * (per_quarter + 1):
                        quarter = NUM_MATS
                    mat = next((m['mat'] for m in mat_schedules if m['bout_num'] == bout['bout_num']), 'Unknown')
                    debug_data.append({
                        'Bout #': bout['bout_num'],
                        'Wrestler 1': bout['w1_name'],
                        'Wrestler 2': bout['w2_name'],
                        'Avg Weight': round(bout['avg_weight'], 1),
                        'Quarter': quarter,
                        'Mat': mat,
                        'Early': 'YES' if bout['is_early'] else 'NO'
                    })
                debug_df = pd.DataFrame(debug_data)
                debug_df = debug_df.sort_values(['Quarter', 'Avg Weight'])
                debug_df.to_csv(os.path.join(exe_dir, 'debug_weight_quarters.csv'), index=False)
            update_progress("Done!", 1)
            self.root.after(0, lambda: messagebox.showinfo(
                "Success!",
                "Meet generated successfully!\n\n"
                "All files saved in the same folder as the app:\n"
                f"{exe_dir}\n\n"
                "• meet_schedule_with_extras.xlsx\n"
                "• meet_schedule.pdf\n"
                "• Mat PDFs (even if empty)\n"
                "• debug_weight_quarters.csv (if enabled)\n\n"
                "Click 'Open Output' to view."
            ))
            self.root.after(0, lambda: self.status.set("Finished"))
            self.root.after(0, lambda: self.progress.config(value=100))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self.status.set("Failed"))

    def on_close(self):
        if messagebox.askokcancel("Quit", "Exit the scheduler?"):
            self.root.destroy()

# --------------------------------------------------------------
# RUN
# --------------------------------------------------------------
if __name__ == "__main__":
    app = WrestlingGUI()
    app.root.mainloop()