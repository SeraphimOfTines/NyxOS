import chromadb
from chromadb.config import Settings
import logging
import os
import uuid
from datetime import datetime
import config

logger = logging.getLogger("VectorStore")

class VectorStore:
    def __init__(self):
        self.client = None
        self.collection = None
        self.collection_name = "nyx_knowledge"

    def connect(self):
        """Establishes connection to ChromaDB."""
        try:
            # Check config for URL
            db_url = getattr(config, "VECTOR_DB_URL", "http://localhost:8000")
            
            logger.info(f"Connecting to Vector DB at {db_url}...")
            
            if db_url.startswith("http"):
                host, port = db_url.replace("http://", "").split(":")
                self.client = chromadb.HttpClient(host=host, port=int(port))
            else:
                # Fallback to local persistent (not shared with OpenWebUI easily, but safe fallback)
                # PersistentClient takes 'path' as first arg
                self.client = chromadb.PersistentClient(path=db_url)

            self.collection = self.client.get_or_create_collection(name=self.collection_name)
            logger.info(f"Connected to ChromaDB collection: {self.collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Vector DB: {e}")
            return False

    def add_text(self, text, source="user", metadata=None):
        """Ingests text into the vector database."""
        if not self.collection:
            if not self.connect(): return False

        try:
            doc_id = str(uuid.uuid4())
            meta = metadata or {}
            meta["source"] = source
            meta["timestamp"] = datetime.now().isoformat()

            self.collection.add(
                documents=[text],
                metadatas=[meta],
                ids=[doc_id]
            )
            logger.info(f"Added document {doc_id} from {source}")
            return True
        except Exception as e:
            logger.error(f"Failed to add document: {e}")
            return False

    def search(self, query, n_results=3):
        """Searches the vector database for relevant context."""
        if not self.collection:
            if not self.connect(): return []

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            # Chroma returns a dict of lists. We want to flatten it a bit for easy consumption.
            # results['documents'] is a list of lists (one list per query)
            # results['metadatas'] is a list of lists
            
            if not results['documents'] or not results['documents'][0]:
                return []

            output = []
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i] if results['metadatas'] else {}
                output.append({
                    "text": doc,
                    "metadata": meta,
                    "distance": results['distances'][0][i] if results['distances'] else 0
                })
            
            return output
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

# Global Instance
store = VectorStore()
