#\!/usr/bin/env python3
import os
import psycopg2
import requests
import json
import re
import logging
from typing import List, Dict, Tuple
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Database configuration from environment
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', 5432)),
    'database': os.environ.get('DB_NAME', 'companies_db'),
    'user': os.environ.get('DB_USER', 'mark'),
    'password': os.environ.get('DB_PASSWORD', 'mark123')
}

# Ollama configuration
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434') + '/api/generate'
MODEL_NAME = os.environ.get('MODEL_NAME', 'gpt-oss:20b')

class PatentSearchLLM:
    def __init__(self, model_name=MODEL_NAME):
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
                logger.info(f"LLM extracted keywords: {keywords[:15]}")
                return keywords[:15]
        except Exception as e:
            logger.error(f"LLM keyword extraction failed: {e}")
        
        # Fallback to simple extraction
        return self._simple_keyword_extraction(description)
    
    def _simple_keyword_extraction(self, description: str) -> List[str]:
        """Fallback keyword extraction"""
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                     'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
                     'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                     'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 
                     'those', 'such', 'wherein', 'whereby', 'thereof', 'comprising'}
        
        words = re.findall(r'b[a-z]+b', description.lower())
        keyword_count = {}
        
        for word in words:
            if len(word) >= 3 and word not in stop_words:
                keyword_count[word] = keyword_count.get(word, 0) + 1
        
        sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_keywords[:15]]
    
    def score_patent_relevance(self, user_description: str, patent: Dict) -> float:
        """Use LLM to score patent relevance"""
        prompt = f"""Compare these two patent descriptions and rate their similarity on a scale of 0-100.
Consider technical similarity, application domain, and innovation type.

User's Patent Description:
{user_description[:500]}

Existing Patent:
Title: {patent['title']}
Patent Number: {patent['pub_number']}

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
                match = re.search(r'd+', score_text)
                if match:
                    score = min(float(match.group()) / 100.0, 1.0)
                    logger.info(f"LLM score for {patent['pub_number']}: {score}")
                    return score
        except Exception as e:
            logger.warning(f"LLM scoring failed for {patent['pub_number']}: {e}")
        
        # Fallback to keyword-based scoring
        return patent.get('keyword_score', 0)
    
    def rank_patents_parallel(self, user_description: str, patents: List[Dict], max_workers: int = 3) -> List[Dict]:
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
                    patent['relevance_score'] = score
                    ranked_results.append(patent)
                except Exception as e:
                    logger.error(f"Error scoring patent {patent['pub_number']}: {e}")
                    patent['relevance_score'] = patent.get('keyword_score', 0)
                    ranked_results.append(patent)
        
        # Sort by score
        ranked_results.sort(key=lambda x: x['relevance_score'], reverse=True)
        return ranked_results

# Initialize search system
search_system = PatentSearchLLM()

def search_patents_db(keywords: List[str], limit: int = 100) -> List[Dict]:
    """Search patents in database"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Build search query
        conditions = []
        params = []
        
        for keyword in keywords:
            conditions.append("LOWER(invention_title) LIKE %s")
            params.append(f'%{keyword.lower()}%')
        
        query = f"""
        WITH relevant_patents AS (
            SELECT DISTINCT
                p.id,
                p.pub_number,
                p.invention_title,
                p.app_number,
                p.date_published,
                p.kind,
                CASE 
                    WHEN p.invention_title IS NOT NULL THEN
                        CAST((SELECT COUNT(*) FROM unnest(ARRAY{keywords\!r}) AS kw 
                         WHERE LOWER(p.invention_title) LIKE '%' || LOWER(kw) || '%') AS FLOAT) / {len(keywords)}
                    ELSE 0
                END as keyword_score
            FROM publication p
            WHERE {' OR '.join(conditions)}
            ORDER BY keyword_score DESC, p.date_published DESC
            LIMIT %s
        )
        SELECT * FROM relevant_patents;
        """
        
        params.append(limit)
        cur.execute(query, params)
        
        results = []
        for row in cur.fetchall():
            results.append({
                'id': str(row[0]),
                'pub_number': row[1],
                'title': row[2],
                'app_number': row[3],
                'date_published': str(row[4]) if row[4] else None,
                'kind': row[5],
                'keyword_score': float(row[6])
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise e
    finally:
        if conn:
            conn.close()

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        
        # Test Ollama connection
        ollama_status = "connected"
        try:
            response = requests.get(OLLAMA_URL.replace('/api/generate', '/api/tags'), timeout=2)
            if response.status_code \!= 200:
                ollama_status = "unavailable"
        except:
            ollama_status = "unavailable"
        
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "ollama": ollama_status,
            "model": MODEL_NAME
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    """Serve the web interface"""
    return send_file('web/patent_search.html')

@app.route('/search', methods=['POST'])
def search():
    """Search endpoint"""
    try:
        data = request.get_json()
        description = data.get('description', '')
        use_llm = data.get('use_llm', True)
        limit = min(data.get('limit', 20), 100)
        
        if not description:
            return jsonify({"error": "Description is required"}), 400
        
        # Extract keywords
        if use_llm:
            logger.info("Using LLM for keyword extraction")
            keywords = search_system.extract_keywords_with_llm(description)
        else:
            logger.info("Using simple keyword extraction")
            keywords = search_system._simple_keyword_extraction(description)
        
        logger.info(f"Extracted keywords: {keywords}")
        
        # Search database
        patents = search_patents_db(keywords, limit=limit if not use_llm else limit * 2)
        
        if not patents:
            return jsonify({
                "success": True,
                "keywords": keywords,
                "results": [],
                "total_found": 0
            })
        
        # Rank with LLM if requested
        if use_llm and patents:
            logger.info(f"Ranking {len(patents)} patents with LLM")
            start_time = time.time()
            patents = search_system.rank_patents_parallel(description, patents[:30])[:limit]
            ranking_time = time.time() - start_time
            logger.info(f"LLM ranking completed in {ranking_time:.1f} seconds")
        else:
            # Use keyword scores
            for patent in patents:
                patent['relevance_score'] = patent.get('keyword_score', 0)
        
        return jsonify({
            "success": True,
            "keywords": keywords,
            "results": patents[:limit],
            "total_found": len(patents),
            "llm_used": use_llm
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
