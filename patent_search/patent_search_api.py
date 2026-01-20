#\!/usr/bin/env python3
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import requests
import json
import re
import logging
from typing import List, Dict
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

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

# Ollama configuration
OLLAMA_URL = 'http://localhost:11434/api/generate'
MODEL_NAME = 'openchat'

def extract_keywords(description: str) -> List[str]:
    """Extract keywords from patent description"""
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                  'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 
                  'those', 'such', 'wherein', 'whereby', 'thereof', 'comprising', 'claim',
                  'method', 'system', 'device', 'apparatus'}
    
    words = re.findall(r'\b[a-z]+\b', description.lower())
    keyword_count = {}
    
    for word in words:
        if len(word) >= 3 and word not in stop_words:
            keyword_count[word] = keyword_count.get(word, 0) + 1
    
    sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
    return [word for word, count in sorted_keywords[:20]]

def search_patents(keywords: List[str], limit: int = 50) -> List[Dict]:
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
            params.append(f'%{keyword}%')
        
        query = f"""
        SELECT DISTINCT 
            p.id,
            p.publication_number,
            p.invention_title,
            p.kind,
            COALESCE(p.date_published, p.date_publ) as pub_date,
            array_agg(DISTINCT party.name) FILTER (WHERE party.type = 'assignee') as assignees,
            array_agg(DISTINCT party.name) FILTER (WHERE party.type = 'inventor') as inventors
        FROM publication p
        LEFT JOIN publication_party pp ON p.id = pp.publication_id
        LEFT JOIN party ON pp.party_id = party.id
        WHERE {' OR '.join(conditions)}
        GROUP BY p.id, p.publication_number, p.invention_title, p.kind, p.date_published, p.date_publ
        ORDER BY pub_date DESC
        LIMIT %s
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
                'date_published': str(row[4]) if row[4] else None,
                'assignees': row[5] if row[5] else [],
                'inventors': row[6][:3] if row[6] else []  # Limit to 3 inventors
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def score_with_llm(description: str, patent: Dict) -> float:
    """Score patent relevance using LLM"""
    try:
        prompt = f"""Rate the similarity between these patents (0-100):

User Patent: {description[:200]}

Existing Patent: {patent['title']}

Reply with only a number:"""

        response = requests.post(OLLAMA_URL, json={
            'model': MODEL_NAME,
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.1, 'num_predict': 10}
        }, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            score_text = result.get('response', '0').strip()
            match = re.search(r'\d+', score_text)
            if match:
                return float(match.group()) / 100.0
    except:
        pass
    
    return 0.0

@app.route('/api/search', methods=['POST'])
def search_similar_patents():
    """API endpoint for patent search"""
    try:
        data = request.get_json()
        if not data or 'description' not in data:
            return jsonify({'error': 'Missing description parameter'}), 400
        
        description = data['description']
        use_llm = data.get('use_llm', False)
        limit = min(data.get('limit', 20), 100)
        
        # Extract keywords
        keywords = extract_keywords(description)
        
        # Search patents
        patents = search_patents(keywords, limit=50)
        
        if not patents:
            return jsonify({
                'success': True,
                'keywords': keywords,
                'results': [],
                'message': 'No patents found'
            })
        
        # Score patents
        if use_llm:
            for patent in patents:
                patent['relevance_score'] = score_with_llm(description, patent)
            patents.sort(key=lambda x: x['relevance_score'], reverse=True)
        else:
            # Simple keyword scoring
            for patent in patents:
                title_lower = patent['title'].lower()
                matches = sum(1 for kw in keywords if kw in title_lower)
                patent['relevance_score'] = matches / len(keywords) if keywords else 0
            patents.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        # Return top results
        results = patents[:limit]
        
        return jsonify({
            'success': True,
            'keywords': keywords,
            'total_found': len(patents),
            'results': results
        })
        
    except Exception as e:
        logger.error(f"API error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        
        # Test Ollama connection
        ollama_status = 'unavailable'
        try:
            response = requests.get('http://localhost:11434/api/tags', timeout=2)
            if response.status_code == 200:
                ollama_status = 'available'
        except:
            pass
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'ollama': ollama_status
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    print("Starting Patent Search API on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)
