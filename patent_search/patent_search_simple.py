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
    # Common patent stop words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                  'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 
                  'those', 'such', 'wherein', 'whereby', 'thereof', 'comprising'}
    
    # Convert to lowercase and split
    words = re.findall(r'\b[a-z]+\b', description.lower())
    
    # Extract keywords
    keywords = []
    keyword_count = {}
    
    for word in words:
        if len(word) >= 3 and word not in stop_words:
            keyword_count[word] = keyword_count.get(word, 0) + 1
    
    # Sort by frequency and take top keywords
    sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
    keywords = [word for word, count in sorted_keywords[:15]]
    
    return keywords

def search_patents_in_publication_table(keywords: List[str], limit: int = 100) -> List[Dict]:
    """Search patents in the main publication table"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Build search query
        keyword_conditions = []
        params = []
        
        for keyword in keywords:
            keyword_conditions.append("LOWER(invention_title) LIKE %s")
            params.append(f'%{keyword}%')
        
        query = f"""
        SELECT DISTINCT 
            p.id,
            p.publication_number,
            p.invention_title,
            p.kind,
            p.date_published,
            COUNT(*) OVER() as total_matches
        FROM publication p
        WHERE {' OR '.join(keyword_conditions)}
        ORDER BY p.date_published DESC
        LIMIT %s
        """
        params.append(limit)
        
        logger.info(f"Searching with keywords: {keywords}")
        cur.execute(query, params)
        
        results = []
        for row in cur.fetchall():
            results.append({
                'id': row[0],
                'publication_number': row[1],
                'title': row[2],
                'kind': row[3],
                'date_published': str(row[4]) if row[4] else None,
                'total_matches': row[5]
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_patent_details(patent_ids: List[int]) -> Dict[int, Dict]:
    """Get additional details for patents"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Get assignees/inventors
        query = """
        SELECT 
            pp.publication_id,
            p.name,
            p.type
        FROM publication_party pp
        JOIN party p ON pp.party_id = p.id
        WHERE pp.publication_id = ANY(%s)
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
        logger.error(f"Error getting patent details: {e}")
        return {}
    finally:
        if conn:
            conn.close()

def simple_relevance_score(user_keywords: List[str], patent_title: str) -> float:
    """Calculate simple relevance score based on keyword matches"""
    title_lower = patent_title.lower()
    matches = sum(1 for keyword in user_keywords if keyword in title_lower)
    return matches / len(user_keywords) if user_keywords else 0

def search_similar_patents(user_description: str, top_k: int = 20):
    """Main function to search similar patents"""
    print(f"\n🔍 Searching for patents similar to:\n{user_description}\n")
    
    # Extract keywords
    keywords = extract_keywords(user_description)
    print(f"📝 Extracted keywords: {', '.join(keywords)}\n")
    
    # Search database
    patents = search_patents_in_publication_table(keywords, limit=100)
    
    if not patents:
        print("❌ No patents found matching the keywords.")
        return
    
    print(f"✅ Found {patents[0]['total_matches']} patents, showing top {min(top_k, len(patents))}:\n")
    
    # Get additional details
    patent_ids = [p['id'] for p in patents[:top_k]]
    patent_details = get_patent_details(patent_ids)
    
    # Calculate simple relevance scores
    for patent in patents:
        patent['relevance_score'] = simple_relevance_score(keywords, patent['title'])
    
    # Sort by relevance score
    patents.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    # Display results
    print("=" * 80)
    for i, patent in enumerate(patents[:top_k]):
        details = patent_details.get(patent['id'], {})
        
        print(f"\n{i+1}. Patent Number: {patent['publication_number']}")
        print(f"   Title: {patent['title']}")
        print(f"   Published: {patent['date_published'] or 'N/A'}")
        print(f"   Kind: {patent['kind'] or 'N/A'}")
        print(f"   Relevance: {patent['relevance_score']:.1%}")
        
        if details.get('assignees'):
            print(f"   Assignees: {', '.join(details['assignees'][:3])}")
        if details.get('inventors'):
            print(f"   Inventors: {', '.join(details['inventors'][:3])}")
        
        print("-" * 80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patent_search_simple.py '<patent description>'")
        print("Example: python patent_search_simple.py 'A method for wireless communication using multiple antennas'")
        sys.exit(1)
    
    user_description = ' '.join(sys.argv[1:])
    search_similar_patents(user_description)
