#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sqlite3
import shutil
import os
from datetime import datetime
import config

class DatabaseViewer(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("NyxOS Database Viewer & Editor")
        self.geometry("1200x800")
        
        # Style
        self.style = ttk.Style()
        self.style.theme_use('clam')

        self.db_path = config.DATABASE_FILE
        self.conn = None
        self.cursor = None
        self.current_table = None
        self.primary_keys = {} # Map table -> pk_column
        self.editing_enabled = False
        self.word_wrap = False
        self.current_row_id = None # Value of the PK for the selected row

        # --- SAFETY BACKUP ---
        self.backup_database()

        # --- LAYOUT ---
        # Top: Toolbar
        self.toolbar = ttk.Frame(self, padding=5)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        self.btn_refresh = ttk.Button(self.toolbar, text="🔄 Refresh", command=self.refresh_current_table)
        self.btn_refresh.pack(side=tk.LEFT, padx=2)

        self.btn_edit_mode = ttk.Button(self.toolbar, text="🔒 Edit Mode: OFF", command=self.toggle_edit_mode)
        self.btn_edit_mode.pack(side=tk.LEFT, padx=2)

        self.btn_wrap = ttk.Button(self.toolbar, text="📝 Wrap: OFF", command=self.toggle_wrap)
        self.btn_wrap.pack(side=tk.LEFT, padx=2)

        self.btn_save = ttk.Button(self.toolbar, text="💾 Save Changes", command=self.save_changes, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT, padx=2)

        self.btn_delete = ttk.Button(self.toolbar, text="❌ Delete Row", command=self.delete_row, state=tk.DISABLED)
        self.btn_delete.pack(side=tk.LEFT, padx=2)
        
        self.lbl_status = ttk.Label(self.toolbar, text="Ready", foreground="gray")
        self.lbl_status.pack(side=tk.RIGHT, padx=5)

        # Paned Window (Split List vs Editor)
        self.paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Upper: Table Notebook (Tabs for Tables)
        self.table_notebook = ttk.Notebook(self.paned)
        self.paned.add(self.table_notebook, weight=1)
        self.table_notebook.bind("<<NotebookTabChanged>>", self.on_table_change)

        # Lower: Detail Editor (Notebook for Columns)
        self.editor_frame = ttk.LabelFrame(self.paned, text="Detail Editor (Select a row to view)")
        self.paned.add(self.editor_frame, weight=1)

        # Editor Notebook (Columns as Tabs)
        self.column_notebook = ttk.Notebook(self.editor_frame)
        self.column_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # --- INITIALIZATION ---
        self.connect_db()
        self.load_schema()
        self.populate_table_tabs()

    def backup_database(self):
        if not os.path.exists(self.db_path):
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.db_path}.{timestamp}.bak"
        try:
            shutil.copy(self.db_path, backup_path)
            print(f"Safe Backup created: {backup_path}")
        except Exception as e:
            messagebox.showerror("Backup Failed", f"Could not create safety backup:\n{e}")

    def connect_db(self):
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect to DB:\n{e}")

    def load_schema(self):
        # Get all tables
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = self.cursor.fetchall()
        
        self.primary_keys = {}
        for t in tables:
            table_name = t[0]
            if table_name == "sqlite_sequence": continue
            
            # Get PK
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            columns = self.cursor.fetchall()
            pk = None
            for col in columns:
                # col[5] is the PK flag (1 if PK, 0 if not)
                if col[5] == 1:
                    pk = col[1]
                    break
            
            # If no explicit PK, use rowid (hidden) but better to warn
            if pk:
                self.primary_keys[table_name] = pk
            else:
                self.primary_keys[table_name] = "rowid" # Fallback

    def populate_table_tabs(self):
        # Clear existing
        for tab in self.table_notebook.tabs():
            self.table_notebook.forget(tab)

        for table, pk in self.primary_keys.items():
            frame = ttk.Frame(self.table_notebook)
            self.table_notebook.add(frame, text=table)
            
            # Create Treeview for this table
            # Scrollbars
            vsb = ttk.Scrollbar(frame, orient="vertical")
            hsb = ttk.Scrollbar(frame, orient="horizontal")
            
            tree = ttk.Treeview(frame, yscrollcommand=vsb.set, xscrollcommand=hsb.set, selectmode="browse")
            vsb.config(command=tree.yview)
            hsb.config(command=tree.xview)
            
            vsb.pack(side=tk.RIGHT, fill=tk.Y)
            hsb.pack(side=tk.BOTTOM, fill=tk.X)
            tree.pack(fill=tk.BOTH, expand=True)
            
            # Store ref to tree
            frame.tree = tree
            
            # Bind Select
            tree.bind("<<TreeviewSelect>>", self.on_row_select)

    def on_table_change(self, event):
        # Get current tab
        selected_tab = self.table_notebook.select()
        if not selected_tab: return
        
        # Index or Name?
        index = self.table_notebook.index(selected_tab)
        self.current_table = self.table_notebook.tab(index, "text")
        
        self.refresh_current_table()
        self.clear_editor()

    def refresh_current_table(self):
        if not self.current_table: return
        
        # Get Frame and Tree
        current_frame_id = self.table_notebook.select()
        current_frame = self.table_notebook.nametowidget(current_frame_id)
        tree = current_frame.tree
        
        # Clear Tree
        tree.delete(*tree.get_children())
        
        # Get Columns
        try:
            self.cursor.execute(f"SELECT * FROM {self.current_table}")
            rows = self.cursor.fetchall()
            
            if not rows:
                # Empty table, but we need columns
                self.cursor.execute(f"PRAGMA table_info({self.current_table})")
                cols = [c[1] for c in self.cursor.fetchall()]
            else:
                cols = rows[0].keys()
            
            tree['columns'] = cols
            tree['show'] = 'headings' # Hide phantom column
            
            for col in cols:
                tree.heading(col, text=col)
                tree.column(col, width=100, anchor=tk.W)
            
            # Populate
            for row in rows:
                # Convert row values to string, truncate for display
                display_vals = []
                for val in row:
                    s = str(val)
                    if len(s) > 50: s = s[:50] + "..."
                    display_vals.append(s)
                
                # Tag row with PK value for retrieval
                pk_col = self.primary_keys[self.current_table]
                pk_val = row[pk_col] if pk_col in row.keys() else None
                # If using rowid
                if pk_col == 'rowid':
                    # Need to fetch rowid? "SELECT rowid, * ..."
                    pass # Todo: Handle rowid logic if strictly needed. Most Nyx tables have PKs.
                
                tree.insert("", tk.END, values=display_vals, tags=(pk_val,))
                
            self.lbl_status.config(text=f"Loaded {len(rows)} rows from {self.current_table}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load table:\n{e}")

    def on_row_select(self, event):
        tree = event.widget
        selection = tree.selection()
        if not selection: return
        
        item = tree.item(selection[0])
        # We need the full data.
        # Treeview stores truncated data.
        # We assume the table has a PK we can query.
        
        pk_col = self.primary_keys.get(self.current_table)
        
        # Get PK Value.
        # Problem: 'tags' in insert() stores tags, not data.
        # Treeview doesn't support hidden data easily unless we map IID.
        # Let's assume the IID *is* the PK if possible, or we query by match.
        
        # Better: When loading, I stored pk_val in tags.
        # But tags is a list.
        tags = item.get('tags')
        if not tags: return
        
        pk_val = tags[0]
        self.current_row_id = pk_val
        
        self.load_editor(pk_val)

    def load_editor(self, pk_val):
        self.clear_editor()
        
        pk_col = self.primary_keys[self.current_table]
        
        query = f"SELECT * FROM {self.current_table} WHERE {pk_col} = ?"
        self.cursor.execute(query, (pk_val,))
        row = self.cursor.fetchone()
        
        if not row:
            self.lbl_status.config(text="Row not found!")
            return
            
        self.editor_widgets = {} # col_name -> text_widget
        
        for col_name in row.keys():
            val = row[col_name]
            
            # Create Tab for Column
            frame = ttk.Frame(self.column_notebook)
            self.column_notebook.add(frame, text=col_name)
            
            # Text Editor
            wrap_mode = tk.WORD if self.word_wrap else tk.NONE
            txt = scrolledtext.ScrolledText(frame, wrap=wrap_mode, font=("Consolas", 10))
            txt.pack(fill=tk.BOTH, expand=True)
            
            if val is not None:
                txt.insert(tk.END, str(val))
            
            # Lock if not editing
            if not self.editing_enabled:
                txt.config(state=tk.DISABLED, bg="#f0f0f0")
            
            self.editor_widgets[col_name] = txt
            
        self.lbl_status.config(text=f"Editing Row {pk_val}")
        
        if self.editing_enabled:
            self.btn_save.config(state=tk.NORMAL)
            self.btn_delete.config(state=tk.NORMAL)

    def clear_editor(self):
        for tab in self.column_notebook.tabs():
            self.column_notebook.forget(tab)
        self.editor_widgets = {}
        self.current_row_id = None
        self.btn_save.config(state=tk.DISABLED)
        self.btn_delete.config(state=tk.DISABLED)

    def toggle_edit_mode(self):
        self.editing_enabled = not self.editing_enabled
        
        if self.editing_enabled:
            self.btn_edit_mode.config(text="🔓 Edit Mode: ON", style="Accent.TButton")
            state = tk.NORMAL
            bg = "white"
            if self.current_row_id:
                self.btn_save.config(state=tk.NORMAL)
                self.btn_delete.config(state=tk.NORMAL)
        else:
            self.btn_edit_mode.config(text="🔒 Edit Mode: OFF", style="TButton")
            state = tk.DISABLED
            bg = "#f0f0f0"
            self.btn_save.config(state=tk.DISABLED)
            self.btn_delete.config(state=tk.DISABLED)
            
        # Update existing widgets
        for widget in self.editor_widgets.values():
            widget.config(state=state, bg=bg)

    def toggle_wrap(self):
        self.word_wrap = not self.word_wrap
        mode = tk.WORD if self.word_wrap else tk.NONE
        text = "📝 Wrap: ON" if self.word_wrap else "📝 Wrap: OFF"
        self.btn_wrap.config(text=text)
        
        for widget in self.editor_widgets.values():
            widget.config(wrap=mode)

    def save_changes(self):
        if not self.current_row_id or not self.editing_enabled: return
        
        pk_col = self.primary_keys[self.current_table]
        
        try:
            # Build Update Query
            cols = []
            vals = []
            
            for col, widget in self.editor_widgets.items():
                # Don't update PK usually, but sqlite allows it. 
                # Safety: If PK is edited, it might break? 
                # Let's allow editing everything.
                content = widget.get("1.0", tk.END).strip() # Strip trailing newline added by Text widget?
                # Actually Text widget adds a newline at end always.
                # If original data didn't have it, we might be adding one.
                # `get("1.0", "end-1c")` gets exact text.
                content = widget.get("1.0", "end-1c")
                
                cols.append(f"{col} = ?")
                vals.append(content)
            
            vals.append(self.current_row_id)
            
            query = f"UPDATE {self.current_table} SET {', '.join(cols)} WHERE {pk_col} = ?"
            self.cursor.execute(query, vals)
            self.conn.commit()
            
            self.lbl_status.config(text="Saved successfully!")
            self.refresh_current_table() # Refresh list
            
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save:\n{e}")

    def delete_row(self):
        if not self.current_row_id or not self.editing_enabled: return
        
        confirm = messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete row {self.current_row_id} from {self.current_table}?")
        if not confirm: return
        
        pk_col = self.primary_keys[self.current_table]
        try:
            query = f"DELETE FROM {self.current_table} WHERE {pk_col} = ?"
            self.cursor.execute(query, (self.current_row_id,))
            self.conn.commit()
            
            self.lbl_status.config(text="Row deleted.")
            self.refresh_current_table()
            self.clear_editor()
            
        except Exception as e:
            messagebox.showerror("Delete Error", f"Failed to delete:\n{e}")

if __name__ == "__main__":
    if not os.environ.get("DISPLAY"):
        print("❌ Error: No X11 DISPLAY found. This is a GUI tool.")
        print("   If you are running via SSH, verify X11 forwarding is enabled.")
    else:
        app = DatabaseViewer()
        app.mainloop()
