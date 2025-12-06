
import chromadb
import config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Browser")

def browse_db():
    try:
        db_url = config.VECTOR_DB_URL
        print(f"Connecting to {db_url}...")
        
        if db_url.startswith("http"):
            host, port = db_url.replace("http://", "").split(":")
            client = chromadb.HttpClient(host=host, port=int(port))
        else:
            client = chromadb.PersistentClient(path=db_url)
            
        coll = client.get_or_create_collection("nyx_knowledge")
        print(f"Collection: {coll.name} (Count: {coll.count()})")
        
        # Get all documents
        # ChromaDB API 'get' without ids returns everything if limit not exceeded
        data = coll.get()
        
        ids = data['ids']
        metadatas = data['metadatas']
        documents = data['documents']
        
        print(f"\nTotal Documents: {len(ids)}")
        print("-" * 40)
        
        for i in range(len(ids)):
            print(f"ID: {ids[i]}")
            print(f"Metadata: {metadatas[i]}")
            print(f"Snippet: {documents[i][:100]}...")
            print("-" * 40)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    browse_db()
