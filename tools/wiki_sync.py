import requests
import chromadb
import logging
import sys
import re
import os

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] WikiSync: %(message)s')
logger = logging.getLogger("WikiSync")

def clean_html(raw_html):
    """Basic cleanup of HTML content from Wiki.js."""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def fetch_wiki_pages():
    """Fetches all pages from Wiki.js GraphQL endpoint."""
    url = f"{config.WIKI_JS_URL}/graphql"
    headers = {"Authorization": f"Bearer {config.WIKI_JS_API_KEY}"}
    
    # Wiki.js 2.x 'list' query doesn't allow 'content' field directly in listing for performance
    # We must fetch the list first, then fetch content for each ID.
    
    # 1. Fetch List
    list_query = """
    {
      pages {
        list (orderBy: TITLE) {
          id
          path
          title
          description
        }
      }
    }
    """
    
    try:
        logger.info("Fetching page list...")
        resp = requests.post(url, json={'query': list_query}, headers=headers)
        if resp.status_code != 200:
            logger.error(f"Failed to fetch list. Status: {resp.status_code}")
            return []
            
        data = resp.json()
        if 'errors' in data:
            logger.error(f"GraphQL Errors (List): {data['errors']}")
            return []
            
        page_list = data.get('data', {}).get('pages', {}).get('list', [])
        logger.info(f"Found {len(page_list)} pages. Fetching content...")
        
        full_pages = []
        
        # 2. Fetch Content for each page
        for item in page_list:
            pid = item['id']
            # Query for single page content
            content_query = """
            query ($id: Int!) {
              pages {
                single (id: $id) {
                  content
                }
              }
            }
            """
            
            r = requests.post(url, json={'query': content_query, 'variables': {'id': pid}}, headers=headers)
            if r.status_code == 200:
                c_data = r.json()
                content = c_data.get('data', {}).get('pages', {}).get('single', {}).get('content', '')
                item['content'] = content
                full_pages.append(item)
                logger.info(f" -> Fetched: {item['title']}")
            else:
                logger.warning(f"Failed to fetch content for ID {pid}")
                
        return full_pages

    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return []

def sync_to_chroma(pages):
    """Ingests pages into ChromaDB."""
    if not pages:
        logger.warning("No pages to sync.")
        return

    try:
        client = chromadb.HttpClient(host='localhost', port=8250)
        
        # We use a dedicated collection for Wiki content
        collection = client.get_or_create_collection(name="wiki_knowledge")
        
        logger.info(f"Syncing {len(pages)} pages to ChromaDB...")
        
        # Prepare Batch
        ids = []
        documents = []
        metadatas = []
        
        for page in pages:
            # We use 'path' or 'id' as the vector ID
            page_id = f"wiki_{page['id']}"
            
            # Content: Title + Description + Body
            # Clean HTML tags if content is HTML
            raw_content = page.get('content', '')
            text_content = clean_html(raw_content)
            
            full_text = f"Title: {page['title']}\nDescription: {page['description']}\n\n{text_content}"
            
            ids.append(page_id)
            documents.append(full_text)
            metadatas.append({
                "source": "Wiki.js",
                "title": page['title'],
                "path": page['path'],
                "url": f"{config.WIKI_JS_URL}/{page['path']}"
            })
            
        # Batch Upsert (Update or Insert)
        if ids:
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            logger.info("Sync complete!")
        
    except Exception as e:
        logger.error(f"ChromaDB Sync failed: {e}")

if __name__ == "__main__":
    logger.info("Starting Wiki.js Sync...")
    pages = fetch_wiki_pages()
    if pages:
        logger.info(f"Fetched {len(pages)} pages.")
        sync_to_chroma(pages)
    else:
        logger.warning("No pages found or fetch failed.")
