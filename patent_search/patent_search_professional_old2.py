#!/usr/bin/env python3
"""
Fast Patent Search with Post-Processing AI Ranking
AI only processes results AFTER database returns them
"""

from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import re
import os
import requests
import logging
from datetime import datetime
from typing import List, Dict
import hashlib
import uuid
import threading
import time

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)

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

# Store for search progress
search_progress = {}

class FastPatentSearch:
    def __init__(self):
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could'
        }
    
    def extract_keywords_fast(self, text: str) -> List[str]:
        """Fast keyword extraction without AI"""
        # Quick extraction of technical terms
        text_lower = text.lower()
        
        # Find all words
        words = re.findall(r'\b[a-z]+\b', text_lower)
        
        # Filter and count
        keyword_count = {}
        for word in words:
            if len(word) >= 4 and word not in self.stop_words:
                keyword_count[word] = keyword_count.get(word, 0) + 1
        
        # Get top keywords by frequency
        sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
        keywords = [word for word, count in sorted_keywords[:15]]
        
        # Also extract 2-word phrases
        phrases = re.findall(r'\b[a-z]+\s+[a-z]+\b', text_lower)
        for phrase in phrases[:5]:
            words_in_phrase = phrase.split()
            if all(w not in self.stop_words for w in words_in_phrase):
                keywords.append(phrase)
        
        return keywords[:20]  # Return top 20 terms
    
    def search_database_fast(self, keywords: List[str], search_id: str) -> List[Dict]:
        """Fast database search with simple keyword matching"""
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Update progress
            if search_id:
                search_progress[search_id] = {
                    'status': 'searching',
                    'progress': 30,
                    'message': 'Searching patent database...'
                }
            
            # Build simple OR query for speed
            conditions = []
            params = []
            
            # Use only top keywords for faster search
            for keyword in keywords[:10]:
                # Search in title and abstract only for speed
                conditions.append("""
                    (LOWER(u.title) LIKE %s OR 
                     LOWER(u.abstract_text) LIKE %s)
                """)
                pattern = f'%{keyword}%'
                params.extend([pattern, pattern])
            
            # Also search in description but limited
            if keywords:
                conditions.append("""
                    LOWER(LEFT(u.description_text, 5000)) LIKE %s
                """)
                params.append(f'%{keywords[0]}%')
            
            query = f"""
            SELECT 
                u.pub_number,
                u.title,
                u.abstract_text,
                LEFT(u.description_text, 2000) as description_text,
                u.pub_date,
                u.year,
                u.inventors,
                u.assignees
            FROM patent_data_unified u
            WHERE {' OR '.join(conditions)}
            ORDER BY u.year DESC
            LIMIT 200
            """
            
            # Update progress
            if search_id:
                search_progress[search_id] = {
                    'status': 'searching',
                    'progress': 50,
                    'message': 'Retrieving patents from database...'
                }
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            # Parse JSON fields
            for patent in results:
                for field in ['inventors', 'assignees']:
                    if patent.get(field) and isinstance(patent[field], str):
                        try:
                            patent[field] = json.loads(patent[field])
                        except:
                            patent[field] = []
            
            return results
            
        except Exception as e:
            logging.error(f"Database search error: {e}")
            return []
        finally:
            cur.close()
            conn.close()
    
    def rank_results_fast(self, results: List[Dict], original_text: str, keywords: List[str], search_id: str) -> List[Dict]:
        """Fast ranking based on keyword matching"""
        if not results:
            return []
        
        # Update progress
        if search_id:
            search_progress[search_id] = {
                'status': 'ranking',
                'progress': 70,
                'message': 'Ranking results by relevance...'
            }
        
        # Score each result based on keyword matches
        for patent in results:
            score = 0
            text = f"{patent.get('title', '')} {patent.get('abstract_text', '')} {patent.get('description_text', '')}".lower()
            
            # Count keyword matches
            for keyword in keywords:
                if keyword.lower() in text:
                    # Weight by where it appears
                    if keyword.lower() in patent.get('title', '').lower():
                        score += 3
                    if keyword.lower() in patent.get('abstract_text', '').lower():
                        score += 2
                    if keyword.lower() in patent.get('description_text', '').lower():
                        score += 1
            
            patent['relevance_score'] = score / (len(keywords) * 6) if keywords else 0
        
        # Sort by relevance score
        results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        
        # Use AI only for top 10 results for fine-tuning
        if len(results) > 0:
            if search_id:
                search_progress[search_id] = {
                    'status': 'analyzing',
                    'progress': 85,
                    'message': 'AI analyzing top results...'
                }
            
            # Quick AI check for top results only
            top_results = results[:10]
            self.ai_refine_top_results(top_results, original_text, keywords)
        
        return results
    
    def ai_refine_top_results(self, results: List[Dict], original_text: str, keywords: List[str]):
        """Quick AI refinement of just the top results"""
        try:
            # Create a simple prompt for batch scoring
            patents_text = ""
            for i, patent in enumerate(results):
                patents_text += f"{i+1}. {patent.get('title', '')}\n"
            
            prompt = f"""Rate these patents 1-10 for relevance to: {original_text[:200]}
Just provide numbers like: 1:8, 2:6, 3:9, etc.
Patents:
{patents_text}
Scores:"""
            
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,
                    'num_predict': 100
                }
            }, timeout=5)  # Short timeout
            
            if response.status_code == 200:
                scores_text = response.json().get('response', '')
                # Parse scores
                for match in re.finditer(r'(\d+):(\d+)', scores_text):
                    idx = int(match.group(1)) - 1
                    score = int(match.group(2))
                    if 0 <= idx < len(results):
                        # Adjust existing score with AI input
                        results[idx]['relevance_score'] = (results[idx].get('relevance_score', 0) * 0.7 + score/10 * 0.3)
                
                # Re-sort by updated scores
                results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        except Exception as e:
            logging.error(f"AI refinement failed (using keyword scores): {e}")
            # Just use keyword-based scores if AI fails
    
    def generate_report(self, results: List[Dict], keywords: List[str], search_id: str) -> Dict:
        """Generate simple report"""
        if search_id:
            search_progress[search_id] = {
                'status': 'finalizing',
                'progress': 95,
                'message': 'Generating report...'
            }
        
        report = {
            'keywords_used': keywords,
            'total_results': len(results),
            'high_relevance': sum(1 for r in results if r.get('relevance_score', 0) > 0.6),
            'results': []
        }
        
        # Process top 20 results
        for patent in results[:20]:
            score = patent.get('relevance_score', 0)
            
            # Determine level
            if score > 0.6:
                level = 'H'
            elif score > 0.3:
                level = 'M'
            else:
                level = 'L'
            
            # Extract assignees
            assignees = []
            if patent.get('assignees'):
                for ass in patent.get('assignees', []):
                    if isinstance(ass, dict) and ass.get('name'):
                        assignees.append(ass['name'])
            
            report['results'].append({
                'patent_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'pub_date': str(patent.get('pub_date')),
                'relevance_level': level,
                'relevance_score': score,
                'assignees': assignees,
                'abstract': (patent.get('abstract_text') or '')[:300]
            })
        
        if search_id:
            search_progress[search_id] = {
                'status': 'complete',
                'progress': 100,
                'message': 'Search complete!'
            }
        
        return report

# Initialize search engine
search_engine = FastPatentSearch()

@app.route('/')
def home():
    return render_template_string(SEARCH_HTML)

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    """Fast patent search with post-processing"""
    try:
        data = request.get_json()
        invention_description = data.get('invention_description', '')
        
        if not invention_description:
            return jsonify({'error': 'Description required'}), 400
        
        # Generate search ID
        search_id = str(uuid.uuid4())
        
        # Initialize progress
        search_progress[search_id] = {
            'status': 'starting',
            'progress': 10,
            'message': 'Extracting keywords...'
        }
        
        # Fast keyword extraction (no AI)
        keywords = search_engine.extract_keywords_fast(invention_description)
        
        # Fast database search
        results = search_engine.search_database_fast(keywords, search_id)
        
        # Rank results (minimal AI)
        ranked_results = search_engine.rank_results_fast(results, invention_description, keywords, search_id)
        
        # Generate report
        report = search_engine.generate_report(ranked_results, keywords, search_id)
        
        return jsonify({
            'success': True,
            'search_id': search_id,
            'report': report
        })
        
    except Exception as e:
        logging.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search-progress/<search_id>', methods=['GET'])
def get_search_progress(search_id):
    """Get real-time search progress"""
    return jsonify(search_progress.get(search_id, {
        'status': 'not_found',
        'progress': 0,
        'message': 'Search not found'
    }))

# Simplified HTML interface
SEARCH_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fast Patent Search System</title>
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
            max-width: 1400px;
            margin: 20px auto;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            padding: 0 20px;
        }
        .panel {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 5px;
            min-height: 200px;
            font-size: 14px;
        }
        .btn {
            background: #4a90e2;
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
            margin-top: 15px;
        }
        .btn:disabled {
            background: #bdc3c7;
        }
        .progress-container {
            margin-top: 20px;
            display: none;
        }
        .progress-container.active {
            display: block;
        }
        .progress-bar {
            height: 30px;
            background: #ecf0f1;
            border-radius: 15px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #4a90e2, #357abd);
            transition: width 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 12px;
        }
        .progress-message {
            text-align: center;
            color: #7f8c8d;
            margin-top: 10px;
            font-size: 14px;
        }
        .keywords {
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .keyword-tag {
            display: inline-block;
            padding: 3px 10px;
            margin: 3px;
            background: #4a90e2;
            color: white;
            border-radius: 15px;
            font-size: 12px;
        }
        .patent-item {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
        }
        .patent-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        .relevance-H { background: #27ae60; }
        .relevance-M { background: #f39c12; }
        .relevance-L { background: #95a5a6; }
        .relevance-badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            color: white;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Fast Patent Search System</h1>
        <p>Quick database search with intelligent ranking</p>
    </div>
    
    <div class="container">
        <div class="panel">
            <h2>Search Patents</h2>
            <textarea id="description" placeholder="Enter invention description..."></textarea>
            <button class="btn" id="searchBtn" onclick="search()">Search Patents</button>
            
            <div class="progress-container" id="progressContainer">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill">0%</div>
                </div>
                <div class="progress-message" id="progressMessage">Starting search...</div>
            </div>
            
            <div class="keywords" id="keywords" style="display: none;">
                <strong>Search Keywords:</strong>
                <div id="keywordsList"></div>
            </div>
        </div>
        
        <div class="panel">
            <h2>Results</h2>
            <div id="results">
                <p style="color: #999; text-align: center; padding: 40px;">
                    Enter description and click Search
                </p>
            </div>
        </div>
    </div>
    
    <script>
        let searchId = null;
        let progressTimer = null;
        
        async function search() {
            const description = document.getElementById('description').value.trim();
            if (!description) {
                alert('Please enter a description');
                return;
            }
            
            const btn = document.getElementById('searchBtn');
            const progressContainer = document.getElementById('progressContainer');
            const results = document.getElementById('results');
            
            btn.disabled = true;
            btn.textContent = 'Searching...';
            progressContainer.classList.add('active');
            results.innerHTML = '<p style="color: #999; text-align: center;">Searching...</p>';
            
            try {
                const response = await fetch('/api/professional-search', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({invention_description: description})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    searchId = data.search_id;
                    
                    // Start progress updates
                    progressTimer = setInterval(updateProgress, 200);
                    
                    // Display results after a short delay for progress to complete
                    setTimeout(() => {
                        clearInterval(progressTimer);
                        displayResults(data.report);
                        progressContainer.classList.remove('active');
                    }, 2000);
                }
            } catch (error) {
                results.innerHTML = '<p style="color: red;">Error: ' + error.message + '</p>';
                progressContainer.classList.remove('active');
            } finally {
                btn.disabled = false;
                btn.textContent = 'Search Patents';
            }
        }
        
        async function updateProgress() {
            if (!searchId) return;
            
            try {
                const response = await fetch('/api/search-progress/' + searchId);
                const progress = await response.json();
                
                const fill = document.getElementById('progressFill');
                const message = document.getElementById('progressMessage');
                
                fill.style.width = progress.progress + '%';
                fill.textContent = progress.progress + '%';
                message.textContent = progress.message || 'Processing...';
                
                if (progress.status === 'complete') {
                    clearInterval(progressTimer);
                }
            } catch (error) {
                console.error('Progress update failed:', error);
            }
        }
        
        function displayResults(report) {
            // Show keywords
            const keywordsDiv = document.getElementById('keywords');
            const keywordsList = document.getElementById('keywordsList');
            keywordsDiv.style.display = 'block';
            keywordsList.innerHTML = report.keywords_used.map(k => 
                '<span class="keyword-tag">' + k + '</span>'
            ).join('');
            
            // Show results
            const resultsDiv = document.getElementById('results');
            let html = '<p>Found ' + report.total_results + ' patents (' + report.high_relevance + ' high relevance)</p>';
            
            report.results.forEach((patent, i) => {
                html += '<div class="patent-item">';
                html += '<div class="patent-header">';
                html += '<strong>#' + (i+1) + ' - ' + patent.patent_number + '</strong>';
                html += '<span class="relevance-badge relevance-' + patent.relevance_level + '">';
                html += patent.relevance_level + ' (' + Math.round(patent.relevance_score * 100) + '%)';
                html += '</span>';
                html += '</div>';
                html += '<h3>' + patent.title + '</h3>';
                html += '<p style="color: #666; font-size: 14px;">' + patent.pub_date;
                if (patent.assignees && patent.assignees.length > 0) {
                    html += ' | ' + patent.assignees[0];
                }
                html += '</p>';
                if (patent.abstract) {
                    html += '<p style="margin-top: 10px; font-size: 14px;">' + patent.abstract + '...</p>';
                }
                html += '</div>';
            });
            
            resultsDiv.innerHTML = html;
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8092))
    app.run(host='0.0.0.0', port=port, debug=False)
