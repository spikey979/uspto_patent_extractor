#\!/usr/bin/env python3
import os
import json
import psycopg2
import requests
import re
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from typing import List, Dict
import logging

app = Flask(__name__)
CORS(app)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration from environment
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'companies_db'),
    'user': os.getenv('DB_USER', 'mark'),
    'password': os.getenv('DB_PASSWORD', 'mark123')
}

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434') + '/api/generate'

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
        
        conditions = []
        params = []
        
        for keyword in keywords:
            conditions.append("LOWER(invention_title) LIKE %s")
            params.append(f'%{keyword}%')
        
        query = f"""
        SELECT DISTINCT 
            p.id::text,
            p.pub_number,
            p.invention_title,
            p.pub_date,
            p.app_number
        FROM publication p
        WHERE {' OR '.join(conditions)}
        ORDER BY p.pub_date DESC NULLS LAST
        LIMIT %s
        """
        params.append(limit)
        
        cur.execute(query, params)
        
        results = []
        for row in cur.fetchall():
            results.append({
                'id': row[0],
                'pub_number': row[1],
                'title': row[2],
                'date_published': str(row[3]) if row[3] else None,
                'app_number': row[4]
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def calculate_relevance(keywords: List[str], title: str) -> float:
    """Calculate relevance score"""
    title_lower = title.lower()
    matches = sum(1 for keyword in keywords if keyword in title_lower)
    return matches / len(keywords) if keywords else 0

@app.route('/')
def index():
    """Serve the main search page"""
    return send_file('/app/web/patent_search.html')

@app.route('/search', methods=['POST', 'OPTIONS'])
def search():
    """API endpoint for patent search"""
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        data = request.get_json()
        description = data.get('description', '')
        
        if not description:
            return jsonify({'error': 'No description provided'}), 400
        
        # Extract keywords
        keywords = extract_keywords(description)
        logger.info(f"Extracted keywords: {keywords}")
        
        # Search patents
        patents = search_patents(keywords, limit=100)
        
        # Calculate relevance scores
        for patent in patents:
            patent['relevance_score'] = calculate_relevance(keywords, patent['title'])
        
        # Sort by relevance
        patents.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        # Return top 20 results
        return jsonify({
            'success': True,
            'keywords': keywords,
            'results': patents[:20],
            'total_found': len(patents)
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Test database connection
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        return jsonify({'status': 'healthy', 'database': 'connected'})
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
