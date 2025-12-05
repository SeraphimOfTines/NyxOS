import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import threading
import time
import json
import os
import sys
import subprocess
import re
import copy

# Auto-install dependencies
def install_and_import(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        __import__(import_name)
    except ImportError:
        print(f"Dependency '{package}' not found. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"Successfully installed '{package}'.")
        except Exception as e:
            print(f"Failed to install '{package}': {e}")
            input("Press Enter to exit...")
            sys.exit(1)

install_and_import("requests")
install_and_import("Pillow", "PIL")

import requests
from PIL import Image, ImageTk, ImageSequence

# ==========================================
# CONFIGURATION & PATHS
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "nyxcontrolconfig.txt")
EMOJI_DB_FILE = os.path.join(BASE_DIR, "emoji_db.json")
PALETTE_LAYOUT_FILE = os.path.join(BASE_DIR, "palette_layout.json")
PRESETS_FILE = os.path.join(BASE_DIR, "presets.json")
EMOJI_IMG_DIR = os.path.join(BASE_DIR, "emojis")

# Ensure folders exist
if not os.path.exists(EMOJI_IMG_DIR):
    os.makedirs(EMOJI_IMG_DIR)

# Default Config
API_URL = "http://localhost:5555"
API_KEY = "changeme_default"

def load_config():
    global API_URL, API_KEY
    host = "localhost"
    port = "5555"
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                content = f.read()
                for line in content.splitlines():
                    if "CONTROL_API_HOST" in line:
                         try: host = line.split("=")[1].strip().strip('"').strip("'")
                         except: pass
                    if "CONTROL_API_PORT" in line:
                        try: port = line.split("=")[1].strip()
                        except: pass
                    if "CONTROL_API_KEY" in line:
                        try: API_KEY = line.split("=")[1].strip().strip('"').strip("'")
                        except: pass
        except Exception as e:
            print(f"Error loading config: {e}")
            
    API_URL = f"http://{host}:{port}"

load_config()

# Load Emoji DB
emoji_map = {} # Name -> Discord String
if os.path.exists(EMOJI_DB_FILE):
    try:
        with open(EMOJI_DB_FILE, "r") as f:
            emoji_map = json.load(f)
    except: pass

# Load Palette Layout
palette_layout = {
    "categories": {
        "Yami": [],
        "Calyptra": [],
        "Riven": [],
        "SΛTVRN": [],
        "Other": []
    }, 
    "hidden": [], 
    "use_counts": {}
}

if os.path.exists(PALETTE_LAYOUT_FILE):
    try:
        with open(PALETTE_LAYOUT_FILE, "r") as f:
            loaded = json.load(f)
            # Migration: Old "quick" list -> "Other"
            if "quick" in loaded and isinstance(loaded["quick"], list):
                palette_layout["categories"]["Other"].extend(loaded["quick"])
                if "hidden" in loaded: palette_layout["hidden"] = loaded["hidden"]
                if "use_counts" in loaded: palette_layout["use_counts"] = loaded["use_counts"]
            elif "categories" in loaded:
                # Merge loaded categories with defaults to ensure all exist
                for cat in palette_layout["categories"]:
                    if cat in loaded["categories"]:
                        palette_layout["categories"][cat] = loaded["categories"][cat]
                # Preserve hidden/counts
                if "hidden" in loaded: palette_layout["hidden"] = loaded["hidden"]
                if "use_counts" in loaded: palette_layout["use_counts"] = loaded["use_counts"]
    except: pass

# Reconcile Layout with DB
# 1. Collect all known items in layout
layout_items = set(palette_layout["hidden"])
for cat_list in palette_layout["categories"].values():
    layout_items.update(cat_list)

# 2. Add missing DB items to "Other"
db_keys = set(emoji_map.keys())
missing = db_keys - layout_items
for m in missing:
    palette_layout["categories"]["Other"].append(m)

# 3. Remove items not in DB
palette_layout["hidden"] = [x for x in palette_layout["hidden"] if x in emoji_map]
for cat in palette_layout["categories"]:
    palette_layout["categories"][cat] = [x for x in palette_layout["categories"][cat] if x in emoji_map]

# Load Presets
presets = {}
if os.path.exists(PRESETS_FILE):
    try:
        with open(PRESETS_FILE, "r") as f:
            presets = json.load(f)
    except: pass

def save_presets():
    try:
        with open(PRESETS_FILE, "w") as f:
            json.dump(presets, f, indent=4)
    except: pass

def save_palette_layout():
    # Threaded save to prevent I/O lag
    def _save(data):
        try:
            with open(PALETTE_LAYOUT_FILE, "w") as f:
                json.dump(data, f, indent=4)
        except: pass
    
    data_copy = copy.deepcopy(palette_layout)
    threading.Thread(target=_save, args=(data_copy,), daemon=True).start()

save_palette_layout()

# ==========================================
# API CLIENT
# ==========================================
class NyxClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": API_KEY})

    def get_status(self):
        try:
            resp = self.session.get(f"{API_URL}/api/status", timeout=1)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def get_bars(self):
        try:
            resp = self.session.get(f"{API_URL}/api/bars", timeout=2)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def set_global_state(self, action):
        try:
            resp = self.session.post(f"{API_URL}/api/global/state", json={"action": action}, timeout=2)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def set_global_text(self, text):
        try:
            resp = self.session.post(f"{API_URL}/api/global/update", json={"content": text}, timeout=2)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def get_emojis(self):
        try:
            resp = self.session.get(f"{API_URL}/api/emojis", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

client = NyxClient()

# ==========================================
# DRAG MANAGER (Lightweight)
# ==========================================
class DragManager:
    def __init__(self, app):
        self.app = app
        self.dragged_item = None
        self.source_category = None
        self.is_dragging = False

    def start_drag(self, event, item_name, category):
        self.dragged_item = item_name
        self.source_category = category
        self.is_dragging = False # Wait for move

    def on_motion(self, event):
        if self.dragged_item and not self.is_dragging:
            # Threshold met, start dragging
            self.is_dragging = True
            self.app.config(cursor="fleur")

    def stop_drag(self, event):
        self.app.config(cursor="") # Reset cursor
        
        if not self.is_dragging or not self.dragged_item:
            # Just a click, handled by button command
            self.is_dragging = False
            self.dragged_item = None
            return

        # Determine Drop Target
        x, y = event.x_root, event.y_root
        
        target_category = None
        
        # Check Hidden Pane if visible
        if self.app.storage_visible:
            hx = self.app.hidden_frame.winfo_rootx()
            hy = self.app.hidden_frame.winfo_rooty()
            hw = self.app.hidden_frame.winfo_width()
            hh = self.app.hidden_frame.winfo_height()
            if hx <= x <= hx + hw and hy <= y <= hy + hh:
                target_category = "hidden"

        # Check Categories
        if not target_category:
            for cat, frame in self.app.category_frames.items():
                fx = frame.winfo_rootx()
                fy = frame.winfo_rooty()
                fw = frame.winfo_width()
                fh = frame.winfo_height()
                
                # Approximate hit test
                if fx <= x <= fx + fw and fy <= y <= fy + fh:
                    target_category = cat
                    break
        
        if target_category and target_category != self.source_category:
            self.move_item(self.dragged_item, self.source_category, target_category)

        self.is_dragging = False
        self.dragged_item = None

    def move_item(self, item, source, target):
        # Remove from Source
        if source == "hidden":
            if item in palette_layout["hidden"]: palette_layout["hidden"].remove(item)
        else:
            if item in palette_layout["categories"][source]: palette_layout["categories"][source].remove(item)
            
        # Add to Target
        if target == "hidden":
            palette_layout["hidden"].append(item)
        else:
            palette_layout["categories"][target].append(item)
            
        save_palette_layout()
        self.app.render_palettes()


# ==========================================
# GUI APPLICATION
# ==========================================
class NyxControlApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NyxOS Control Center")
        self.geometry("1200x800") 
        self.configure(bg="#2C2F33") 

        self.drag_manager = DragManager(self)
        self.icon_cache = {}
        
        # Layout State
        self.storage_visible = False
        self.category_frames = {} # cat_name -> Frame widget
        self.cols_quick = 5
        self.cols_hidden = 3

        # Styles
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#2C2F33")
        style.configure("TLabel", background="#2C2F33", foreground="white", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 9), background="#7289DA", foreground="white")
        style.map("TButton", background=[('active', '#677BC4')])
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#7289DA")
        style.configure("Category.TLabel", font=("Segoe UI", 11, "bold"), foreground="#99AAB5")

        # --- MAIN LAYOUT ---
        self.main_container = ttk.Frame(self)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1. STATUS HEADER
        self.status_frame = ttk.Frame(self.main_container)
        self.status_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.status_indicator = tk.Label(self.status_frame, text="●", fg="red", bg="#2C2F33", font=("Arial", 16))
        self.status_indicator.pack(side=tk.LEFT)
        
        self.status_label = ttk.Label(self.status_frame, text="Connecting...", font=("Segoe UI", 12))
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.latency_label = ttk.Label(self.status_frame, text="")
        self.latency_label.pack(side=tk.RIGHT)

        ttk.Separator(self.main_container, orient='horizontal').pack(fill=tk.X, pady=5)

        # 2. GLOBAL CONTROLS
        self.global_frame = ttk.Frame(self.main_container)
        self.global_frame.pack(fill=tk.X, pady=5)

        ttk.Label(self.global_frame, text="Global Actions:", style="Header.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        
        self.btn_awake = ttk.Button(self.global_frame, text="Awake All (0)", command=lambda: self.send_state("awake"))
        self.btn_awake.pack(side=tk.LEFT, padx=2)
        
        self.btn_idle = ttk.Button(self.global_frame, text="Idle All (Watching)", command=lambda: self.send_state("idle"))
        self.btn_idle.pack(side=tk.LEFT, padx=2)
        
        self.btn_sleep = ttk.Button(self.global_frame, text="Sleep All (Zzz)", command=lambda: self.send_state("sleep"))
        self.btn_sleep.pack(side=tk.LEFT, padx=2)

        # 3. MASTER BAR EDITOR
        self.editor_frame = ttk.Frame(self.main_container)
        self.editor_frame.pack(fill=tk.X, pady=10)

        ttk.Label(self.editor_frame, text="Master Bar Text:", style="Header.TLabel").pack(anchor=tk.W)
        
        self.input_wrapper = ttk.Frame(self.editor_frame)
        self.input_wrapper.pack(fill=tk.X, pady=5)
        
        self.text_entry = tk.Entry(self.input_wrapper, bg="#23272A", fg="white", insertbackground="white", font=("Consolas", 11))
        self.text_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.text_entry.bind("<KeyRelease>", self.update_preview) 
        self.text_entry.bind("<Return>", lambda e: self.send_text_update())
        
        self.btn_clear = ttk.Button(self.input_wrapper, text="✖", width=3, command=self.clear_text)
        self.btn_clear.pack(side=tk.RIGHT, padx=(5, 0))
        
        self.preview_canvas = tk.Canvas(self.editor_frame, bg="#23272A", height=40, highlightthickness=0)
        self.preview_canvas.pack(fill=tk.X, pady=2)

        self.btn_update = ttk.Button(self.editor_frame, text="Update Text Globally", command=self.send_text_update)
        self.btn_update.pack(anchor=tk.E, pady=5)

        ttk.Separator(self.main_container, orient='horizontal').pack(fill=tk.X, pady=10)

        # 4. CONTENT PANES
        self.content_pane = tk.PanedWindow(self.main_container, orient=tk.HORIZONTAL, bg="#2C2F33", sashwidth=4)
        self.content_pane.pack(fill=tk.BOTH, expand=True)

        # Pane 1: Presets
        self.presets_frame = ttk.Frame(self.content_pane)
        self.content_pane.add(self.presets_frame, minsize=200)
        
        self.presets_header = ttk.Frame(self.presets_frame)
        self.presets_header.pack(fill=tk.X)
        ttk.Label(self.presets_header, text="Presets", style="Header.TLabel").pack(side=tk.LEFT, anchor=tk.W)
        ttk.Button(self.presets_header, text="+ Add", command=self.add_preset, width=6).pack(side=tk.RIGHT, padx=2)
        
        self.presets_listbox = tk.Listbox(self.presets_frame, bg="#23272A", fg="white", selectbackground="#7289DA", font=("Segoe UI", 10))
        self.presets_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        self.presets_listbox.bind("<<ListboxSelect>>", self.on_preset_select)
        self.presets_listbox.bind("<Button-3>", self.on_preset_right_click)
        
        self.refresh_presets_list()

        # Pane 2: Quick Palette (Categorized)
        self.quick_frame = ttk.Frame(self.content_pane)
        self.content_pane.add(self.quick_frame, minsize=400)
        
        self.quick_header = ttk.Frame(self.quick_frame)
        self.quick_header.pack(fill=tk.X)
        ttk.Label(self.quick_header, text="Quick Palette", style="Header.TLabel").pack(side=tk.LEFT, padx=5)
        
        self.quick_toolbar = ttk.Frame(self.quick_frame)
        self.quick_toolbar.pack(fill=tk.X, padx=5)
        
        ttk.Button(self.quick_toolbar, text="Sort: Name", command=lambda: self.sort_palettes("name"), width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.quick_toolbar, text="Sort: Usage", command=lambda: self.sort_palettes("usage"), width=10).pack(side=tk.LEFT, padx=2)
        
        # Storage Toggle
        self.btn_storage = ttk.Button(self.quick_toolbar, text="Show Storage", command=self.toggle_storage, width=12)
        self.btn_storage.pack(side=tk.RIGHT, padx=2)
        
        ttk.Button(self.quick_toolbar, text="Sync", command=self.start_sync_emojis, width=6).pack(side=tk.RIGHT, padx=2)
        ttk.Button(self.quick_toolbar, text="+ Import", command=self.import_emoji, width=8).pack(side=tk.RIGHT, padx=2)

        # Scrollable Area for Categories
        self.quick_canvas = tk.Canvas(self.quick_frame, bg="#2C2F33", highlightthickness=0)
        self.quick_scrollbar = ttk.Scrollbar(self.quick_frame, orient="vertical", command=self.quick_canvas.yview)
        self.quick_scrollable_frame = ttk.Frame(self.quick_canvas)
        self.quick_window_id = self.quick_canvas.create_window((0, 0), window=self.quick_scrollable_frame, anchor="nw")
        
        self.quick_scrollable_frame.bind("<Configure>", lambda e: self.quick_canvas.configure(scrollregion=self.quick_canvas.bbox("all")))
        self.quick_canvas.bind("<Configure>", lambda e: self.on_canvas_resize(e, "quick"))
        self.quick_canvas.configure(yscrollcommand=self.quick_scrollbar.set)
        
        self.quick_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.quick_scrollbar.pack(side="right", fill="y", pady=5)

        # Pane 3: Hidden/Storage (Initially Hidden)
        self.hidden_frame = ttk.Frame(self.content_pane)
        # Not added to content_pane initially
        
        ttk.Label(self.hidden_frame, text="Storage / Hidden", style="Header.TLabel").pack(anchor=tk.W, padx=5)
        
        self.hidden_canvas = tk.Canvas(self.hidden_frame, bg="#23272A", highlightthickness=0) 
        self.hidden_scrollbar = ttk.Scrollbar(self.hidden_frame, orient="vertical", command=self.hidden_canvas.yview)
        self.hidden_scrollable_frame = ttk.Frame(self.hidden_canvas)
        self.hidden_window_id = self.hidden_canvas.create_window((0, 0), window=self.hidden_scrollable_frame, anchor="nw")
        
        self.hidden_scrollable_frame.bind("<Configure>", lambda e: self.hidden_canvas.configure(scrollregion=self.hidden_canvas.bbox("all")))
        self.hidden_canvas.bind("<Configure>", lambda e: self.on_canvas_resize(e, "hidden"))
        self.hidden_canvas.configure(yscrollcommand=self.hidden_scrollbar.set)
        
        self.hidden_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.hidden_scrollbar.pack(side="right", fill="y", pady=5)

        self.render_palettes()
        self.poll_api()

    def toggle_storage(self):
        if self.storage_visible:
            self.content_pane.forget(self.hidden_frame)
            self.btn_storage.config(text="Show Storage")
            self.storage_visible = False
        else:
            self.content_pane.add(self.hidden_frame, minsize=200)
            self.btn_storage.config(text="Hide Storage")
            self.storage_visible = True

    def on_canvas_resize(self, event, palette_type):
        canvas = self.quick_canvas if palette_type == "quick" else self.hidden_canvas
        window_id = self.quick_window_id if palette_type == "quick" else self.hidden_window_id
        canvas.itemconfig(window_id, width=event.width)

        # Calculate Columns
        cell_width = 40
        new_cols = max(1, event.width // cell_width)
        
        current_cols = getattr(self, f"cols_{palette_type}")
        if abs(new_cols - current_cols) > 0:
             setattr(self, f"cols_{palette_type}", new_cols)
             self.render_palettes()

    # --- IMAGE HELPERS ---
    def load_icon(self, name):
        if name in self.icon_cache:
            return self.icon_cache[name]
            
        found_path = None
        for ext in [".png", ".gif", ".jpg", ".jpeg", ".webp"]:
            path = os.path.join(EMOJI_IMG_DIR, name + ext)
            if os.path.exists(path):
                found_path = path
                break
        if not found_path: return None
            
        try:
            img = Image.open(found_path)
            if hasattr(img, 'is_animated') and img.is_animated: img.seek(0)
            img = img.resize((32, 32), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.icon_cache[name] = photo
            return photo
        except: return None

    def render_palettes(self):
        # Clear Quick Frame
        for w in self.quick_scrollable_frame.winfo_children(): w.destroy()
        self.category_frames.clear()
        
        # Render Categories
        order = ["Yami", "Calyptra", "Riven", "SΛTVRN", "Other"]
        for cat in order:
            if cat not in palette_layout["categories"]: continue
            
            # Header
            lbl = ttk.Label(self.quick_scrollable_frame, text=cat, style="Category.TLabel")
            lbl.pack(fill=tk.X, padx=5, pady=(10, 2))
            
            # Grid Frame
            f = ttk.Frame(self.quick_scrollable_frame)
            f.pack(fill=tk.X, padx=5)
            self.category_frames[cat] = f
            
            self._render_grid(f, palette_layout["categories"][cat], cat, self.cols_quick)

        # Render Hidden
        for w in self.hidden_scrollable_frame.winfo_children(): w.destroy()
        self._render_grid(self.hidden_scrollable_frame, palette_layout["hidden"], "hidden", self.cols_hidden)

    def _render_grid(self, parent, item_list, category, max_cols):
        row = 0
        col = 0
        
        bg_color = "#23272A" if category=="hidden" else "#2C2F33"
        
        for name in item_list:
            if name not in emoji_map: continue
            
            discord_str = emoji_map[name]
            icon = self.load_icon(name)
            
            if icon:
                w = tk.Label(parent, image=icon, bg=bg_color)
            else:
                disp = name[:2]
                w = tk.Label(parent, text=disp, font=("Segoe UI", 10), bg=bg_color, fg="white", width=4)
            
            # Bindings
            w.bind("<Button-1>", lambda e, c=discord_str, n=name, cat=category: self.on_emoji_click(e, c, n, cat))
            w.bind("<B1-Motion>", self.drag_manager.on_motion)
            w.bind("<ButtonRelease-1>", self.drag_manager.stop_drag)
            w.bind("<Enter>", lambda e, n=name: self.status_label.config(text=f"Emoji: {n} (Uses: {palette_layout['use_counts'].get(name, 0)})"))
            w.bind("<Leave>", lambda e: self.status_label.config(text="Online"))
            
            w.grid(row=row, column=col, padx=2, pady=2)
            
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
    
    def sort_palettes(self, method):
        def sort_list(lst):
            if method == "name":
                lst.sort(key=lambda x: x.lower())
            elif method == "usage":
                lst.sort(key=lambda x: (-palette_layout["use_counts"].get(x, 0), x.lower()))
        
        # Sort each category
        for cat in palette_layout["categories"]:
            sort_list(palette_layout["categories"][cat])
            
        sort_list(palette_layout["hidden"])
        save_palette_layout()
        self.render_palettes()

    def on_emoji_click(self, event, code, name, category):
        self.drag_manager.start_drag(event, name, category)
        if not self.drag_manager.is_dragging:
            # Immediate click action
            self.text_entry.insert(tk.END, f" {code} ")
            self.update_preview()

    def start_sync_emojis(self):
        self.status_label.config(text="Syncing Emojis...")
        threading.Thread(target=self.sync_emojis, daemon=True).start()

    def sync_emojis(self):
        resp = client.get_emojis()
        if "error" in resp:
            self.after(0, lambda: messagebox.showerror("Sync Error", resp["error"]))
            self.after(0, lambda: self.status_label.config(text="Sync Failed"))
            return

        emojis = resp.get("emojis", [])
        count_new = 0
        
        layout_changed = False
        for emo in emojis:
            name = emo["name"]
            emoji_map[name] = emo["string"]
            
            # Check existence in any category or hidden
            exists = False
            if name in palette_layout["hidden"]: exists = True
            for cat in palette_layout["categories"].values():
                if name in cat: exists = True; break
            
            if not exists:
                palette_layout["hidden"].append(name)
                count_new += 1
                layout_changed = True
            
            self._check_and_download_icon(name, emo["url"], emo["animated"])

        if layout_changed: save_palette_layout()
        self.after(0, self.render_palettes)
        self.after(0, lambda: self.status_label.config(text=f"Synced {count_new} new emojis (to Storage)."))

    def _check_and_download_icon(self, name, url, animated):
         for ext in [".png", ".gif", ".jpg", ".jpeg", ".webp"]:
             if os.path.exists(os.path.join(EMOJI_IMG_DIR, name + ext)): return
         
         try:
             img_resp = requests.get(url, timeout=10)
             if img_resp.status_code == 200:
                 ext = ".gif" if animated else ".png"
                 dest = os.path.join(EMOJI_IMG_DIR, name + ext)
                 with open(dest, "wb") as f: f.write(img_resp.content)
         except: pass

    def import_emoji(self):
        file_path = filedialog.askopenfilename(title="Select Image", filetypes=[("Images", "*.png;*.gif;*.jpg;*.webp")])
        if not file_path: return
        
        default_name = os.path.splitext(os.path.basename(file_path))[0]
        name = simpledialog.askstring("Emoji Name", "Enter Emoji Name:", initialvalue=default_name)
        if not name: return
        
        discord_id = simpledialog.askstring("Discord ID", f"Enter ID for {name}:", initialvalue=f"<:{name}:12345>")
        if not discord_id: return
        
        try:
            img = Image.open(file_path)
            if hasattr(img, 'is_animated') and img.is_animated: img.seek(0)
            dest = os.path.join(EMOJI_IMG_DIR, f"{name}.png")
            img.save(dest, "PNG")
            
            emoji_map[name] = discord_id
            with open(EMOJI_DB_FILE, "w") as f: json.dump(emoji_map, f, indent=4)
            
            if name not in palette_layout["categories"]["Other"]:
                palette_layout["categories"]["Other"].append(name)
                save_palette_layout()
            
            self.icon_cache.pop(name, None)
            self.render_palettes()
        except Exception as e: messagebox.showerror("Error", str(e))

    def clear_text(self):
        self.text_entry.delete(0, tk.END)
        self.update_preview()

    def remove_emoji_from_bar(self, emoji_str):
        current = self.text_entry.get()
        if emoji_str in current:
            new_text = current.replace(emoji_str, "", 1)
            new_text = new_text.replace("  ", " ")
            self.text_entry.delete(0, tk.END)
            self.text_entry.insert(0, new_text)
            self.update_preview()

    def update_preview(self, event=None):
        self.preview_canvas.delete("all")
        text = self.text_entry.get()
        
        x = 5
        y = 20
        
        sorted_emojis = sorted(emoji_map.items(), key=lambda x: len(x[1]), reverse=True)
        temp_text = text
        for name, code in sorted_emojis:
            temp_text = temp_text.replace(code, f"|{name}|")
            
        parts = re.split(r'\|(.*?)\|', temp_text)
        
        for part in parts:
            if part in emoji_map:
                icon = self.load_icon(part)
                discord_str = emoji_map[part]
                
                item_id = None
                if icon:
                    item_id = self.preview_canvas.create_image(x, y, image=icon, anchor="w")
                    x += 34
                else:
                    item_id = self.preview_canvas.create_text(x, y, text=f"[{part}]", fill="#7289DA", anchor="w", font=("Segoe UI", 9))
                    x += 60
                
                if item_id:
                    self.preview_canvas.tag_bind(item_id, "<Button-3>", lambda e, s=discord_str: self.remove_emoji_from_bar(s))
                    
            else:
                self.preview_canvas.create_text(x, y, text=part, fill="white", anchor="w", font=("Consolas", 10))
                width = len(part) * 8
                x += width

    # ... (Presets, Poll API, Send State, Send Text, Update UI - Same as before)
    def refresh_presets_list(self):
        self.presets_listbox.delete(0, tk.END)
        for name in sorted(presets.keys()):
             self.presets_listbox.insert(tk.END, name)

    def add_preset(self):
        text = self.text_entry.get()
        if not text: return
        name = simpledialog.askstring("Save Preset", "Enter name for this preset:")
        if name:
            presets[name] = text
            save_presets()
            self.refresh_presets_list()

    def on_preset_select(self, event):
        selection = self.presets_listbox.curselection()
        if selection:
            name = self.presets_listbox.get(selection[0])
            text = presets.get(name)
            if text:
                self.text_entry.delete(0, tk.END)
                self.text_entry.insert(0, text)
                self.update_preview()

    def on_preset_right_click(self, event):
        self.presets_listbox.selection_clear(0, tk.END)
        index = self.presets_listbox.nearest(event.y)
        self.presets_listbox.selection_set(index)
        self.presets_listbox.activate(index)
        
        name = self.presets_listbox.get(index)
        if messagebox.askyesno("Delete Preset", f"Delete preset '{name}'?"):
            del presets[name]
            save_presets()
            self.refresh_presets_list()

    def poll_api(self):
        def _poll():
            status = client.get_status()
            self.after(0, lambda: self.update_ui(status, None))
        threading.Thread(target=_poll, daemon=True).start()
        self.after(2000, self.poll_api)

    def update_ui(self, status, bars):
        if "error" in status:
            self.status_indicator.config(fg="red")
            self.status_label.config(text=f"Offline ({status['error']})")
        else:
            self.status_indicator.config(fg="green")
            self.status_label.config(text=f"Online: {status.get('user', 'NyxOS')}")
            self.latency_label.config(text=f"Ping: {status.get('latency')}ms")

    def send_state(self, action):
        threading.Thread(target=client.set_global_state, args=(action,), daemon=True).start()

    def send_text_update(self):
        text = self.text_entry.get()
        if not text: return
        
        for name, code in emoji_map.items():
            if code in text:
                palette_layout["use_counts"][name] = palette_layout["use_counts"].get(name, 0) + 1
        save_palette_layout()
        
        def _send():
            resp = client.set_global_text(text)
            if "error" in resp:
                self.after(0, lambda: messagebox.showerror("Error", resp["error"]))
            else:
                self.after(0, self.bell)
                self.after(0, lambda: self.status_label.config(text="Update Sent!"))
                self.after(2000, lambda: self.status_label.config(text=f"Online: {client.get_status().get('user', 'NyxOS')}"))

        threading.Thread(target=_send, daemon=True).start()

if __name__ == "__main__":
    try:
        app = NyxControlApp()
        app.mainloop()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        input("Press Enter to exit...")