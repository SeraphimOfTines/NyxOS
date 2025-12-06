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
        """Ingests text into the vector database, automatically chunking large inputs."""
        if not self.collection:
            if not self.connect(): return False

        try:
            # Chunking Logic
            CHUNK_SIZE = 1000
            OVERLAP = 100
            
            chunks = []
            if len(text) > CHUNK_SIZE:
                # Simple sliding window chunking
                start = 0
                while start < len(text):
                    end = start + CHUNK_SIZE
                    # Try to find a newline or space to break at
                    if end < len(text):
                        # Look for last newline in the chunk to avoid breaking sentences
                        last_newline = text.rfind('\n', start, end)
                        if last_newline != -1 and last_newline > start + (CHUNK_SIZE // 2):
                            end = last_newline + 1 # Include newline
                        else:
                            # Fallback to space
                            last_space = text.rfind(' ', start, end)
                            if last_space != -1 and last_space > start + (CHUNK_SIZE // 2):
                                end = last_space + 1
                    
                    chunk = text[start:end]
                    chunks.append(chunk)
                    # Move start pointer, respecting overlap
                    start = end - OVERLAP if end < len(text) else end
            else:
                chunks = [text]

            # Prepare Batch
            ids = [str(uuid.uuid4()) for _ in chunks]
            metadatas = []
            for i, _ in enumerate(chunks):
                meta = (metadata or {}).copy()
                meta["source"] = source
                meta["timestamp"] = datetime.now().isoformat()
                meta["chunk_index"] = i
                meta["total_chunks"] = len(chunks)
                metadatas.append(meta)

            self.collection.add(
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"Added {len(chunks)} chunks from {source}")
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
