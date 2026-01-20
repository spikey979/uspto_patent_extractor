#!/usr/bin/env python3
"""
Patent Search System - No Cache, Fixed Relevance Scoring
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import re
import os
import logging
from typing import List, Dict
import hashlib

app = Flask(__name__)
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
        # Remove parentheses content for cleaner extraction
        text = re.sub(r'\([^)]*\)', '', text)
        
        # Extract all words
        words = re.findall(r'\b[a-z]+\b', text.lower())
        
        # Get unique keywords
        seen = set()
        keywords = []
        for word in words:
            if len(word) >= 3 and word not in self.stop_words and word not in seen:
                keywords.append(word)
                seen.add(word)
        
        return keywords
    
    def search_patents(self, keywords: List[str], limit: int = 100) -> List[Dict]:
        """Search patents using keywords - NO CACHING"""
        if not keywords:
            logger.warning("No keywords provided for search")
            return []
        
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Build search query - search for ANY keyword match
            conditions = []
            params = []
            
            for keyword in keywords[:20]:  # Limit to first 20 keywords
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
                pub_date,
                year,
                inventors,
                assignees
            FROM patent_data_unified
            WHERE {' OR '.join(conditions)}
            ORDER BY pub_date DESC
            LIMIT %s
            """
            
            params.append(limit)
            
            logger.info(f"Searching with {len(keywords)} keywords: {keywords[:10]}")
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            logger.info(f"Found {len(results)} patents")
            
            # Process JSON fields
            for patent in results:
                for field in ['inventors', 'assignees']:
                    if patent.get(field) and isinstance(patent[field], str):
                        try:
                            patent[field] = json.loads(patent[field])
                        except:
                            patent[field] = []
            
            return results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
        finally:
            cur.close()
            conn.close()
    
    def calculate_relevance_score(self, patent: Dict, keywords: List[str]) -> float:
        """Calculate actual relevance based on keyword matches"""
        if not keywords:
            return 0.0
        
        # Combine title and abstract for matching
        patent_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')}".lower()
        
        # Count how many keywords match
        matches = 0
        matched_keywords = []
        
        for keyword in keywords:
            if keyword.lower() in patent_text:
                matches += 1
                matched_keywords.append(keyword)
        
        # Calculate score as percentage of keywords that matched
        base_score = matches / len(keywords)
        
        # Boost score if important keywords match in title
        title = (patent.get('title', '')).lower()
        title_boost = 0
        for keyword in keywords[:5]:  # First 5 keywords are most important
            if keyword.lower() in title:
                title_boost += 0.1
        
        final_score = min(1.0, base_score + title_boost)
        
        # Store matched keywords for display
        patent['matched_keywords'] = matched_keywords
        patent['match_count'] = matches
        
        return final_score

# Initialize search engine
search_engine = PatentSearchEngine()

# HTML template
SEARCH_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Patent Search System - Fixed</title>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #f5f7fa;
        color: #333;
    }
    .header {
        background: #1a1a2e;
        color: white;
        padding: 20px;
        text-align: center;
    }
    .header h1 { font-size: 24px; }
    .header p { font-size: 14px; opacity: 0.8; margin-top: 5px; }
    .container {
        max-width: 1200px;
        margin: 20px auto;
        padding: 0 20px;
    }
    .search-box {
        background: white;
        padding: 30px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        margin-bottom: 30px;
    }
    textarea {
        width: 100%;
        padding: 15px;
        border: 2px solid #e0e0e0;
        border-radius: 5px;
        font-size: 14px;
        resize: vertical;
        min-height: 120px;
    }
    .btn {
        background: #3498db;
        color: white;
        padding: 12px 30px;
        border: none;
        border-radius: 5px;
        font-size: 16px;
        cursor: pointer;
        margin-top: 15px;
    }
    .btn:hover { background: #2980b9; }
    .btn:disabled {
        background: #bdc3c7;
        cursor: not-allowed;
    }
    .loading {
        display: none;
        text-align: center;
        padding: 20px;
        color: #666;
    }
    .loading.active { display: block; }
    .keywords {
        margin: 20px 0;
        padding: 15px;
        background: #f8f9fa;
        border-radius: 5px;
        display: none;
    }
    .keywords.active { display: block; }
    .keyword-chip {
        display: inline-block;
        padding: 4px 10px;
        background: #e9ecef;
        border-radius: 15px;
        margin: 3px;
        font-size: 13px;
    }
    .results {
        background: white;
        padding: 30px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        display: none;
    }
    .results.active { display: block; }
    .stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin-bottom: 20px;
        padding: 20px;
        background: #f8f9fa;
        border-radius: 8px;
    }
    .stat-item {
        text-align: center;
    }
    .stat-value {
        font-size: 24px;
        font-weight: 600;
        color: #2c3e50;
    }
    .stat-label {
        font-size: 12px;
        color: #666;
        margin-top: 5px;
    }
    .patent-item {
        padding: 20px;
        border: 1px solid #e0e0e0;
        margin-bottom: 15px;
        border-radius: 8px;
        transition: all 0.3s;
    }
    .patent-item:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transform: translateY(-2px);
    }
    .patent-header {
        display: flex;
        justify-content: space-between;
        align-items: start;
        margin-bottom: 10px;
    }
    .patent-title {
        color: #2c3e50;
        font-weight: 600;
        font-size: 16px;
        flex: 1;
        margin-right: 10px;
    }
    .relevance-badge {
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        white-space: nowrap;
    }
    .relevance-H { background: #d4edda; color: #155724; }
    .relevance-M { background: #fff3cd; color: #856404; }
    .relevance-L { background: #f8d7da; color: #721c24; }
    .patent-meta {
        color: #666;
        font-size: 13px;
        margin: 10px 0;
    }
    .patent-abstract {
        color: #555;
        font-size: 14px;
        line-height: 1.6;
        margin: 10px 0;
    }
    .matched-keywords {
        margin-top: 10px;
        font-size: 12px;
        color: #888;
    }
    .matched-keywords strong {
        color: #3498db;
    }
    .no-results {
        text-align: center;
        padding: 40px;
        color: #666;
    }
</style>
</head>
<body>
    <div class="header">
        <h1>Patent Search System</h1>
        <p>No Cache - Real-time Search with Accurate Relevance Scoring</p>
    </div>
    
    <div class="container">
        <div class="search-box">
            <h2>Describe Your Invention</h2>
            <textarea id="description" placeholder="Enter a detailed description of your invention..."></textarea>
            <button class="btn" onclick="performSearch()" id="searchBtn">Search Patents</button>
            <div class="loading" id="loading">Searching patent database...</div>
        </div>
        
        <div class="keywords" id="keywords">
            <h3>Keywords Extracted</h3>
            <div id="keywordList"></div>
        </div>
        
        <div class="results" id="results">
            <h2>Search Results</h2>
            <div class="stats" id="stats"></div>
            <div id="resultsList"></div>
        </div>
    </div>

<script>
async function performSearch() {
    const description = document.getElementById('description').value.trim();
    if (!description) {
        alert('Please enter a description');
        return;
    }
    
    // Show loading
    document.getElementById('searchBtn').disabled = true;
    document.getElementById('loading').classList.add('active');
    document.getElementById('keywords').classList.remove('active');
    document.getElementById('results').classList.remove('active');
    
    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({description: description})
        });
        
        const data = await response.json();
        
        if (data.error) {
            alert('Search failed: ' + data.error);
            return;
        }
        
        displayResults(data);
        
    } catch (error) {
        alert('Search failed: ' + error.message);
    } finally {
        document.getElementById('searchBtn').disabled = false;
        document.getElementById('loading').classList.remove('active');
    }
}

function displayResults(data) {
    // Display keywords
    if (data.keywords && data.keywords.length > 0) {
        document.getElementById('keywords').classList.add('active');
        const keywordList = document.getElementById('keywordList');
        keywordList.innerHTML = data.keywords.map(kw => 
            `<span class="keyword-chip">${kw}</span>`
        ).join('');
    }
    
    // Display stats
    document.getElementById('results').classList.add('active');
    document.getElementById('stats').innerHTML = `
        <div class="stat-item">
            <div class="stat-value">${data.total_results}</div>
            <div class="stat-label">Total Results</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.high_relevance}</div>
            <div class="stat-label">High Relevance (≥65%)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.medium_relevance}</div>
            <div class="stat-label">Medium Relevance (35-64%)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.low_relevance}</div>
            <div class="stat-label">Low Relevance (<35%)</div>
        </div>
    `;
    
    // Display results
    const resultsList = document.getElementById('resultsList');
    
    if (!data.results || data.results.length === 0) {
        resultsList.innerHTML = '<div class="no-results">No patents found matching your description</div>';
        return;
    }
    
    resultsList.innerHTML = data.results.map((patent, idx) => {
        const relevancePercent = Math.round((patent.relevance_score || 0) * 100);
        const matchedKw = patent.matched_keywords ? patent.matched_keywords.join(', ') : '';
        
        return `
            <div class="patent-item">
                <div class="patent-header">
                    <div class="patent-title">#${idx + 1} - ${patent.pub_number}</div>
                    <span class="relevance-badge relevance-${patent.relevance_level}">
                        ${patent.relevance_level} (${relevancePercent}%)
                    </span>
                </div>
                <div class="patent-title">${patent.title || 'Untitled'}</div>
                <div class="patent-meta">
                    📅 ${patent.pub_date || 'N/A'} | 
                    Year: ${patent.year || 'N/A'} | 
                    🏢 ${patent.assignees ? patent.assignees.slice(0, 2).join(', ') : 'N/A'} |
                    👤 ${patent.inventors ? patent.inventors.slice(0, 2).join(', ') : 'N/A'}
                </div>
                <div class="patent-abstract">
                    ${patent.abstract ? patent.abstract.substring(0, 200) + '...' : 'No abstract available'}
                </div>
                ${matchedKw ? `<div class="matched-keywords">
                    <strong>Matched keywords (${patent.match_count}/${data.keywords.length}):</strong> ${matchedKw}
                </div>` : ''}
            </div>
        `;
    }).join('');
}
</script>
</body>
</html>'''

@app.route("/")
def home():
    """Serve the search interface"""
    return SEARCH_HTML

@app.route('/api/search', methods=['POST'])
def search():
    """Patent search with proper relevance scoring"""
    try:
        data = request.get_json()
        description = data.get('description', '').strip()
        
        if not description:
            return jsonify({'error': 'Description required'}), 400
        
        # Extract keywords
        keywords = search_engine.extract_keywords(description)
        logger.info(f"Extracted keywords: {keywords}")
        
        if not keywords:
            return jsonify({
                'keywords': [],
                'results': [],
                'total_results': 0,
                'high_relevance': 0,
                'medium_relevance': 0,
                'low_relevance': 0
            })
        
        # Search patents - NO CACHE
        results = search_engine.search_patents(keywords, limit=100)
        logger.info(f"Search returned {len(results)} results")
        
        # Calculate relevance scores for each result
        scored_results = []
        for patent in results:
            score = search_engine.calculate_relevance_score(patent, keywords)
            patent['relevance_score'] = score
            
            # Assign relevance level based on thresholds
            if score >= 0.65:
                patent['relevance_level'] = 'H'
            elif score >= 0.35:
                patent['relevance_level'] = 'M'
            else:
                patent['relevance_level'] = 'L'
            
            scored_results.append(patent)
        
        # Sort by relevance score
        scored_results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        # Count relevance levels
        high_count = sum(1 for p in scored_results if p['relevance_level'] == 'H')
        medium_count = sum(1 for p in scored_results if p['relevance_level'] == 'M')
        low_count = sum(1 for p in scored_results if p['relevance_level'] == 'L')
        
        # Format results for display
        display_results = []
        for patent in scored_results[:50]:  # Return top 50
            # Format assignees and inventors
            assignees = []
            if patent.get('assignees'):
                for ass in patent['assignees']:
                    if isinstance(ass, dict) and ass.get('name'):
                        assignees.append(ass['name'])
                    elif isinstance(ass, str):
                        assignees.append(ass)
            
            inventors = []
            if patent.get('inventors'):
                for inv in patent['inventors']:
                    if isinstance(inv, dict) and inv.get('name'):
                        inventors.append(inv['name'])
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
                'relevance_level': patent['relevance_level'],
                'matched_keywords': patent.get('matched_keywords', []),
                'match_count': patent.get('match_count', 0)
            })
        
        return jsonify({
            'keywords': keywords[:20],  # Show first 20 keywords
            'results': display_results,
            'total_results': len(scored_results),
            'high_relevance': high_count,
            'medium_relevance': medium_count,
            'low_relevance': low_count
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8092))
    app.run(host='0.0.0.0', port=port, debug=False)
