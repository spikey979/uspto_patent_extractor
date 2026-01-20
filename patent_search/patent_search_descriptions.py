#!/usr/bin/env python3
import os
import psycopg2
import re
from typing import List, Dict

# Database configuration
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', 5432)),
    'database': os.environ.get('DB_NAME', 'companies_db'),
    'user': os.environ.get('DB_USER', 'mark'),
    'password': os.environ.get('DB_PASSWORD', 'mark123')
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

def search_patents_with_descriptions(keywords: List[str], limit: int = 50) -> List[Dict]:
    """Search patents in both title and description/abstract"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Build search conditions for description search
        desc_conditions = []
        desc_params = []
        
        for keyword in keywords:
            # Search in title, abstract, and description
            desc_conditions.append("""(
                LOWER(title) LIKE %s OR 
                LOWER(abstract_text) LIKE %s OR 
                LOWER(description_text) LIKE %s
            )""")
            kw_pattern = f'%{keyword.lower()}%'
            desc_params.extend([kw_pattern, kw_pattern, kw_pattern])
        
        # Build keyword matching subquery
        keyword_match_cases = []
        for kw in keywords:
            keyword_match_cases.append(f"""
                CASE WHEN (
                    LOWER(title) LIKE '%{kw}%' OR
                    LOWER(abstract_text) LIKE '%{kw}%' OR
                    LOWER(description_text) LIKE '%{kw}%'
                ) THEN 1 ELSE 0 END
            """)
        
        # Query patents with full text
        query = f"""
        WITH scored_patents AS (
            SELECT 
                pub_number,
                title,
                abstract_text,
                description_text,
                pub_date,
                year,
                ({' + '.join(keyword_match_cases)}) as keyword_matches
            FROM patent_data_unified
            WHERE {' OR '.join(desc_conditions)}
            ORDER BY keyword_matches DESC, pub_date DESC
            LIMIT %s
        )
        SELECT * FROM scored_patents;
        """
        
        desc_params.append(limit)
        cur.execute(query, desc_params)
        
        results = []
        for row in cur.fetchall():
            results.append({
                'pub_number': row[0],
                'title': row[1],
                'abstract': row[2][:500] if row[2] else None,
                'description_preview': row[3][:200] + '...' if row[3] and len(row[3]) > 200 else row[3],
                'pub_date': str(row[4]) if row[4] else None,
                'year': row[5],
                'keyword_matches': row[6],
                'relevance_score': float(row[6]) / len(keywords) if keywords else 0
            })
        
        # Also search in main publication table for titles only (for newer patents without descriptions yet)
        if len(results) < limit:
            remaining = limit - len(results)
            
            title_conditions = []
            title_params = []
            for keyword in keywords:
                title_conditions.append("LOWER(invention_title) LIKE %s")
                title_params.append(f'%{keyword.lower()}%')
            
            # Build keyword matching for titles
            title_keyword_cases = []
            for kw in keywords:
                title_keyword_cases.append(f"CASE WHEN LOWER(p.invention_title) LIKE '%{kw}%' THEN 1 ELSE 0 END")
            
            title_query = f"""
            SELECT DISTINCT
                p.pub_number,
                p.invention_title,
                p.pub_date,
                ({' + '.join(title_keyword_cases)}) as keyword_matches
            FROM publication p
            LEFT JOIN patent_data_unified u ON p.pub_number = u.pub_number
            WHERE u.pub_number IS NULL AND ({' OR '.join(title_conditions)})
            ORDER BY keyword_matches DESC, p.pub_date DESC
            LIMIT %s
            """
            
            title_params.append(remaining)
            cur.execute(title_query, title_params)
            
            for row in cur.fetchall():
                results.append({
                    'pub_number': row[0],
                    'title': row[1],
                    'abstract': None,
                    'description_preview': None,
                    'pub_date': str(row[2]) if row[2] else None,
                    'year': row[2].year if row[2] else None,
                    'keyword_matches': row[3],
                    'relevance_score': float(row[3]) / len(keywords) if keywords else 0
                })
        
        return results
        
    except Exception as e:
        print(f"Database error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python patent_search_descriptions.py '<search description>'")
        sys.exit(1)
    
    search_desc = ' '.join(sys.argv[1:])
    keywords = extract_keywords(search_desc)
    
    print(f"\nSearching with keywords: {', '.join(keywords)}")
    print("Searching in titles, abstracts, and descriptions...\n")
    
    results = search_patents_with_descriptions(keywords, limit=10)
    
    for i, patent in enumerate(results, 1):
        print(f"{i}. Patent {patent['pub_number']} ({patent['pub_date']})")
        print(f"   Title: {patent['title']}")
        if patent['abstract']:
            print(f"   Abstract: {patent['abstract']}")
        print(f"   Relevance: {patent['relevance_score']*100:.1f}%")
        print(f"   Keyword matches: {patent['keyword_matches']}")
        print()

if __name__ == "__main__":
    main()