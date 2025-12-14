import chromadb

# 1. Connect to the SAME database folder as your viewer
# (Make sure this path matches the one in viewer.py!)
DB_PATH = "./chroma_db"

client = chromadb.PersistentClient(path=DB_PATH)

# 2. Get or Create the Collection
# If "my_notes" doesn't exist, it creates it. If it does, it loads it.
collection = client.get_or_create_collection(name="my_notes")

print("Adding data...")

# 3. Add Data (Upsert)
# 'upsert' is safer than 'add' because it won't crash if IDs already exist;
# it just updates them.
collection.upsert(
    documents=[
        "This is a document about pineapple",
        "This is a document about oranges",
        "Linux is a powerful operating system",
        "Windows uses NTFS file systems"
    ],
    metadatas=[
        {"category": "fruit", "author": "Alice"},
        {"category": "fruit", "author": "Bob"},
        {"category": "tech", "os": "linux"},
        {"category": "tech", "os": "windows"}
    ],
    ids=["id1", "id2", "id3", "id4"]
)

print(f"Success! items in collection: {collection.count()}")
