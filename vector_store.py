import chromadb
import logging
import config

logger = logging.getLogger("VectorStore")

class VectorStore:
    def __init__(self):
        self.client = None
        # We no longer hold a single collection ref, we fetch dynamically

    def connect(self):
        """Establishes connection to ChromaDB."""
        if self.client: return True
        try:
            db_url = getattr(config, "VECTOR_DB_URL", "http://localhost:8250")
            if db_url.startswith("http"):
                host, port = db_url.replace("http://", "").split(":")
                self.client = chromadb.HttpClient(host=host, port=int(port))
            else:
                self.client = chromadb.PersistentClient(path=db_url)
            
            logger.info(f"Connected to Vector DB at {db_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Vector DB: {e}")
            return False

    def search(self, query, n_results=3):
        """
        Searches ALL collections in the DB (OpenWebUI + Nyx) and returns the best matches.
        This allows Nyx to 'see' documents uploaded via OpenWebUI.
        """
        if not self.connect(): return []

        try:
            # 1. List all collections
            collections = self.client.list_collections()
            if not collections: 
                logger.warning("Search: No collections found in DB.")
                return []

            all_results = []

            # 2. Query each collection
            # OpenWebUI usually creates one collection per document or groups them.
            # We limit n_results per collection to keep it fast.
            for col_obj in collections:
                try:
                    # We can't query if collection is empty, but query handles it gracefully usually
                    count = col_obj.count()
                    if count == 0: continue
                    
                    res = col_obj.query(
                        query_texts=[query],
                        n_results=min(2, count) # Get top 2 from each doc
                    )
                    
                    if res['documents'] and res['documents'][0]:
                        for i, doc in enumerate(res['documents'][0]):
                            dist = res['distances'][0][i] if res['distances'] else 1.0
                            meta = res['metadatas'][0][i] if res['metadatas'] else {}
                            
                            # OpenWebUI often puts filename in metadata 'source' or 'name'
                            source = meta.get('source') or meta.get('name') or col_obj.name
                            
                            all_results.append({
                                "text": doc,
                                "metadata": meta,
                                "distance": dist,
                                "source": source
                            })
                except Exception as e:
                    # logger.warning(f"Collection {col_obj.name} query failed: {e}")
                    pass # Skip collections that fail query (e.g. different embedding dimension?)

            # 3. Sort & Prune
            # Chroma distances: Lower is better (usually L2 or Cosine distance)
            all_results.sort(key=lambda x: x['distance'])
            
            final_results = all_results[:n_results]
            if final_results:
                logger.info(f"Vector Search '{query[:30]}...' found {len(final_results)} matches. Top: {final_results[0]['source']} ({final_results[0]['distance']:.4f})")
            else:
                logger.info(f"Vector Search '{query[:30]}...' returned NO matches.")
                
            return final_results

        except Exception as e:
            logger.error(f"Global Vector search failed: {e}")
            return []

    # Disable write methods since we are reading OpenWebUI's brain
    def add_text(self, *args, **kwargs):
        logger.warning("Nyx ingestion is disabled. Use OpenWebUI to upload documents.")
        return False

# Global Instance
store = VectorStore()