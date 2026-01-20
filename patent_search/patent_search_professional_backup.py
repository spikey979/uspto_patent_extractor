#!/usr/bin/env python3
"""
Smart Patent Search with Clickable Results and Detail View
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
from typing import List, Dict, Set
import hashlib
import uuid

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

# Store for search progress and results
search_progress = {}
search_results_cache = {}

class SmartPatentSearch:
    def __init__(self):
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'more', 'specifically', 'relates', 'involves', 'during', 'time'
        }
    
    def extract_technical_concepts(self, text: str) -> Dict[str, List[str]]:
        """Extract ALL technical concepts from text using AI"""
        text_lower = text.lower()
        
        concepts = {
            'primary_terms': [],
            'medical_terms': [],
            'method_terms': [],
            'component_terms': [],
            'combined_phrases': []
        }
        
        # First try AI extraction with Ollama
        try:
            import requests
            prompt = f"""Extract the most important technical keywords from this invention description.
Focus on: product names, technical components, methods, materials, and domain-specific terms.
Return ONLY comma-separated keywords, no explanation.

Description: {text[:1000]}

Keywords:"""
            
            response = requests.post('http://localhost:11434/api/generate', 
                json={
                    'model': 'gpt-oss:20b',
                    'prompt': prompt,
                    'stream': False,
                    'options': {'temperature': 0.3, 'num_predict': 100}
                }, 
                timeout=15)
            
            if response.status_code == 200:
                ai_keywords = response.json().get('response', '').strip()
                keywords = [k.strip().lower() for k in ai_keywords.split(',') if k.strip()]
                concepts['primary_terms'] = keywords[:20]
        except:
            pass
        
        # Fallback: Extract ALL meaningful words as keywords
        if not concepts['primary_terms']:
            # Remove common stop words
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                         'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be'}
            
            # Extract all words 3+ chars that aren't stop words
            words = re.findall(r'[a-z]{3,}', text_lower)
            word_freq = {}
            for word in words:
                if word not in stop_words:
                    word_freq[word] = word_freq.get(word, 0) + 1
            
            # Get top 15 most frequent words
            sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
            concepts['primary_terms'] = [word for word, freq in sorted_words[:15]]
        
        # Always include specific technical terms if present
        tech_terms = ['wireless', 'bluetooth', 'earbuds', 'noise', 'cancellation', 'audio',
                     'battery', 'charging', 'communication', 'device', 'microphone', 'speaker']
        for term in tech_terms:
            if term in text_lower and term not in concepts['primary_terms']:
                concepts['primary_terms'].append(term)
        
        return concepts
    
    def search_with_concepts(self, concepts: Dict[str, List[str]], search_id: str) -> List[Dict]:
        """Search database using extracted concepts"""
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            if search_id:
                search_progress[search_id] = {
                    'status': 'searching',
                    'progress': 30,
                    'message': 'Searching patent database...'
                }
            
            conditions = []
            params = []
            
            # Search for phrases and terms
            all_terms = concepts['primary_terms'][:10] + concepts.get('combined_phrases', [])[:3] + concepts.get('medical_terms', [])[:3]
            for term in all_terms:
                conditions.append("""
                    (LOWER(u.title) LIKE %s OR 
                     LOWER(u.abstract_text) LIKE %s OR
                     LOWER(LEFT(u.description_text, 10000)) LIKE %s)
                """)
                pattern = f'%{term}%'
                params.extend([pattern, pattern, pattern])
            
            if not conditions:
                return []
            
            query = f"""
            SELECT 
                u.pub_number,
                u.title,
                u.abstract_text,
                u.description_text,
                u.pub_date,
                u.year,
                u.inventors,
                u.assignees,
                u.applicants
            FROM patent_data_unified u
            WHERE {' OR '.join(conditions)}
            ORDER BY u.year DESC
            LIMIT 50
            """
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            # Parse JSON fields and store full data
            for patent in results:
                for field in ['inventors', 'assignees', 'applicants']:
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
    
    def score_results_by_concepts(self, results: List[Dict], concepts: Dict[str, List[str]], search_id: str, user_description: str = None) -> List[Dict]:
        """Fast keyword-based relevance scoring"""
        if not results:
            return []
        
        keywords = concepts.get('primary_terms', [])
        
        for patent in results:
            text = (patent.get('title', '') + ' ' + patent.get('abstract_text', '')).lower()
            
            # Count keyword matches
            matches = 0
            for keyword in keywords:
                if keyword.lower() in text:
                    matches += 1
            
            # Calculate score based on matches
            if matches == 0:
                score = 5
            elif matches == 1:
                score = 25
            elif matches == 2:
                score = 45
            elif matches == 3:
                score = 65
            elif matches == 4:
                score = 80
            else:
                score = 90
            
            patent['relevance_score'] = score / 100.0
            patent['keyword_matches'] = matches
        
        # Sort by score
        results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        
        if search_id:
            search_progress[search_id] = {
                'status': 'complete',
                'progress': 100,
                'message': 'Search complete'
            }
        
        return results[:50]
    
    def _fallback_scoring(self, text: str, concepts: Dict[str, List[str]]) -> int:
        """Simple keyword matching"""
        score = 0
        for term in concepts.get('primary_terms', []):
            if term in text:
                score += 15
        return min(100, score)


    def _fallback_scoring(self, text: str, concepts: Dict[str, List[str]]) -> int:
        """Simple keyword matching fallback"""
        score = 0
        for term in concepts.get('primary_terms', []):
            if term in text:
                score += 15
        return min(100, score)

def home():
    return render_template_string(SEARCH_HTML)
# Initialize search engine
search_engine = SmartPatentSearch()


# HTML interface with clickable results
SEARCH_HTML = '''
    <!DOCTYPE html>
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
            max-height: calc(100vh - 100px);
            overflow-y: auto;
        }
        textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 5px;
            min-height: 150px;
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
        .patent-item {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
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
        .patent-number {
            color: #4a90e2;
            font-weight: 600;
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
        .patent-title {
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 8px;
            color: #2c3e50;
        }
        .patent-meta {
            font-size: 13px;
            color: #7f8c8d;
            margin-bottom: 8px;
        }
        .patent-abstract {
            font-size: 13px;
            color: #555;
            line-height: 1.5;
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
        .modal-content {
            background-color: white;
            margin: 50px auto;
            padding: 30px;
            border-radius: 10px;
            width: 90%;
            max-width: 1000px;
            max-height: 80vh;
            overflow-y: auto;
            position: relative;
        }
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover {
            color: #000;
        }
        .detail-section {
            margin-bottom: 25px;
        }
        .detail-label {
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 8px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .detail-content {
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
            font-size: 14px;
            line-height: 1.6;
        }
        .person-tag {
            display: inline-block;
            padding: 4px 10px;
            margin: 3px;
            background: #e8f4fd;
            border: 1px solid #b8e0ff;
            border-radius: 15px;
            font-size: 13px;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #7f8c8d;
        }
        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #3498db;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Patent Search System</h1>
        <p>Click any patent to view full details</p>
    </div>
    
    <div class="container">
        <div class="panel">
            <h2>Search Patents</h2>
            <textarea id="description" placeholder="Paste patent description or invention details..."></textarea>
            <button class="btn" id="searchBtn" onclick="search()">Search Patents</button>
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
    
    <!-- Patent Detail Modal -->
    <div id="patentModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <div id="modalContent">
                <div class="loading">
                    <div class="spinner"></div>
                    <p>Loading patent details...</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentSearchId = null;
        
        async function search() {
            const description = document.getElementById('description').value.trim();
            if (!description) {
                alert('Please enter a description');
                return;
            }
            
            const btn = document.getElementById('searchBtn');
            const results = document.getElementById('results');
            
            btn.disabled = true;
            btn.textContent = 'Searching...';
            results.innerHTML = '<div class="loading"><div class="spinner"></div><p>Searching patents...</p></div>';
            
            try {
                const response = await fetch('/api/professional-search', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({invention_description: description})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    currentSearchId = data.search_id;
                    displayResults(data.report);
                } else {
                    results.innerHTML = '<p style="color: red;">Error: ' + (data.error || 'Search failed') + '</p>';
                }
            } catch (error) {
                results.innerHTML = '<p style="color: red;">Error: ' + error.message + '</p>';
            } finally {
                btn.disabled = false;
                btn.textContent = 'Search Patents';
            }
        }
        
        function displayResults(report) {
            const resultsDiv = document.getElementById('results');
            let html = '<p style="margin-bottom: 15px;">Found <strong>' + report.total_results + '</strong> patents';
            html += ' (<strong>' + report.high_relevance + '</strong> high relevance)</p>';
            
            if (report.results.length === 0) {
                html += '<p style="color: #999; text-align: center; padding: 20px;">No matching patents found.</p>';
            } else {
                report.results.forEach((patent, i) => {
                    html += `<div class="patent-item" onclick="showPatentDetails('${patent.patent_number}')">`;\n                    html += '<div class="patent-header">';
                    html += '<span class="patent-number">#' + (i+1) + ' - ' + patent.patent_number + '</span>';
                    html += '<span class="relevance-badge relevance-' + patent.relevance_level + '">';
                    html += patent.relevance_level + ' (' + Math.round(patent.relevance_score * 100) + '%)';
                    html += '</span>';
                    html += '</div>';
                    html += '<div class="patent-title">' + patent.title + '</div>';
                    html += '<div class="patent-meta">';
                    html += '📅 ' + patent.pub_date + ' | Year: ' + patent.year;
                    if (patent.assignees && patent.assignees.length > 0) {
                        html += ' | 🏢 ' + patent.assignees[0];
                    }
                    if (patent.inventors && patent.inventors.length > 0) {
                        html += ' | 👤 ' + patent.inventors.slice(0, 2).join(', ');
                        if (patent.inventors.length > 2) html += '...';
                    }
                    html += '</div>';
                    if (patent.abstract) {
                        html += '<div class="patent-abstract">' + patent.abstract + '...</div>';
                    }
                    html += '</div>';
                });
            }
            
            resultsDiv.innerHTML = html;
        }
        
        async function showPatentDetails(patentNumber) {
            const modal = document.getElementById('patentModal');
            const modalContent = document.getElementById('modalContent');
            
            modal.style.display = 'block';
            modalContent.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading patent details...</p></div>';
            
            try {
                const response = await fetch('/api/patent/' + currentSearchId + '/' + patentNumber);
                const data = await response.json();
                
                if (data.success) {
                    displayPatentDetails(data.patent);
                } else {
                    modalContent.innerHTML = '<p style="color: red;">Error loading patent details</p>';
                }
            } catch (error) {
                modalContent.innerHTML = '<p style="color: red;">Error: ' + error.message + '</p>';
            }
        }
        
        function displayPatentDetails(patent) {
            const modalContent = document.getElementById('modalContent');
            
            let html = '<h2 style="color: #2c3e50; margin-bottom: 20px;">' + patent.pub_number + '</h2>';
            
            // Title
            html += '<div class="detail-section">';
            html += '<div class="detail-label">Title</div>';
            html += '<div class="detail-content">' + (patent.title || 'N/A') + '</div>';
            html += '</div>';
            
            // Basic Info
            html += '<div class="detail-section">';
            html += '<div class="detail-label">Basic Information</div>';
            html += '<div class="detail-content">';
            html += '<strong>Publication Date:</strong> ' + patent.pub_date + '<br>';
            html += '<strong>Year:</strong> ' + patent.year + '<br>';
            if (patent.relevance_score) {
                html += '<strong>Relevance Score:</strong> ' + Math.round(patent.relevance_score * 100) + '%<br>';
            }
            html += '</div>';
            html += '</div>';
            
            // Assignees
            if (patent.assignees && patent.assignees.length > 0) {
                html += '<div class="detail-section">';
                html += '<div class="detail-label">Assignees / Companies</div>';
                html += '<div class="detail-content">';
                patent.assignees.forEach(ass => {
                    const name = ass.name || ass;
                    html += '<span class="person-tag">🏢 ' + name + '</span>';
                });
                html += '</div>';
                html += '</div>';
            }
            
            // Inventors
            if (patent.inventors && patent.inventors.length > 0) {
                html += '<div class="detail-section">';
                html += '<div class="detail-label">Inventors</div>';
                html += '<div class="detail-content">';
                patent.inventors.forEach(inv => {
                    const name = inv.name || inv;
                    html += '<span class="person-tag">👤 ' + name + '</span>';
                });
                html += '</div>';
                html += '</div>';
            }
            
            // Applicants
            if (patent.applicants && patent.applicants.length > 0) {
                html += '<div class="detail-section">';
                html += '<div class="detail-label">Applicants</div>';
                html += '<div class="detail-content">';
                patent.applicants.forEach(app => {
                    const name = app.name || app;
                    html += '<span class="person-tag">📝 ' + name + '</span>';
                });
                html += '</div>';
                html += '</div>';
            }
            
            // Abstract
            if (patent.abstract_text) {
                html += '<div class="detail-section">';
                html += '<div class="detail-label">Abstract</div>';
                html += '<div class="detail-content">' + patent.abstract_text + '</div>';
                html += '</div>';
            }
            
            // Description (limited to first 5000 chars for display)
            if (patent.description_text) {
                const description = patent.description_text.substring(0, 5000);
                html += '<div class="detail-section">';
                html += '<div class="detail-label">Description</div>';
                html += '<div class="detail-content">';
                html += description;
                if (patent.description_text.length > 5000) {
                    html += '... <em>(truncated for display)</em>';
                }
                html += '</div>';
                html += '</div>';
            }
            
            modalContent.innerHTML = html;
        }
        
        function closeModal() {
            document.getElementById('patentModal').style.display = 'none';
        }
        
        // Close modal when clicking outside
        window.onclick = function(event) {
            const modal = document.getElementById('patentModal');
            if (event.target == modal) {
                modal.style.display = 'none';
            }
        }
    </script>
</body>
</html>
'''

@app.route("/")
def home():
    """Serve the professional search interface"""
    return SEARCH_HTML

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    """Smart patent search"""
    try:
        data = request.get_json()
        invention_description = data.get('invention_description', '')
        
        if not invention_description:
            return jsonify({'error': 'Description required'}), 400
        
        search_id = str(uuid.uuid4())
        
        # Extract concepts
        concepts = search_engine.extract_technical_concepts(invention_description)
        
        # Search
        results = search_engine.search_with_concepts(concepts, search_id)
        
        # Score
        scored_results = search_engine.score_results_by_concepts(results, concepts, search_id, invention_description)
        
        # Cache full results for detail view
        search_results_cache[search_id] = scored_results
        
        # Generate report
        report = {
            'search_id': search_id,
            'concepts_found': concepts,
            'total_results': len(scored_results),
            'high_relevance': sum(1 for r in scored_results if r.get('relevance_score', 0) > 0.15),
            'results': []
        }
        
        # Process for display
        for patent in scored_results[:50]:
            score = patent.get('relevance_score', 0)
            level = 'H' if score >= 0.65 else 'M' if score >= 0.35 else 'L'
            
            assignees = []
            if patent.get('assignees'):
                for ass in patent.get('assignees', []):
                    if isinstance(ass, dict) and ass.get('name'):
                        assignees.append(ass['name'])
            
            inventors = []
            if patent.get('inventors'):
                for inv in patent.get('inventors', []):
                    if isinstance(inv, dict) and inv.get('name'):
                        inventors.append(inv['name'])
            
            report['results'].append({
                'patent_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'pub_date': str(patent.get('pub_date')),
                'year': patent.get('year'),
                'relevance_level': level,
                'relevance_score': score,
                'assignees': assignees,
                'inventors': inventors[:3],  # First 3 inventors
                'abstract': (patent.get('abstract_text') or '')[:200]
            })
        
        return jsonify({
            'success': True,
            'search_id': search_id,
            'report': report
        })
        
    except Exception as e:
        logging.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/patent/<search_id>/<patent_number>', methods=['GET'])
def get_patent_details(search_id, patent_number):
    """Get full patent details from cache"""
    if search_id in search_results_cache:
        for patent in search_results_cache[search_id]:
            if patent.get('pub_number') == patent_number:
                return jsonify({
                    'success': True,
                    'patent': patent
                })
    
            # Fallback to database query
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            try:
                query = """
                SELECT * FROM patent_data_unified
                WHERE pub_number = %s
                """
                cur.execute(query, (patent_number,))
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
