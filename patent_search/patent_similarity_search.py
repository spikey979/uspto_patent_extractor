#\!/usr/bin/env python3
import psycopg2
import requests
import json
import re
import sys
from typing import List, Dict, Tuple
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
    'password': 'qwklmn711'
}

# Ollama configuration
OLLAMA_URL = 'http://localhost:11434/api/generate'
MODEL_NAME = 'openchat'  # Using the faster model for relevance ranking

def extract_keywords(description: str) -> List[str]:
    """Extract keywords from patent description using simple NLP techniques"""
    # Remove common stop words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                  'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those'}
    
    # Convert to lowercase and split
    words = description.lower().split()
    
    # Extract keywords (3+ characters, not stop words)
    keywords = []
    for word in words:
        # Remove punctuation
        word = re.sub(r'[^a-zA-Z0-9]', '', word)
        if len(word) >= 3 and word not in stop_words:
            keywords.append(word)
    
    # Return unique keywords
    return list(set(keywords))[:20]  # Limit to 20 keywords

def search_patents_by_keywords(keywords: List[str], limit: int = 50) -> List[Dict]:
    """Search patents in database using keywords"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Build search query using OR for keywords
        keyword_conditions = []
        params = []
        
        for keyword in keywords:
            keyword_conditions.append(
                "(LOWER(title) LIKE %s OR LOWER(abstract) LIKE %s OR LOWER(description) LIKE %s)"
            )
            params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
        
        query = f"""
        SELECT DISTINCT 
            publication_number,
            title,
            abstract,
            LEFT(description, 500) as description_snippet,
            filing_date
        FROM patent_data_unified
        WHERE {' OR '.join(keyword_conditions)}
        LIMIT %s
        """
        params.append(limit)
        
        logger.info(f"Searching with {len(keywords)} keywords: {keywords[:5]}...")
        cur.execute(query, params)
        
        results = []
        for row in cur.fetchall():
            results.append({
                'publication_number': row[0],
                'title': row[1],
                'abstract': row[2],
                'description_snippet': row[3],
                'filing_date': str(row[4]) if row[4] else None
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def rank_patents_with_llm(user_description: str, patents: List[Dict]) -> List[Tuple[Dict, float]]:
    """Use LLM to rank patents by relevance to user description"""
    ranked_results = []
    
    for patent in patents:
        try:
            # Create prompt for LLM
            prompt = f"""Rate the similarity between these two patent descriptions on a scale of 0-100:

User's Patent Description:
{user_description}

Existing Patent:
Title: {patent['title']}
Abstract: {patent['abstract'] or 'N/A'}
Description snippet: {patent['description_snippet'] or 'N/A'}

Please respond with only a number between 0 and 100 indicating the similarity score."""

            # Call Ollama API
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,  # Low temperature for consistent scoring
                    'num_predict': 10    # We only need a short response
                }
            }, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                score_text = result.get('response', '0').strip()
                
                # Extract numeric score
                score_match = re.search(r'\d+', score_text)
                if score_match:
                    score = float(score_match.group()) / 100.0
                else:
                    score = 0.0
                
                ranked_results.append((patent, score))
                logger.info(f"Patent {patent['publication_number']} scored: {score:.2f}")
            
        except Exception as e:
            logger.error(f"Error ranking patent {patent.get('publication_number', 'unknown')}: {e}")
            ranked_results.append((patent, 0.0))
    
    # Sort by score descending
    ranked_results.sort(key=lambda x: x[1], reverse=True)
    return ranked_results

def search_similar_patents(user_description: str, top_k: int = 10):
    """Main function to search and rank similar patents"""
    print(f"\nSearching for patents similar to: {user_description[:100]}...\n")
    
    # Extract keywords
    keywords = extract_keywords(user_description)
    print(f"Extracted keywords: {', '.join(keywords)}\n")
    
    # Search database
    patents = search_patents_by_keywords(keywords, limit=50)
    print(f"Found {len(patents)} potentially similar patents\n")
    
    if not patents:
        print("No patents found matching the keywords.")
        return
    
    # Rank with LLM
    print("Ranking patents with LLM (this may take a moment)...\n")
    ranked_patents = rank_patents_with_llm(user_description, patents)
    
    # Display top results
    print(f"\nTop {top_k} most similar patents:\n")
    print("=" * 80)
    
    for i, (patent, score) in enumerate(ranked_patents[:top_k]):
        print(f"\n{i+1}. Patent: {patent['publication_number']}")
        print(f"   Similarity Score: {score:.1%}")
        print(f"   Title: {patent['title']}")
        print(f"   Filed: {patent['filing_date'] or 'N/A'}")
        print(f"   Abstract: {(patent['abstract'] or 'N/A')[:200]}...")
        print("-" * 80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python patent_similarity_search.py '<patent description>'")
        sys.exit(1)
    
    user_description = ' '.join(sys.argv[1:])
    search_similar_patents(user_description)
