#!/usr/bin/env python3
import sqlite3
import shutil
import os
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
import config

app = Flask(__name__, template_folder='templates')

DB_PATH = config.DATABASE_FILE

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def backup_database():
    if not os.path.exists(DB_PATH):
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB_PATH}.{timestamp}.bak"
    try:
        shutil.copy(DB_PATH, backup_path)
        print(f"✅ Safety Backup created: {backup_path}")
    except Exception as e:
        print(f"❌ Backup Failed: {e}")

# --- API ---

@app.route('/')
def index():
    return render_template('db_viewer.html')

@app.route('/api/tables')
def list_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row['name'] for row in cursor.fetchall() if row['name'] != 'sqlite_sequence']
    conn.close()
    return jsonify({'tables': tables})

@app.route('/api/table/<table_name>')
def get_table_data(table_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get PK
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns_info = cursor.fetchall()
    pk = "rowid"
    columns = []
    
    for col in columns_info:
        columns.append(col['name'])
        if col['pk'] == 1:
            pk = col['name']
    
    # Fetch Data
    try:
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({'rows': rows, 'pk': pk, 'columns': columns})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/row', methods=['POST'])
def update_row():
    data = request.json
    table = data.get('table')
    pk_col = data.get('pk_col')
    pk_val = data.get('pk_val')
    row_data = data.get('data') # Dict of col->val

    if not all([table, pk_col, pk_val, row_data]):
        return jsonify({'error': 'Missing fields'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        set_clause = []
        values = []
        for col, val in row_data.items():
            set_clause.append(f"{col} = ?")
            values.append(val)
        
        values.append(pk_val)
        
        query = f"UPDATE {table} SET {', '.join(set_clause)} WHERE {pk_col} = ?"
        cursor.execute(query, values)
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/row', methods=['DELETE'])
def delete_row():
    table = request.args.get('table')
    pk_col = request.args.get('pk')
    pk_val = request.args.get('val')

    if not all([table, pk_col, pk_val]):
        return jsonify({'error': 'Missing args'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = f"DELETE FROM {table} WHERE {pk_col} = ?"
        cursor.execute(query, (pk_val,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Starting NyxOS Database Viewer Web Server...")
    backup_database()
    print(f"🌍 Serving at http://localhost:5942")
    # Using 0.0.0.0 allows internal network access if firewall permits
    app.run(host='0.0.0.0', port=5942, debug=True)
