import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import threading
import time
import json
import os
import sys
import subprocess
import re

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

client = NyxClient()

# ==========================================
# GUI APPLICATION
# ==========================================
class NyxControlApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NyxOS Control Center")
        self.geometry("1000x700")
        self.configure(bg="#2C2F33") 

        # Image Cache (Prevent GC)
        self.icon_cache = {}

        # Styles
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#2C2F33")
        style.configure("TLabel", background="#2C2F33", foreground="white", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 9), background="#7289DA", foreground="white")
        style.map("TButton", background=[('active', '#677BC4')])
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#7289DA")

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
        
        self.text_entry = tk.Entry(self.editor_frame, bg="#23272A", fg="white", insertbackground="white", font=("Consolas", 11))
        self.text_entry.pack(fill=tk.X, pady=5)
        self.text_entry.bind("<KeyRelease>", self.update_preview) # Live preview
        self.text_entry.bind("<Return>", lambda e: self.send_text_update())
        
        # Preview Canvas
        self.preview_canvas = tk.Canvas(self.editor_frame, bg="#23272A", height=40, highlightthickness=0)
        self.preview_canvas.pack(fill=tk.X, pady=2)

        self.btn_update = ttk.Button(self.editor_frame, text="Update Text Globally", command=self.send_text_update)
        self.btn_update.pack(anchor=tk.E, pady=5)

        ttk.Separator(self.main_container, orient='horizontal').pack(fill=tk.X, pady=10)

        # 4. RACK & PALETTE (Split Pane)
        self.content_pane = tk.PanedWindow(self.main_container, orient=tk.HORIZONTAL, bg="#2C2F33", sashwidth=4)
        self.content_pane.pack(fill=tk.BOTH, expand=True)

        # Left: The Rack (Active Bars)
        self.rack_frame = ttk.Frame(self.content_pane)
        self.content_pane.add(self.rack_frame)
        
        ttk.Label(self.rack_frame, text="Active Uplinks", style="Header.TLabel").pack(anchor=tk.W)
        
        self.bars_listbox = tk.Listbox(self.rack_frame, bg="#23272A", fg="white", selectbackground="#7289DA", font=("Segoe UI", 10))
        self.bars_listbox.pack(fill=tk.BOTH, expand=True, pady=5)

        # Right: The Palette (Tools)
        self.palette_frame = ttk.Frame(self.content_pane)
        self.content_pane.add(self.palette_frame)
        
        # Palette Header with Import Button
        self.palette_header = ttk.Frame(self.palette_frame)
        self.palette_header.pack(fill=tk.X)
        
        ttk.Label(self.palette_header, text="Emoji Palette", style="Header.TLabel").pack(side=tk.LEFT, padx=5)
        ttk.Button(self.palette_header, text="+ Import", command=self.import_emoji, width=8).pack(side=tk.RIGHT, padx=5)

        self.emoji_grid_frame = ttk.Frame(self.palette_frame)
        self.emoji_grid_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Scrollable Canvas for Emoji Grid
        self.emoji_canvas = tk.Canvas(self.emoji_grid_frame, bg="#2C2F33", highlightthickness=0)
        self.emoji_scrollbar = ttk.Scrollbar(self.emoji_grid_frame, orient="vertical", command=self.emoji_canvas.yview)
        self.emoji_scrollable_frame = ttk.Frame(self.emoji_canvas)

        self.emoji_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.emoji_canvas.configure(scrollregion=self.emoji_canvas.bbox("all"))
        )

        self.emoji_canvas.create_window((0, 0), window=self.emoji_scrollable_frame, anchor="nw")
        self.emoji_canvas.configure(yscrollcommand=self.emoji_scrollbar.set)

        self.emoji_canvas.pack(side="left", fill="both", expand=True)
        self.emoji_scrollbar.pack(side="right", fill="y")
        
        self.init_emoji_palette()

        # Start Polling
        self.poll_api()

    # --- IMAGE HELPERS ---
    def load_icon(self, name):
        """Loads an icon from disk, processing GIFs/resizing."""
        if name in self.icon_cache:
            return self.icon_cache[name]
            
        # Try extensions
        found_path = None
        for ext in [".png", ".gif", ".jpg", ".jpeg", ".webp"]:
            path = os.path.join(EMOJI_IMG_DIR, name + ext)
            if os.path.exists(path):
                found_path = path
                break
                
        if not found_path:
            return None
            
        try:
            img = Image.open(found_path)
            # If GIF, get first frame
            if hasattr(img, 'is_animated') and img.is_animated:
                img.seek(0)
            
            # Resize
            img = img.resize((32, 32), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.icon_cache[name] = photo
            return photo
        except Exception as e:
            print(f"Failed to load image {name}: {e}")
            return None

    def init_emoji_palette(self):
        # Clear existing
        for widget in self.emoji_scrollable_frame.winfo_children():
            widget.destroy()

        # Standard Unicode Fallbacks
        defaults = ["🦊", "🎵", "💤", "👁️", "💻", "🎮", "✨", "💀"]
        
        # Combine DB and Defaults
        items = list(emoji_map.keys())
        # Add unicode items that aren't in DB if needed, but let's focus on DB
        
        row = 0
        col = 0
        max_cols = 5
        
        # 1. Custom Emojis
        for name in items:
            icon = self.load_icon(name)
            discord_str = emoji_map[name]
            
            if icon:
                btn = tk.Button(self.emoji_scrollable_frame, image=icon, 
                                bg="#23272A", relief="flat",
                                command=lambda c=discord_str: self.on_emoji_click(c))
            else:
                # Text fallback (Shorten name)
                disp = name[:2]
                btn = tk.Button(self.emoji_scrollable_frame, text=disp, font=("Segoe UI", 10),
                                bg="#23272A", fg="white", relief="flat", width=4,
                                command=lambda c=discord_str: self.on_emoji_click(c))
                
            btn.grid(row=row, column=col, padx=2, pady=2)
            
            # Tooltip (Basic hover via status label)
            btn.bind("<Enter>", lambda e, n=name: self.status_label.config(text=f"Emoji: {n}"))
            btn.bind("<Leave>", lambda e: self.status_label.config(text="Online"))

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # 2. Unicode Defaults (Append after)
        for char in defaults:
            btn = tk.Button(self.emoji_scrollable_frame, text=char, font=("Segoe UI Emoji", 14), 
                            bg="#23272A", fg="white", relief="flat",
                            command=lambda c=char: self.on_emoji_click(c))
            btn.grid(row=row, column=col, padx=2, pady=2)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def import_emoji(self):
        """Dialog to import a new emoji."""
        file_path = filedialog.askopenfilename(title="Select Image", filetypes=[("Images", "*.png;*.gif;*.jpg;*.webp")])
        if not file_path: return
        
        # Ask for Name
        default_name = os.path.splitext(os.path.basename(file_path))[0]
        name = simpledialog.askstring("Emoji Name", "Enter Emoji Name (e.g. FoxxyLook):", initialvalue=default_name)
        if not name: return
        
        # Ask for ID
        discord_id = simpledialog.askstring("Discord ID", f"Enter Full Discord String for {name}:", initialvalue=f"<:{name}:12345>")
        if not discord_id: return
        
        try:
            # 1. Copy/Process Image
            img = Image.open(file_path)
            if hasattr(img, 'is_animated') and img.is_animated:
                img.seek(0)
            
            # Save as PNG to emojis dir
            dest = os.path.join(EMOJI_IMG_DIR, f"{name}.png")
            img.save(dest, "PNG")
            
            # 2. Update DB
            emoji_map[name] = discord_id
            with open(EMOJI_DB_FILE, "w") as f:
                json.dump(emoji_map, f, indent=4)
            
            # 3. Refresh
            self.icon_cache.pop(name, None) # Clear cache
            self.init_emoji_palette()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import: {e}")

    def update_preview(self, event=None):
        """Renders a preview of the text with icons."""
        self.preview_canvas.delete("all")
        text = self.text_entry.get()
        
        x = 5
        y = 20
        
        # Regex to find emojis: <a:Name:ID> or <:Name:ID> or generic unicode
        # Simplification: Split by spaces and check against DB map values?
        # Better: Tokenize.
        
        # Let's iterate through known emojis and replace them with placeholders for splitting
        # This is complex for a simple preview.
        # Strategy: Check if any stored Discord String is present in text.
        
        # We will tokenize by finding the Discord strings in the text.
        # Sort emojis by length descending to match longest first
        sorted_emojis = sorted(emoji_map.items(), key=lambda x: len(x[1]), reverse=True)
        
        # We need to split the text into chunks of (Text, ImageObj)
        chunks = []
        
        # Naive parsing:
        # Replace all emoji strings with special marker |EMOJI:NAME|
        temp_text = text
        for name, code in sorted_emojis:
            temp_text = temp_text.replace(code, f"|{name}|")
            
        # Split by markers
        parts = re.split(r'\|(.*?)\|', temp_text)
        
        for part in parts:
            if part in emoji_map:
                # It's an emoji name
                icon = self.load_icon(part)
                if icon:
                    self.preview_canvas.create_image(x, y, image=icon, anchor="w")
                    x += 34
                else:
                    # Fallback text
                    self.preview_canvas.create_text(x, y, text=f"[{part}]", fill="#7289DA", anchor="w", font=("Segoe UI", 9))
                    x += 60
            else:
                # It's regular text
                self.preview_canvas.create_text(x, y, text=part, fill="white", anchor="w", font=("Consolas", 10))
                # Calc width (approx)
                width = len(part) * 8
                x += width

    # --- LOGIC ---

    def poll_api(self):
        def _poll():
            status = client.get_status()
            bars = client.get_bars()
            self.after(0, lambda: self.update_ui(status, bars))
            
        threading.Thread(target=_poll, daemon=True).start()
        self.after(2000, self.poll_api)

    def update_ui(self, status, bars):
        # Update Status Header
        if "error" in status:
            self.status_indicator.config(fg="red")
            self.status_label.config(text=f"Offline ({status['error']})")
            self.latency_label.config(text="")
        else:
            self.status_indicator.config(fg="green")
            self.status_label.config(text=f"Online: {status.get('user', 'NyxOS')}")
            self.latency_label.config(text=f"Ping: {status.get('latency')}ms")

        # Update Bars List
        if bars and "bars" in bars:
            current_selection = self.bars_listbox.curselection()
            selected_idx = current_selection[0] if current_selection else None
            
            self.bars_listbox.delete(0, tk.END)
            for bar in bars['bars']:
                entry = f"[{bar['category']}] #{bar['channel_name']}"
                self.bars_listbox.insert(tk.END, entry)
            
            if selected_idx is not None and selected_idx < self.bars_listbox.size():
                self.bars_listbox.selection_set(selected_idx)

    def send_state(self, action):
        threading.Thread(target=client.set_global_state, args=(action,), daemon=True).start()

    def send_text_update(self):
        text = self.text_entry.get()
        if not text: return
        threading.Thread(target=client.set_global_text, args=(text,), daemon=True).start()
        messagebox.showinfo("Sent", "Update request sent to bot.")

    def on_emoji_click(self, code):
        self.text_entry.insert(tk.END, f" {code} ")
        self.update_preview()

if __name__ == "__main__":
    try:
        app = NyxControlApp()
        app.mainloop()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror("NyxControl Error", str(e))
        except: pass
        input("Press Enter to exit...")