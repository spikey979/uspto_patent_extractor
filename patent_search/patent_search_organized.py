#!/usr/bin/env python3
"""
Patent Search System - Organized with Static Files
"""

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import re
import os
import logging
from typing import List, Dict

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', 5432)),
    'database': os.environ.get('DB_NAME', 'companies_db'),
    'user': os.environ.get('DB_USER', 'mark'),
    'password': os.environ.get('DB_PASSWORD', 'mark123')
}

# Store patent details for modal view
patent_cache = {}

class PatentSearchEngine:
    def __init__(self):
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
            'that', 'this', 'such', 'may', 'can', 'do', 'some', 'about', 'than',
            'eg', 'ie', 'etc', 'have', 'has', 'had', 'will', 'would', 'could',
            'should', 'might', 'must', 'shall', 'being', 'been', 'having'
        }
    
    def extract_keywords(self, text: str) -> List[str]:
        """Extract all meaningful keywords from text"""
        text = re.sub(r'\([^)]*\)', '', text)
        words = re.findall(r'\b[a-z]+\b', text.lower())
        
        seen = set()
        keywords = []
        for word in words:
            if len(word) >= 3 and word not in self.stop_words and word not in seen:
                keywords.append(word)
                seen.add(word)
        
        return keywords
    
    def search_patents(self, keywords: List[str], limit: int = 100) -> List[Dict]:
        """Search patents using keywords"""
        if not keywords:
            logger.warning("No keywords provided for search")
            return []
        
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            conditions = []
            params = []
            
            for keyword in keywords[:20]:
                conditions.append("""(
                    LOWER(title) LIKE %s OR 
                    LOWER(abstract_text) LIKE %s
                )""")
                kw_pattern = f'%{keyword.lower()}%'
                params.extend([kw_pattern, kw_pattern])
            
            query = f"""
            SELECT 
                pub_number,
                title,
                abstract_text,
                description_text,
                pub_date,
                year,
                inventors,
                assignees,
                filing_date,
                applicants
            FROM patent_data_unified
            WHERE {' OR '.join(conditions)}
            ORDER BY pub_date DESC
            LIMIT %s
            """
            
            params.append(limit)
            logger.info(f"Searching with {len(keywords)} keywords")
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            logger.info(f"Found {len(results)} patents")
            
            # Process JSON fields and store full patent data
            for patent in results:
                for field in ['inventors', 'assignees', 'applicants']:
                    if patent.get(field) and isinstance(patent[field], str):
                        try:
                            patent[field] = json.loads(patent[field])
                        except:
                            patent[field] = []
                
                # Store full patent data for detail view
                patent_cache[patent['pub_number']] = patent
            
            return results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
        finally:
            cur.close()
            conn.close()
    
    def calculate_relevance_score(self, patent: Dict, keywords: List[str]) -> float:
        """Calculate relevance based on keyword matches"""
        if not keywords:
            return 0.0
        
        patent_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')}".lower()
        
        matches = 0
        matched_keywords = []
        
        for keyword in keywords:
            if keyword.lower() in patent_text:
                matches += 1
                matched_keywords.append(keyword)
        
        base_score = matches / len(keywords)
        
        title = (patent.get('title', '')).lower()
        title_boost = 0
        for keyword in keywords[:5]:
            if keyword.lower() in title:
                title_boost += 0.1
        
        final_score = min(1.0, base_score + title_boost)
        
        patent['matched_keywords'] = matched_keywords
        patent['match_count'] = matches
        
        return final_score

# Initialize search engine
search_engine = PatentSearchEngine()

@app.route("/")
def home():
    """Serve the search interface"""
    return render_template('index.html')

@app.route('/static/<path:path>')
def send_static(path):
    """Serve static files"""
    return send_from_directory('static', path)

@app.route('/api/search', methods=['POST'])
def search():
    """Patent search with progress simulation"""
    try:
        data = request.get_json()
        description = data.get('description', '').strip()
        
        if not description:
            return jsonify({'error': 'Description required'}), 400
        
        # Extract keywords
        keywords = search_engine.extract_keywords(description)
        logger.info(f"Extracted {len(keywords)} keywords")
        
        if not keywords:
            return jsonify({
                'results': [],
                'total_results': 0,
                'high_relevance': 0,
                'medium_relevance': 0,
                'low_relevance': 0
            })
        
        # Search patents
        results = search_engine.search_patents(keywords, limit=100)
        logger.info(f"Search returned {len(results)} results")
        
        # Calculate relevance scores
        scored_results = []
        for patent in results:
            score = search_engine.calculate_relevance_score(patent, keywords)
            patent['relevance_score'] = score
            
            if score >= 0.65:
                patent['relevance_level'] = 'H'
            elif score >= 0.35:
                patent['relevance_level'] = 'M'
            else:
                patent['relevance_level'] = 'L'
            
            scored_results.append(patent)
        
        # Sort by relevance
        scored_results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        # Count relevance levels
        high_count = sum(1 for p in scored_results if p['relevance_level'] == 'H')
        medium_count = sum(1 for p in scored_results if p['relevance_level'] == 'M')
        low_count = sum(1 for p in scored_results if p['relevance_level'] == 'L')
        
        # Format results - properly extract names from objects
        display_results = []
        for patent in scored_results[:50]:
            # Extract assignee names
            assignees = []
            if patent.get('assignees'):
                for ass in patent['assignees']:
                    if isinstance(ass, dict):
                        name = ass.get('name') or ass.get('orgname') or 'Unknown'
                        assignees.append(name)
                    elif isinstance(ass, str):
                        assignees.append(ass)
            
            # Extract inventor names
            inventors = []
            if patent.get('inventors'):
                for inv in patent['inventors']:
                    if isinstance(inv, dict):
                        name = inv.get('name')
                        if not name:
                            # Try to construct from first/last name
                            first = inv.get('first_name', '')
                            last = inv.get('last_name', '')
                            if first or last:
                                name = f"{first} {last}".strip()
                            else:
                                name = 'Unknown'
                        inventors.append(name)
                    elif isinstance(inv, str):
                        inventors.append(inv)
            
            display_results.append({
                'pub_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'abstract': patent.get('abstract_text', ''),
                'pub_date': str(patent.get('pub_date')) if patent.get('pub_date') else 'N/A',
                'year': patent.get('year'),
                'assignees': assignees,
                'inventors': inventors,
                'relevance_score': patent['relevance_score'],
                'relevance_level': patent['relevance_level']
            })
        
        return jsonify({
            'results': display_results,
            'total_results': len(scored_results),
            'high_relevance': high_count,
            'medium_relevance': medium_count,
            'low_relevance': low_count
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/patent/<pub_number>')
def get_patent_detail(pub_number):
    """Get detailed patent information"""
    try:
        # Check cache first
        if pub_number in patent_cache:
            patent = patent_cache[pub_number]
            return jsonify({'patent': patent})
        
        # Fetch from database
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT * FROM patent_data_unified
            WHERE pub_number = %s
        """, (pub_number,))
        
        patent = cur.fetchone()
        cur.close()
        conn.close()
        
        if patent:
            # Process JSON fields
            for field in ['inventors', 'assignees', 'applicants']:
                if patent.get(field) and isinstance(patent[field], str):
                    try:
                        patent[field] = json.loads(patent[field])
                    except:
                        patent[field] = []
            
            return jsonify({'patent': patent})
        else:
            return jsonify({'error': 'Patent not found'}), 404
            
    except Exception as e:
        logger.error(f"Error fetching patent {pub_number}: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8092))
    app.run(host='0.0.0.0', port=port, debug=False)
