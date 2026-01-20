#\!/usr/bin/env python3
import psycopg2
import requests
import json
import re
import sys
from typing import List, Dict
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'companies_db',
    'user': 'mark',
    'password': 'mark123'
}

def extract_keywords(description: str) -> List[str]:
    """Extract keywords from patent description"""
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                  'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 
                  'those', 'such', 'wherein', 'whereby', 'thereof', 'comprising'}
    
    words = re.findall(r'\b[a-z]+\b', description.lower())
    keyword_count = {}
    
    for word in words:
        if len(word) >= 3 and word not in stop_words:
            keyword_count[word] = keyword_count.get(word, 0) + 1
    
    sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
    return [word for word, count in sorted_keywords[:15]]

def search_patents(keywords: List[str], limit: int = 50) -> List[Dict]:
    """Search patents in database"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Build search query
        conditions = []
        params = []
        
        # Search for any keyword match
        for keyword in keywords:
            conditions.append("LOWER(invention_title) LIKE %s")
            params.append(f'%{keyword}%')
        
        query = f"""
        SELECT DISTINCT 
            p.id,
            p.pub_number,
            p.invention_title,
            p.pub_date,
            p.app_number,
            COUNT(*) OVER() as total_matches
        FROM publication p
        WHERE {' OR '.join(conditions)}
        ORDER BY p.pub_date DESC NULLS LAST
        LIMIT %s
        """
        params.append(limit)
        
        logger.info(f"Searching with {len(keywords)} keywords")
        cur.execute(query, params)
        
        results = []
        for row in cur.fetchall():
            results.append({
                'id': str(row[0]),
                'pub_number': row[1],
                'title': row[2],
                'pub_date': str(row[3]) if row[3] else None,
                'app_number': row[4],
                'total_matches': row[5]
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_patent_parties(patent_ids: List[str]) -> Dict[str, Dict]:
    """Get parties (inventors/assignees) for patents"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        query = """
        SELECT 
            pp.publication_id::text,
            p.name,
            p.type
        FROM publication_party pp
        JOIN party p ON pp.party_id = p.id
        WHERE pp.publication_id = ANY(%s::uuid[])
        """
        
        cur.execute(query, (patent_ids,))
        
        patent_parties = {}
        for row in cur.fetchall():
            pub_id = row[0]
            if pub_id not in patent_parties:
                patent_parties[pub_id] = {'assignees': [], 'inventors': []}
            
            if row[2] == 'assignee':
                patent_parties[pub_id]['assignees'].append(row[1])
            elif row[2] == 'inventor':
                patent_parties[pub_id]['inventors'].append(row[1])
        
        return patent_parties
        
    except Exception as e:
        logger.error(f"Error getting patent parties: {e}")
        return {}
    finally:
        if conn:
            conn.close()

def simple_relevance_score(keywords: List[str], title: str) -> float:
    """Calculate simple relevance score"""
    title_lower = title.lower()
    matches = sum(1 for keyword in keywords if keyword in title_lower)
    return matches / len(keywords) if keywords else 0

def search_similar_patents(description: str, top_k: int = 20):
    """Main search function"""
    print(f"\n🔍 Searching for patents similar to:\n{description}\n")
    
    # Extract keywords
    keywords = extract_keywords(description)
    print(f"📝 Extracted keywords: {', '.join(keywords)}\n")
    
    # Search database
    patents = search_patents(keywords, limit=100)
    
    if not patents:
        print("❌ No patents found matching the keywords.")
        return
    
    print(f"✅ Found {patents[0]['total_matches']} patents\n")
    
    # Get parties for top patents
    top_patent_ids = [p['id'] for p in patents[:top_k]]
    patent_parties = get_patent_parties(top_patent_ids)
    
    # Calculate relevance scores
    for patent in patents:
        patent['relevance_score'] = simple_relevance_score(keywords, patent['title'])
    
    # Sort by relevance
    patents.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    # Display results
    print("Top Results:")
    print("=" * 80)
    
    for i, patent in enumerate(patents[:top_k]):
        parties = patent_parties.get(patent['id'], {})
        
        print(f"\n{i+1}. Patent: {patent['pub_number']}")
        print(f"   Title: {patent['title']}")
        print(f"   Published: {patent['pub_date'] or 'N/A'}")
        print(f"   Relevance: {patent['relevance_score']:.1%}")
        
        if parties.get('assignees'):
            print(f"   Assignees: {', '.join(parties['assignees'][:3])}")
        if parties.get('inventors'):
            print(f"   Inventors: {', '.join(parties['inventors'][:3])}")
        
        print("-" * 80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patent_search_fixed.py '<patent description>'")
        sys.exit(1)
    
    user_description = ' '.join(sys.argv[1:])
    search_similar_patents(user_description)
