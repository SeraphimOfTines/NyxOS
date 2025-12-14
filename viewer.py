import streamlit as st
import chromadb
import pandas as pd

# 1. Setup the Title
st.title("Chroma DB Viewer")

# 2. Connect to the Database
# !!! IMPORTANT: Check this path matches your actual folder !!!
DB_PATH = "./chroma_db" 

try:
    client = chromadb.PersistentClient(path=DB_PATH)
    
    # 3. List Collections
    collections = client.list_collections()
    collection_names = [c.name for c in collections]
    
    if not collection_names:
        st.warning(f"No collections found in {DB_PATH}. Check your path.")
    else:
        selected_collection = st.selectbox("Select a Collection:", collection_names)
        
        # 4. Get Data
        if selected_collection:
            coll = client.get_collection(selected_collection)
            # Fetch first 10 items
            data = coll.get(limit=10)
            
            # 5. Display Data Table
            if data['ids']:
                df = pd.DataFrame({
                    'ID': data['ids'],
                    'Document': data['documents'],
                    # Convert metadata to string to avoid display errors
                    'Metadata': [str(m) for m in data['metadatas']], 
                })
                st.dataframe(df, use_container_width=True)
                st.write(f"Total items in collection: {coll.count()}")
            else:
                st.info("Collection is empty.")

except Exception as e:
    st.error(f"Error loading database: {e}")
