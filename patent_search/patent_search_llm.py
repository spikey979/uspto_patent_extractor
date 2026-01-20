#\!/usr/bin/env python3
import psycopg2
import requests
import json
import re
import sys
import time
from typing import List, Dict, Tuple
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'companies_db',
    'user': 'mark',
    'password': 'mark123'
}

# Ollama configuration
OLLAMA_URL = 'http://localhost:11434/api/generate'

class PatentSearchLLM:
    def __init__(self, model_name='openchat'):
        self.model_name = model_name
        self.ollama_url = OLLAMA_URL
        
    def extract_keywords_with_llm(self, description: str) -> List[str]:
        """Use LLM to extract technical keywords from patent description"""
        prompt = f"""Extract the most important technical keywords from this patent description. 
Focus on unique technical terms, components, methods, and innovations.
Return only a comma-separated list of keywords (maximum 15 keywords).

Patent description:
{description}

Keywords:"""
        
        try:
            response = requests.post(self.ollama_url, json={
                'model': self.model_name,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.3,
                    'num_predict': 100
                }
            }, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                keywords_text = result.get('response', '')
                # Extract comma-separated keywords
                keywords = [k.strip().lower() for k in keywords_text.split(',') if k.strip()]
                return keywords[:15]
        except Exception as e:
            logger.error(f"LLM keyword extraction failed: {e}")
        
        # Fallback to simple extraction
        return self._simple_keyword_extraction(description)
    
    def _simple_keyword_extraction(self, description: str) -> List[str]:
        """Fallback keyword extraction"""
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                     'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be'}
        words = re.findall(r'\b[a-z]+\b', description.lower())
        keyword_count = {}
        
        for word in words:
            if len(word) >= 3 and word not in stop_words:
                keyword_count[word] = keyword_count.get(word, 0) + 1
        
        sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_keywords[:15]]
    
    def search_patents(self, keywords: List[str], limit: int = 50) -> List[Dict]:
        """Search patents using keywords"""
        conn = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            
            # Build comprehensive search query
            conditions = []
            params = []
            
            # Search in title
            title_conditions = ["LOWER(invention_title) LIKE %s" for _ in keywords]
            params.extend([f'%{kw}%' for kw in keywords])
            
            # Combine with OR
            if title_conditions:
                conditions.append(f"({' OR '.join(title_conditions)})")
            
            query = f"""
            WITH ranked_patents AS (
                SELECT DISTINCT 
                    p.id,
                    p.publication_number,
                    p.invention_title,
                    p.kind,
                    p.date_published,
                    p.date_publ,
                    CASE 
                        WHEN p.invention_title IS NOT NULL THEN
                            (SELECT COUNT(*) FROM unnest(ARRAY{keywords\!r}) AS kw 
                             WHERE LOWER(p.invention_title) LIKE '%' || LOWER(kw) || '%')
                        ELSE 0
                    END as keyword_matches
                FROM publication p
                WHERE {' OR '.join(conditions)}
                ORDER BY keyword_matches DESC, p.date_published DESC
                LIMIT %s
            )
            SELECT * FROM ranked_patents;
            """
            params.append(limit)
            
            cur.execute(query, params)
            
            results = []
            for row in cur.fetchall():
                results.append({
                    'id': row[0],
                    'publication_number': row[1],
                    'title': row[2],
                    'kind': row[3],
                    'date_published': str(row[4]) if row[4] else str(row[5]) if row[5] else None,
                    'keyword_matches': row[6]
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Database search error: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def score_patent_relevance(self, user_description: str, patent: Dict) -> float:
        """Use LLM to score patent relevance"""
        prompt = f"""Compare these two patent descriptions and rate their similarity on a scale of 0-100.
Consider technical similarity, application domain, and innovation type.

User's Patent Description:
{user_description[:500]}

Existing Patent:
Title: {patent['title']}
Patent Number: {patent['publication_number']}

Respond with only a number between 0-100:"""
        
        try:
            response = requests.post(self.ollama_url, json={
                'model': self.model_name,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,
                    'num_predict': 10
                }
            }, timeout=20)
            
            if response.status_code == 200:
                result = response.json()
                score_text = result.get('response', '0').strip()
                match = re.search(r'\d+', score_text)
                if match:
                    return min(float(match.group()) / 100.0, 1.0)
        except Exception as e:
            logger.warning(f"LLM scoring failed for {patent['publication_number']}: {e}")
        
        # Fallback to keyword-based scoring
        return patent.get('keyword_matches', 0) / 10.0
    
    def rank_patents_parallel(self, user_description: str, patents: List[Dict], max_workers: int = 5) -> List[Tuple[Dict, float]]:
        """Rank patents in parallel using LLM"""
        ranked_results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_patent = {
                executor.submit(self.score_patent_relevance, user_description, patent): patent 
                for patent in patents
            }
            
            for future in as_completed(future_to_patent):
                patent = future_to_patent[future]
                try:
                    score = future.result()
                    ranked_results.append((patent, score))
                except Exception as e:
                    logger.error(f"Error scoring patent {patent['publication_number']}: {e}")
                    ranked_results.append((patent, 0.0))
        
        # Sort by score
        ranked_results.sort(key=lambda x: x[1], reverse=True)
        return ranked_results
    
    def search_and_rank(self, user_description: str, top_k: int = 10):
        """Main search and rank function"""
        print(f"\n🔍 AI-Powered Patent Search\n")
        print(f"📄 Your Description: {user_description[:100]}...\n")
        
        # Extract keywords using LLM
        print("🤖 Extracting keywords with AI...")
        keywords = self.extract_keywords_with_llm(user_description)
        print(f"📝 Keywords: {', '.join(keywords)}\n")
        
        # Search patents
        print("🔎 Searching patent database...")
        patents = self.search_patents(keywords, limit=30)
        
        if not patents:
            print("❌ No patents found matching your description.")
            return
        
        print(f"✅ Found {len(patents)} relevant patents\n")
        
        # Rank with LLM
        print("🧠 AI ranking patents by relevance...")
        start_time = time.time()
        ranked_patents = self.rank_patents_parallel(user_description, patents)
        ranking_time = time.time() - start_time
        print(f"⏱️  Ranking completed in {ranking_time:.1f} seconds\n")
        
        # Display results
        print("=" * 80)
        print(f"Top {min(top_k, len(ranked_patents))} Most Relevant Patents:")
        print("=" * 80)
        
        for i, (patent, score) in enumerate(ranked_patents[:top_k]):
            print(f"\n{i+1}. Patent: {patent['publication_number']}")
            print(f"   📊 Relevance Score: {score:.1%}")
            print(f"   📋 Title: {patent['title']}")
            print(f"   📅 Published: {patent['date_published'] or 'N/A'}")
            print(f"   🔍 Keyword Matches: {patent['keyword_matches']}")
            print("-" * 80)

def main():
    if len(sys.argv) < 2:
        print("\n🔍 AI-Powered Patent Similarity Search")
        print("\nUsage: python patent_search_llm.py '<your patent description>'")
        print("\nExample: python patent_search_llm.py 'A system for autonomous vehicle navigation using lidar and computer vision'")
        sys.exit(1)
    
    user_description = ' '.join(sys.argv[1:])
    
    # Initialize search system
    search_system = PatentSearchLLM(model_name='openchat')
    
    # Run search
    search_system.search_and_rank(user_description, top_k=10)

if __name__ == "__main__":
    main()
