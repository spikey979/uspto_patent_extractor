#!/usr/bin/env python3
"""
Professional Patent Search with LLM-based Relevance Scoring
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import re
import os
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import hashlib
from typing import List, Dict, Tuple

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

# Ollama configuration
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434/api/generate')
MODEL_NAME = os.environ.get('MODEL_NAME', 'gpt-oss:20b')

# Store search results
search_results_cache = {}
search_progress = {}

class PatentSearchEngine:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=10)
        
    def extract_keywords_ai(self, description: str) -> List[str]:
        """Extract keywords using AI"""
        prompt = f"""Extract the most important technical keywords from this invention description.
Focus on unique technical terms, components, and methods.
Return ONLY a comma-separated list of keywords (max 15 words).

Description: {description[:500]}

Keywords:"""
        
        try:
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.3, 'num_predict': 100}
            }, timeout=15)
            
            if response.status_code == 200:
                keywords_text = response.json().get('response', '').strip()
                keywords = [k.strip() for k in keywords_text.split(',') if k.strip()]
                return keywords[:15]
        except Exception as e:
            logger.error(f"AI keyword extraction failed: {e}")
        
        # Fallback to simple extraction
        return self.extract_keywords_simple(description)
    
    def extract_keywords_simple(self, text: str) -> List[str]:
        """Simple keyword extraction"""
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                     'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be'}
        
        words = re.findall(r'\b[a-z]+\b', text.lower())
        keyword_count = {}
        
        for word in words:
            if len(word) >= 3 and word not in stop_words:
                keyword_count[word] = keyword_count.get(word, 0) + 1
        
        sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_keywords[:15]]
    
    def search_patents(self, keywords: List[str], limit: int = 100) -> List[Dict]:
        """Search patents in database"""
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            conditions = []
            params = []
            
            for keyword in keywords:
                conditions.append("""(
                    LOWER(title) LIKE %s OR 
                    LOWER(abstract_text) LIKE %s OR 
                    LOWER(description_text) LIKE %s
                )""")
                kw_pattern = f'%{keyword.lower()}%'
                params.extend([kw_pattern, kw_pattern, kw_pattern])
            
            query = f"""
            SELECT 
                pub_number,
                title,
                abstract_text,
                description_text,
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
            cur.execute(query, params)
            results = cur.fetchall()
            
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
    
    def score_patent_with_llm(self, patent: Dict, description: str) -> float:
        """Score a single patent using LLM"""
        try:
            patent_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')[:500]}"
            
            prompt = f"""Compare this invention description with a patent and rate their similarity.
Rate from 0 to 100 where:
- 0-34: Low relevance (different field or unrelated)
- 35-64: Medium relevance (same field, some similarities)
- 65-100: High relevance (very similar technology)

INVENTION: {description[:300]}

PATENT: {patent_text[:300]}

Return ONLY a number between 0 and 100:"""
            
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.1, 'num_predict': 10}
            }, timeout=10)
            
            if response.status_code == 200:
                score_text = response.json().get('response', '').strip()
                # Extract number from response
                numbers = re.findall(r'\d+', score_text)
                if numbers:
                    score = min(100, max(0, int(numbers[0])))
                    return score / 100.0
            
        except Exception as e:
            logger.error(f"LLM scoring failed for patent {patent.get('pub_number')}: {e}")
        
        # Fallback to keyword scoring
        return self.score_patent_keywords(patent, description)
    
    def score_patent_keywords(self, patent: Dict, description: str) -> float:
        """Fallback keyword-based scoring"""
        keywords = self.extract_keywords_simple(description)
        patent_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')}".lower()
        
        matches = sum(1 for keyword in keywords if keyword.lower() in patent_text)
        return min(1.0, matches / len(keywords) if keywords else 0)
    
    def score_patents_parallel(self, patents: List[Dict], description: str, search_id: str) -> List[Dict]:
        """Score patents in parallel using LLM"""
        total = len(patents)
        scored_patents = []
        
        # First do quick keyword scoring for all
        for patent in patents:
            patent['keyword_score'] = self.score_patent_keywords(patent, description)
        
        # Sort by keyword score and take top 50 for LLM scoring
        patents.sort(key=lambda x: x['keyword_score'], reverse=True)
        top_patents = patents[:50]
        remaining = patents[50:]
        
        # Update progress
        if search_id:
            search_progress[search_id] = {
                'status': 'scoring',
                'progress': 10,
                'message': f'Scoring {len(top_patents)} most relevant patents with AI...'
            }
        
        # Score top patents with LLM in parallel
        futures = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            for patent in top_patents:
                future = executor.submit(self.score_patent_with_llm, patent, description)
                futures[future] = patent
            
            completed = 0
            for future in as_completed(futures):
                patent = futures[future]
                try:
                    score = future.result(timeout=10)
                    patent['relevance_score'] = score
                    patent['scoring_method'] = 'llm'
                except Exception as e:
                    logger.error(f"Scoring failed: {e}")
                    patent['relevance_score'] = patent['keyword_score']
                    patent['scoring_method'] = 'keyword'
                
                completed += 1
                if search_id and completed % 5 == 0:
                    progress = 10 + int((completed / len(top_patents)) * 80)
                    search_progress[search_id] = {
                        'status': 'scoring',
                        'progress': progress,
                        'message': f'AI scoring: {completed}/{len(top_patents)} patents'
                    }
                
                scored_patents.append(patent)
        
        # Add remaining patents with keyword scores
        for patent in remaining:
            patent['relevance_score'] = patent['keyword_score']
            patent['scoring_method'] = 'keyword'
            scored_patents.append(patent)
        
        # Sort by final score
        scored_patents.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        if search_id:
            search_progress[search_id] = {
                'status': 'complete',
                'progress': 100,
                'message': 'Search complete'
            }
        
        return scored_patents

# Initialize search engine
search_engine = PatentSearchEngine()

# HTML template
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
        min-height: 150px;
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
    .progress-bar {
        display: none;
        margin-top: 20px;
        padding: 15px;
        background: #f8f9fa;
        border-radius: 5px;
    }
    .progress-bar.active { display: block; }
    .progress-fill {
        height: 20px;
        background: #3498db;
        border-radius: 3px;
        transition: width 0.3s;
    }
    .progress-text {
        margin-top: 10px;
        color: #666;
        font-size: 14px;
    }
    .results {
        background: white;
        padding: 30px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    .patent-item {
        padding: 20px;
        border: 1px solid #e0e0e0;
        margin-bottom: 15px;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.3s;
    }
    .patent-item:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transform: translateY(-2px);
    }
    .patent-header {
        display: flex;
        justify-content: space-between;
        margin-bottom: 10px;
    }
    .patent-title {
        color: #2c3e50;
        font-weight: 600;
        font-size: 16px;
    }
    .relevance-badge {
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
    .relevance-H { background: #d4edda; color: #155724; }
    .relevance-M { background: #fff3cd; color: #856404; }
    .relevance-L { background: #f8d7da; color: #721c24; }
    .patent-details {
        display: none;
        margin-top: 15px;
        padding-top: 15px;
        border-top: 1px solid #e0e0e0;
    }
    .patent-details.active { display: block; }
    .keywords {
        margin: 20px 0;
        padding: 15px;
        background: #f8f9fa;
        border-radius: 5px;
    }
    .keyword-chip {
        display: inline-block;
        padding: 4px 10px;
        background: #e9ecef;
        border-radius: 15px;
        margin: 3px;
        font-size: 13px;
    }
    .stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 15px;
        margin: 20px 0;
    }
    .stat-card {
        padding: 15px;
        background: #f8f9fa;
        border-radius: 8px;
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
</style>
</head>
<body>
    <div class="header">
        <h1>Professional Patent Search System</h1>
        <p>AI-Enhanced Relevance Scoring</p>
    </div>
    
    <div class="container">
        <div class="search-box">
            <h2>Describe Your Invention</h2>
            <textarea id="description" placeholder="Enter a detailed description of your invention, including its purpose, key components, and how it works..."></textarea>
            <button class="btn" onclick="performSearch()">Search Patents</button>
            
            <div class="progress-bar" id="progressBar">
                <div class="progress-fill" id="progressFill" style="width: 0%"></div>
                <div class="progress-text" id="progressText">Initializing search...</div>
            </div>
        </div>
        
        <div id="keywords" class="keywords" style="display: none;">
            <h3>Extracted Keywords</h3>
            <div id="keywordList"></div>
        </div>
        
        <div id="stats" class="stats" style="display: none;"></div>
        
        <div id="results" class="results" style="display: none;">
            <h2>Search Results</h2>
            <div id="resultsList"></div>
        </div>
    </div>

<script>
let currentSearchId = null;
let progressInterval = null;

async function performSearch() {
    const description = document.getElementById('description').value.trim();
    if (!description) {
        alert('Please enter a description');
        return;
    }
    
    // Reset UI
    document.getElementById('results').style.display = 'none';
    document.getElementById('keywords').style.display = 'none';
    document.getElementById('stats').style.display = 'none';
    document.getElementById('progressBar').classList.add('active');
    document.getElementById('progressFill').style.width = '0%';
    document.getElementById('progressText').textContent = 'Initializing search...';
    
    // Generate search ID
    currentSearchId = Date.now().toString();
    
    // Start progress polling
    startProgressPolling();
    
    try {
        const response = await fetch('/api/professional-search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                invention_description: description,
                search_id: currentSearchId
            })
        });
        
        const data = await response.json();
        stopProgressPolling();
        
        if (data.error) {
            alert('Search failed: ' + data.error);
            document.getElementById('progressBar').classList.remove('active');
            return;
        }
        
        displayResults(data.report);
        
    } catch (error) {
        stopProgressPolling();
        alert('Search failed: ' + error.message);
        document.getElementById('progressBar').classList.remove('active');
    }
}

function startProgressPolling() {
    progressInterval = setInterval(async () => {
        if (!currentSearchId) return;
        
        try {
            const response = await fetch(`/api/search-progress/${currentSearchId}`);
            const data = await response.json();
            
            if (data.progress) {
                document.getElementById('progressFill').style.width = data.progress + '%';
                document.getElementById('progressText').textContent = data.message || 'Processing...';
            }
        } catch (error) {
            console.error('Progress polling error:', error);
        }
    }, 1000);
}

function stopProgressPolling() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    document.getElementById('progressBar').classList.remove('active');
}

function displayResults(report) {
    // Display keywords
    if (report.concepts_found) {
        document.getElementById('keywords').style.display = 'block';
        const keywordList = document.getElementById('keywordList');
        keywordList.innerHTML = '';
        
        const allKeywords = [
            ...(report.concepts_found.primary_terms || []),
            ...(report.concepts_found.component_terms || []),
            ...(report.concepts_found.method_terms || [])
        ];
        
        allKeywords.forEach(keyword => {
            keywordList.innerHTML += `<span class="keyword-chip">${keyword}</span>`;
        });
    }
    
    // Display stats
    document.getElementById('stats').style.display = 'grid';
    document.getElementById('stats').innerHTML = `
        <div class="stat-card">
            <div class="stat-value">${report.total_results || 0}</div>
            <div class="stat-label">Total Results</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${report.high_relevance || 0}</div>
            <div class="stat-label">High Relevance</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${report.medium_relevance || 0}</div>
            <div class="stat-label">Medium Relevance</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${report.low_relevance || 0}</div>
            <div class="stat-label">Low Relevance</div>
        </div>
    `;
    
    // Display results
    document.getElementById('results').style.display = 'block';
    const resultsList = document.getElementById('resultsList');
    resultsList.innerHTML = '';
    
    if (!report.results || report.results.length === 0) {
        resultsList.innerHTML = '<p>No results found</p>';
        return;
    }
    
    report.results.forEach(patent => {
        const item = document.createElement('div');
        item.className = 'patent-item';
        item.onclick = () => showPatentDetails(patent.patent_number, currentSearchId);
        
        const relevancePercent = Math.round((patent.relevance_score || 0) * 100);
        const scoringMethod = patent.scoring_method === 'llm' ? '🤖' : '🔤';
        
        item.innerHTML = `
            <div class="patent-header">
                <div class="patent-title">${patent.title || 'Untitled'}</div>
                <span class="relevance-badge relevance-${patent.relevance_level}">
                    ${patent.relevance_level} (${relevancePercent}%) ${scoringMethod}
                </span>
            </div>
            <div style="color: #666; font-size: 14px;">
                Patent #${patent.patent_number} | ${patent.pub_date || 'N/A'}
            </div>
            <div style="margin-top: 10px; color: #555; font-size: 13px;">
                ${patent.abstract ? patent.abstract.substring(0, 200) + '...' : 'No abstract available'}
            </div>
            <div style="margin-top: 10px; font-size: 12px; color: #888;">
                Assignees: ${patent.assignees ? patent.assignees.join(', ') : 'N/A'}
            </div>
        `;
        
        resultsList.appendChild(item);
    });
}

async function showPatentDetails(patentNumber, searchId) {
    try {
        const response = await fetch(`/api/patent/${searchId}/${patentNumber}`);
        const data = await response.json();
        
        if (data.patent) {
            // Create modal or expand details
            alert(JSON.stringify(data.patent, null, 2));
        }
    } catch (error) {
        console.error('Error fetching patent details:', error);
    }
}
</script>
</body>
</html>'''

@app.route("/")
def home():
    """Serve the search interface"""
    return SEARCH_HTML

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    """Smart patent search with LLM scoring"""
    try:
        data = request.get_json()
        description = data.get('invention_description', '').strip()
        search_id = data.get('search_id', hashlib.md5(description.encode()).hexdigest()[:8])
        
        if not description:
            return jsonify({'error': 'Description required'}), 400
        
        # Initialize progress
        search_progress[search_id] = {
            'status': 'extracting',
            'progress': 5,
            'message': 'Extracting keywords with AI...'
        }
        
        # Extract keywords
        keywords = search_engine.extract_keywords_ai(description)
        
        search_progress[search_id] = {
            'status': 'searching',
            'progress': 20,
            'message': f'Searching database with {len(keywords)} keywords...'
        }
        
        # Search patents
        results = search_engine.search_patents(keywords, limit=100)
        
        if not results:
            return jsonify({
                'report': {
                    'concepts_found': {'primary_terms': keywords},
                    'results': [],
                    'total_results': 0
                }
            })
        
        # Score patents with LLM
        scored_results = search_engine.score_patents_parallel(results, description, search_id)
        
        # Prepare report
        high_count = sum(1 for p in scored_results if p.get('relevance_score', 0) >= 0.65)
        medium_count = sum(1 for p in scored_results if 0.35 <= p.get('relevance_score', 0) < 0.65)
        low_count = sum(1 for p in scored_results if p.get('relevance_score', 0) < 0.35)
        
        # Cache results
        search_results_cache[search_id] = scored_results
        
        # Format results for display
        display_results = []
        for patent in scored_results[:50]:
            score = patent.get('relevance_score', 0)
            level = 'H' if score >= 0.65 else 'M' if score >= 0.35 else 'L'
            
            assignees = []
            if patent.get('assignees'):
                for ass in patent['assignees']:
                    if isinstance(ass, dict) and ass.get('name'):
                        assignees.append(ass['name'])
                    elif isinstance(ass, str):
                        assignees.append(ass)
            
            display_results.append({
                'patent_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'abstract': patent.get('abstract_text', '')[:200] if patent.get('abstract_text') else '',
                'pub_date': str(patent.get('pub_date')) if patent.get('pub_date') else 'N/A',
                'assignees': assignees[:3],
                'relevance_score': score,
                'relevance_level': level,
                'scoring_method': patent.get('scoring_method', 'keyword'),
                'year': patent.get('year')
            })
        
        report = {
            'search_id': search_id,
            'concepts_found': {
                'primary_terms': keywords[:5],
                'component_terms': keywords[5:10] if len(keywords) > 5 else [],
                'method_terms': keywords[10:] if len(keywords) > 10 else []
            },
            'total_results': len(scored_results),
            'high_relevance': high_count,
            'medium_relevance': medium_count,
            'low_relevance': low_count,
            'results': display_results
        }
        
        return jsonify({'report': report})
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search-progress/<search_id>', methods=['GET'])
def get_search_progress(search_id):
    """Get search progress"""
    progress = search_progress.get(search_id, {
        'status': 'unknown',
        'progress': 0,
        'message': 'Search not found'
    })
    return jsonify(progress)

@app.route('/api/patent/<search_id>/<patent_number>', methods=['GET'])
def get_patent_details(search_id, patent_number):
    """Get detailed patent information"""
    # Try to get from cache first
    cached_results = search_results_cache.get(search_id, [])
    for patent in cached_results:
        if patent.get('pub_number') == patent_number:
            return jsonify({'success': True, 'patent': patent})
    
    # Fetch from database
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT * FROM patent_data_unified
            WHERE pub_number = %s
        """, (patent_number,))
        
        patent = cur.fetchone()
        
        if patent:
            # Parse JSON fields
            for field in ['inventors', 'assignees', 'applicants']:
                if patent.get(field) and isinstance(patent[field], str):
                    try:
                        patent[field] = json.loads(patent[field])
                    except:
                        patent[field] = []
            
            return jsonify({'success': True, 'patent': patent})
        else:
            return jsonify({'error': 'Patent not found'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8092))
    app.run(host='0.0.0.0', port=port, debug=False)
