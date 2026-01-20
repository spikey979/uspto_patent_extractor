#!/usr/bin/env python3
import os
import psycopg2
import requests
import json
import re
import logging
from typing import List, Dict
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Setup logging
logging.basicConfig(level=logging.INFO)

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

def extract_keywords_with_llm(description: str) -> List[str]:
    """Use LLM to extract keywords"""
    prompt = f"""Extract the most important technical keywords from this patent description. 
Focus on unique technical terms, components, methods, and innovations.
Return only a comma-separated list of keywords (maximum 15 keywords).

Patent description:
{description}

Keywords:"""
    
    try:
        response = requests.post(OLLAMA_URL, json={
            'model': MODEL_NAME,
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
            keywords = [k.strip().lower() for k in keywords_text.split(',') if k.strip()]
            app.logger.info(f"LLM extracted keywords: {keywords[:15]}")
            return keywords[:15] if keywords else extract_keywords(description)
    except Exception as e:
        app.logger.error(f"LLM keyword extraction failed: {e}")
    
    return extract_keywords(description)

def score_patent_with_llm(user_description: str, patent: Dict) -> float:
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
        response = requests.post(OLLAMA_URL, json={
            'model': MODEL_NAME,
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
                app.logger.info(f"LLM score for {patent['pub_number']}: {score}")
                return score
    except Exception as e:
        app.logger.warning(f"LLM scoring failed: {e}")
    
    return patent.get('relevance_score', 0)

def search_patents_db(keywords: List[str], limit: int = 100) -> List[Dict]:
    """Search patents in database"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Build search conditions
        conditions = []
        params = []
        
        for keyword in keywords:
            conditions.append("LOWER(invention_title) LIKE %s")
            params.append(f'%{keyword.lower()}%')
        
        # Count keywords in SQL
        keyword_count_sql = []
        if not keywords:
            return []
        for i, keyword in enumerate(keywords):
            keyword_count_sql.append(f"CASE WHEN LOWER(invention_title) LIKE %s THEN 1 ELSE 0 END")
            params.append(f'%{keyword.lower()}%')
        
        query = f"""
        WITH relevant_patents AS (
            SELECT DISTINCT
                p.id,
                p.pub_number,
                p.invention_title,
                p.app_number,
                p.pub_date,
                ({' + '.join(keyword_count_sql)}) as keyword_matches
            FROM publication p
            WHERE {' OR '.join(conditions)}
            ORDER BY keyword_matches DESC, p.pub_date DESC
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
                'pub_date': str(row[4]) if row[4] else None,
                'relevance_score': float(row[5]) / len(keywords) if keywords else 0
            })
        
        return results
        
    except Exception as e:
        app.logger.error(f"Database error: {e}")
        raise e
    finally:
        if conn:
            conn.close()

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        
        # Test Ollama
        ollama_status = "connected"
        try:
            response = requests.get(OLLAMA_URL.replace('/api/generate', '/api/tags'), timeout=2)
            if response.status_code != 200:
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
            app.logger.info("Using LLM for keyword extraction")
            keywords = extract_keywords_with_llm(description)
        else:
            keywords = extract_keywords(description)
        
        app.logger.info(f"Extracted keywords: {keywords}")
        
        # Search database
        patents = search_patents_db(keywords, limit=limit * 2 if use_llm else limit)
        
        if not patents:
            return jsonify({
                "success": True,
                "keywords": keywords,
                "results": [],
                "total_found": 0
            })
        
        # Rank with LLM if requested
        if use_llm and patents:
            app.logger.info(f"Ranking {len(patents[:30])} patents with LLM")
            start_time = time.time()
            
            # Score patents in parallel
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_patent = {
                    executor.submit(score_patent_with_llm, description, patent): patent 
                    for patent in patents[:30]
                }
                
                scored_patents = []
                for future in as_completed(future_to_patent):
                    patent = future_to_patent[future]
                    try:
                        score = future.result()
                        patent['relevance_score'] = score
                        scored_patents.append(patent)
                    except Exception as e:
                        app.logger.error(f"Error scoring patent: {e}")
                        scored_patents.append(patent)
            
            # Sort by score
            scored_patents.sort(key=lambda x: x['relevance_score'], reverse=True)
            patents = scored_patents[:limit]
            
            ranking_time = time.time() - start_time
            app.logger.info(f"LLM ranking completed in {ranking_time:.1f} seconds")
        
        return jsonify({
            "success": True,
            "keywords": keywords,
            "results": patents[:limit],
            "total_found": len(patents),
            "llm_used": use_llm
        })
        
    except Exception as e:
        app.logger.error(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

@app.route('/test', methods=['GET'])
def test_page():
    """Serve test page"""
    return send_file('web/simple_test.html')
