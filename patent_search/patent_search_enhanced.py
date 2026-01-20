#!/usr/bin/env python3
"""
Patent Search System - Enhanced with Progress Bar and Clickable Patents
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
import time

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

# HTML template with progress bar and clickable patents
SEARCH_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Patent Search System</title>
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
    .progress-container {
        display: none;
        margin-top: 20px;
    }
    .progress-container.active { display: block; }
    .progress-bar {
        width: 100%;
        height: 30px;
        background-color: #e0e0e0;
        border-radius: 15px;
        overflow: hidden;
    }
    .progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #3498db, #2980b9);
        border-radius: 15px;
        transition: width 0.3s ease;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 14px;
        font-weight: 600;
        width: 0%;
    }
    .progress-text {
        margin-top: 10px;
        text-align: center;
        color: #666;
        font-size: 14px;
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
        cursor: pointer;
    }
    .patent-item:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transform: translateY(-2px);
        background: #f8f9fa;
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
    .no-results {
        text-align: center;
        padding: 40px;
        color: #666;
    }
    /* Modal styles */
    .modal {
        display: none;
        position: fixed;
        z-index: 1000;
        left: 0;
        top: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0,0,0,0.5);
        overflow: auto;
    }
    .modal.active { display: block; }
    .modal-content {
        background-color: white;
        margin: 5% auto;
        padding: 30px;
        border-radius: 10px;
        width: 90%;
        max-width: 900px;
        max-height: 80vh;
        overflow-y: auto;
        position: relative;
    }
    .modal-close {
        position: absolute;
        right: 20px;
        top: 20px;
        font-size: 28px;
        font-weight: bold;
        color: #aaa;
        cursor: pointer;
    }
    .modal-close:hover { color: #000; }
    .patent-detail h2 {
        color: #2c3e50;
        margin-bottom: 20px;
        font-size: 20px;
    }
    .patent-detail-section {
        margin-bottom: 25px;
        padding-bottom: 20px;
        border-bottom: 1px solid #e0e0e0;
    }
    .patent-detail-section:last-child {
        border-bottom: none;
    }
    .patent-detail-section h3 {
        color: #3498db;
        margin-bottom: 10px;
        font-size: 16px;
    }
    .patent-detail-section p,
    .patent-detail-section ul {
        line-height: 1.6;
        color: #555;
    }
    .patent-detail-meta {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin-bottom: 20px;
    }
    .patent-detail-meta-item {
        padding: 10px;
        background: #f8f9fa;
        border-radius: 5px;
    }
    .patent-detail-meta-label {
        font-size: 12px;
        color: #666;
        margin-bottom: 5px;
    }
    .patent-detail-meta-value {
        font-size: 14px;
        color: #2c3e50;
        font-weight: 600;
    }
</style>
</head>
<body>
    <div class="header">
        <h1>Patent Search System</h1>
        <p>Real-time Search with Clickable Patent Details</p>
    </div>
    
    <div class="container">
        <div class="search-box">
            <h2>Describe Your Invention</h2>
            <textarea id="description" placeholder="Enter a detailed description of your invention..."></textarea>
            <button class="btn" onclick="performSearch()" id="searchBtn">Search Patents</button>
            
            <div class="progress-container" id="progressContainer">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill">0%</div>
                </div>
                <div class="progress-text" id="progressText">Initializing search...</div>
            </div>
        </div>
        
        <div class="results" id="results">
            <h2>Search Results</h2>
            <div class="stats" id="stats"></div>
            <div id="resultsList"></div>
        </div>
    </div>

    <!-- Patent Detail Modal -->
    <div id="patentModal" class="modal">
        <div class="modal-content">
            <span class="modal-close" onclick="closeModal()">&times;</span>
            <div id="patentDetail" class="patent-detail"></div>
        </div>
    </div>

<script>
let searchResults = [];
let progressInterval = null;

async function performSearch() {
    const description = document.getElementById('description').value.trim();
    if (!description) {
        alert('Please enter a description');
        return;
    }
    
    // Reset and show progress
    document.getElementById('searchBtn').disabled = true;
    document.getElementById('progressContainer').classList.add('active');
    document.getElementById('results').classList.remove('active');
    
    // Start progress animation
    let progress = 0;
    updateProgress(0, 'Extracting keywords...');
    
    progressInterval = setInterval(() => {
        if (progress < 90) {
            progress += Math.random() * 15;
            progress = Math.min(progress, 90);
            
            if (progress < 30) {
                updateProgress(progress, 'Extracting keywords...');
            } else if (progress < 60) {
                updateProgress(progress, 'Searching patent database...');
            } else {
                updateProgress(progress, 'Calculating relevance scores...');
            }
        }
    }, 500);
    
    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({description: description})
        });
        
        const data = await response.json();
        
        clearInterval(progressInterval);
        
        if (data.error) {
            alert('Search failed: ' + data.error);
            document.getElementById('progressContainer').classList.remove('active');
            return;
        }
        
        updateProgress(100, 'Search complete!');
        setTimeout(() => {
            document.getElementById('progressContainer').classList.remove('active');
            displayResults(data);
        }, 500);
        
    } catch (error) {
        clearInterval(progressInterval);
        alert('Search failed: ' + error.message);
        document.getElementById('progressContainer').classList.remove('active');
    } finally {
        document.getElementById('searchBtn').disabled = false;
    }
}

function updateProgress(percent, text) {
    percent = Math.round(percent);
    document.getElementById('progressFill').style.width = percent + '%';
    document.getElementById('progressFill').textContent = percent + '%';
    document.getElementById('progressText').textContent = text;
}

function displayResults(data) {
    searchResults = data.results || [];
    
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
    
    if (!searchResults || searchResults.length === 0) {
        resultsList.innerHTML = '<div class="no-results">No patents found matching your description</div>';
        return;
    }
    
    resultsList.innerHTML = searchResults.map((patent, idx) => {
        const relevancePercent = Math.round((patent.relevance_score || 0) * 100);
        
        return `
            <div class="patent-item" onclick="showPatentDetail('${patent.pub_number}')">
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
                    🏢 ${patent.assignees ? patent.assignees.slice(0, 2).join(', ') : 'N/A'}
                </div>
                <div class="patent-abstract">
                    ${patent.abstract ? patent.abstract.substring(0, 200) + '...' : 'No abstract available'}
                </div>
            </div>
        `;
    }).join('');
}

async function showPatentDetail(pubNumber) {
    try {
        const response = await fetch(`/api/patent/${pubNumber}`);
        const data = await response.json();
        
        if (data.error) {
            alert('Failed to load patent details');
            return;
        }
        
        const patent = data.patent;
        
        // Format inventors and assignees
        const formatPeople = (people) => {
            if (!people || people.length === 0) return 'None listed';
            return people.map(p => {
                if (typeof p === 'string') return p;
                return p.name || 'Unknown';
            }).join(', ');
        };
        
        const detailHTML = `
            <h2>${patent.title || 'Untitled Patent'}</h2>
            
            <div class="patent-detail-meta">
                <div class="patent-detail-meta-item">
                    <div class="patent-detail-meta-label">Patent Number</div>
                    <div class="patent-detail-meta-value">${patent.pub_number}</div>
                </div>
                <div class="patent-detail-meta-item">
                    <div class="patent-detail-meta-label">Publication Date</div>
                    <div class="patent-detail-meta-value">${patent.pub_date || 'N/A'}</div>
                </div>
                <div class="patent-detail-meta-item">
                    <div class="patent-detail-meta-label">Filing Date</div>
                    <div class="patent-detail-meta-value">${patent.filing_date || 'N/A'}</div>
                </div>
                <div class="patent-detail-meta-item">
                    <div class="patent-detail-meta-label">Year</div>
                    <div class="patent-detail-meta-value">${patent.year || 'N/A'}</div>
                </div>
            </div>
            
            <div class="patent-detail-section">
                <h3>Abstract</h3>
                <p>${patent.abstract_text || 'No abstract available'}</p>
            </div>
            
            <div class="patent-detail-section">
                <h3>Inventors</h3>
                <p>${formatPeople(patent.inventors)}</p>
            </div>
            
            <div class="patent-detail-section">
                <h3>Assignees</h3>
                <p>${formatPeople(patent.assignees)}</p>
            </div>
            
            ${patent.description_text ? `
            <div class="patent-detail-section">
                <h3>Description</h3>
                <p>${patent.description_text.substring(0, 2000)}${patent.description_text.length > 2000 ? '...' : ''}</p>
            </div>
            ` : ''}
        `;
        
        document.getElementById('patentDetail').innerHTML = detailHTML;
        document.getElementById('patentModal').classList.add('active');
        
    } catch (error) {
        alert('Failed to load patent details: ' + error.message);
    }
}

function closeModal() {
    document.getElementById('patentModal').classList.remove('active');
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('patentModal');
    if (event.target == modal) {
        closeModal();
    }
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
        
        # Format results
        display_results = []
        for patent in scored_results[:50]:
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
