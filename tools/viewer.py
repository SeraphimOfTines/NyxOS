
import streamlit as st
import chromadb
import pandas as pd
import sys
import os
from datetime import datetime

# Hack to find config.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config

st.set_page_config(page_title="NyxOS Memory Viewer", layout="wide")

st.title("🧠 NyxOS Vector Memory Viewer")

# Sidebar for Connection
with st.sidebar:
    st.header("Connection")
    db_url = st.text_input("Vector DB URL", value=getattr(config, "VECTOR_DB_URL", "http://localhost:8250"))
    if st.button("Connect"):
        st.session_state.db_url = db_url
        st.rerun()

if 'db_url' not in st.session_state:
    st.session_state.db_url = getattr(config, "VECTOR_DB_URL", "http://localhost:8250")

@st.cache_resource
def get_client(url):
    if url.startswith("http"):
        host, port = url.replace("http://", "").split(":")
        return chromadb.HttpClient(host=host, port=int(port))
    else:
        return chromadb.PersistentClient(path=url)

try:
    client = get_client(st.session_state.db_url)
    coll = client.get_or_create_collection("nyx_knowledge")
    
    st.success(f"Connected to: **{st.session_state.db_url}** | Collection: **{coll.name}**")
    
    # Stats
    count = coll.count()
    st.metric("Total Memories", count)
    
    # Search
    query = st.text_input("Search Memories", placeholder="Type to semantic search...")
    
    if query:
        results = coll.query(query_texts=[query], n_results=10)
        
        # Flatten results
        data = []
        if results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i] if results['metadatas'] else {}
                dist = results['distances'][0][i] if results['distances'] else 0
                data.append({
                    "ID": results['ids'][0][i],
                    "Distance": f"{dist:.4f}",
                    "Source": meta.get("source", "Unknown"),
                    "Content": doc,
                    "Metadata": meta
                })
        
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("No results found.")
            
    else:
        # Browse Mode (Get latest)
        # Chroma doesn't support "get latest" easily without IDs, so we get all (up to limit)
        limit = st.slider("Rows to fetch", 10, 1000, 50)
        data = coll.get(limit=limit)
        
        if data['ids']:
            rows = []
            for i in range(len(data['ids'])):
                rows.append({
                    "ID": data['ids'][i],
                    "Source": data['metadatas'][i].get("source", "Unknown"),
                    "Content": data['documents'][i],
                    "Metadata": data['metadatas'][i]
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("Collection is empty.")

except Exception as e:
    st.error(f"Connection Failed: {e}")
