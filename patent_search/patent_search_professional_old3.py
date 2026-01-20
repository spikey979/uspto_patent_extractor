#!/usr/bin/env python3
"""
Smart Patent Search with Better Technical Term Extraction
Focuses on technical concepts and domain-specific terms
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

# Ollama configuration
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434/api/generate')
MODEL_NAME = os.environ.get('MODEL_NAME', 'gpt-oss:20b')

# Store for search progress
search_progress = {}

class SmartPatentSearch:
    def __init__(self):
        # Technical term patterns that indicate important concepts
        self.technical_patterns = [
            r'\b[a-z]+(?:tion|ment|ator|izer|ance|ence|able|ible)\b',  # Technical suffixes
            r'\b(?:pre|post|anti|micro|nano|bio|electro|thermo|cryo)[a-z]+\b',  # Technical prefixes
            r'\b[a-z]+(?:ic|al|ous|ive|ary|ory)\b',  # Scientific adjectives
        ]
        
        # Domain-specific important terms
        self.domain_terms = {
            'medical': ['catheter', 'ablation', 'cardiac', 'arrhythmia', 'tissue', 'necrosis', 
                       'surgical', 'implant', 'diagnostic', 'therapeutic', 'balloon', 'distal',
                       'proximal', 'vascular', 'endoscopic', 'laparoscopic'],
            'energy': ['cryogenic', 'thermal', 'electrical', 'ultrasonic', 'radiofrequency',
                      'laser', 'microwave', 'acoustic', 'electromagnetic'],
            'control': ['pressure', 'temperature', 'flow', 'valve', 'sensor', 'feedback',
                       'regulation', 'monitoring', 'measurement'],
            'procedure': ['procedure', 'method', 'technique', 'process', 'treatment',
                         'therapy', 'intervention', 'operation']
        }
        
        # Common words to exclude
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'more', 'specifically', 'relates', 'involves', 'during', 'time'
        }
    
    def extract_technical_concepts(self, text: str) -> Dict[str, List[str]]:
        """Extract technical concepts and domain-specific terms"""
        text_lower = text.lower()
        
        concepts = {
            'primary_terms': [],      # Most important technical terms
            'medical_terms': [],       # Medical/device specific
            'method_terms': [],        # Process/method related
            'component_terms': [],     # Device components
            'combined_phrases': []     # Multi-word technical phrases
        }
        
        # Extract medical device terms
        medical_pattern = r'\b(?:catheter|ablation|cardiac|arrhythmia|cryogenic|balloon|tissue|necrosis|heart|vascular|surgical|medical|device)s?\b'
        medical_matches = re.findall(medical_pattern, text_lower)
        concepts['medical_terms'] = list(set(medical_matches))
        
        # Extract method/procedure terms
        method_pattern = r'\b(?:method|procedure|delivering|controlling|positioning|blocking|creating|treating|ablating)s?\b'
        method_matches = re.findall(method_pattern, text_lower)
        concepts['method_terms'] = list(set(method_matches))
        
        # Extract component terms
        component_pattern = r'\b(?:tip|device|system|apparatus|mechanism|element|member|portion|chamber|channel|lumen|valve|sensor)s?\b'
        component_matches = re.findall(component_pattern, text_lower)
        concepts['component_terms'] = list(set(component_matches))
        
        # Extract important multi-word phrases
        phrases = [
            'cryoablation balloon',
            'balloon catheter',
            'cardiac arrhythmia',
            'ablative energy',
            'electrical conduction',
            'diseased tissue',
            'tissue necrosis',
            'cryogenic energy',
            'distal tip',
            'pressure control',
            'medical device',
            'catheter ablation'
        ]
        
        for phrase in phrases:
            if phrase in text_lower:
                concepts['combined_phrases'].append(phrase)
        
        # Also extract 2-3 word combinations that appear in the text
        words = text_lower.split()
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            # Check if both words are technical (not stop words)
            if (words[i] not in self.stop_words and words[i+1] not in self.stop_words and
                len(words[i]) > 3 and len(words[i+1]) > 3):
                # Check if it's a technical combination
                if any(term in bigram for term in ['ablation', 'catheter', 'cardiac', 'cryogenic', 'balloon', 'pressure']):
                    concepts['combined_phrases'].append(bigram)
        
        # Deduplicate combined phrases
        concepts['combined_phrases'] = list(set(concepts['combined_phrases']))[:10]
        
        # Determine primary terms (most important for search)
        all_important = (
            concepts['medical_terms'][:5] + 
            concepts['combined_phrases'][:3] +
            concepts['method_terms'][:2]
        )
        concepts['primary_terms'] = all_important
        
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
                    'message': 'Searching patent database with technical concepts...'
                }
            
            # Build search query with different weights for different concept types
            conditions = []
            params = []
            
            # Priority 1: Search for multi-word phrases (most specific)
            for phrase in concepts['combined_phrases'][:5]:
                conditions.append("""
                    (LOWER(u.title) LIKE %s OR 
                     LOWER(u.abstract_text) LIKE %s OR
                     LOWER(LEFT(u.description_text, 10000)) LIKE %s)
                """)
                pattern = f'%{phrase}%'
                params.extend([pattern, pattern, pattern])
            
            # Priority 2: Medical/technical terms
            for term in concepts['medical_terms'][:8]:
                conditions.append("""
                    (LOWER(u.title) LIKE %s OR 
                     LOWER(u.abstract_text) LIKE %s OR
                     LOWER(LEFT(u.description_text, 10000)) LIKE %s)
                """)
                pattern = f'%{term}%'
                params.extend([pattern, pattern, pattern])
            
            # Priority 3: Method terms (less specific but important)
            for term in concepts['method_terms'][:3]:
                conditions.append("""
                    (LOWER(u.abstract_text) LIKE %s OR
                     LOWER(LEFT(u.description_text, 5000)) LIKE %s)
                """)
                pattern = f'%{term}%'
                params.extend([pattern, pattern])
            
            if not conditions:
                return []
            
            query = f"""
            SELECT 
                u.pub_number,
                u.title,
                u.abstract_text,
                LEFT(u.description_text, 3000) as description_text,
                u.pub_date,
                u.year,
                u.inventors,
                u.assignees
            FROM patent_data_unified u
            WHERE {' OR '.join(conditions)}
            ORDER BY u.year DESC
            LIMIT 300
            """
            
            if search_id:
                search_progress[search_id] = {
                    'status': 'searching',
                    'progress': 50,
                    'message': 'Retrieving matching patents...'
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
    
    def score_results_by_concepts(self, results: List[Dict], concepts: Dict[str, List[str]], search_id: str) -> List[Dict]:
        """Score results based on concept matching"""
        if not results:
            return []
        
        if search_id:
            search_progress[search_id] = {
                'status': 'ranking',
                'progress': 70,
                'message': 'Analyzing patent relevance...'
            }
        
        for patent in results:
            score = 0
            matches = {'phrases': 0, 'medical': 0, 'method': 0, 'component': 0}
            
            # Combine all text for searching
            full_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')} {patent.get('description_text', '')}".lower()
            
            # Score multi-word phrases (highest weight)
            for phrase in concepts['combined_phrases']:
                if phrase in full_text:
                    score += 10
                    matches['phrases'] += 1
            
            # Score medical terms
            for term in concepts['medical_terms']:
                if term in full_text:
                    score += 5
                    matches['medical'] += 1
            
            # Score method terms
            for term in concepts['method_terms']:
                if term in full_text:
                    score += 3
                    matches['method'] += 1
            
            # Score component terms
            for term in concepts['component_terms']:
                if term in full_text:
                    score += 2
                    matches['component'] += 1
            
            # Bonus for matching multiple categories
            categories_matched = sum(1 for v in matches.values() if v > 0)
            if categories_matched >= 3:
                score += 10  # Bonus for comprehensive match
            
            # Normalize score
            max_possible = 30 # len(concepts['combined_phrases']) * 10 + len(concepts['medical_terms']) * 5 + 20
            patent['relevance_score'] = min(score / max_possible, 1.0) if max_possible > 0 else 0
            patent['match_details'] = matches
        
        # Sort by relevance
        results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        
        return results
    
    def use_ai_for_top_results(self, results: List[Dict], original_text: str, search_id: str):
        """Quick AI check for top results only"""
        if not results or len(results) == 0:
            return
        
        try:
            if search_id:
                search_progress[search_id] = {
                    'status': 'analyzing',
                    'progress': 85,
                    'message': 'AI refining top results...'
                }
            
            # Only process top 5 for speed
            top_5 = results[:5]
            
            prompt = f"""Compare these patents to this invention:
Invention: {original_text[:300]}

Patents:
1. {top_5[0].get('title', '') if len(top_5) > 0 else ''}
2. {top_5[1].get('title', '') if len(top_5) > 1 else ''}
3. {top_5[2].get('title', '') if len(top_5) > 2 else ''}
4. {top_5[3].get('title', '') if len(top_5) > 3 else ''}
5. {top_5[4].get('title', '') if len(top_5) > 4 else ''}

Rate each 1-10 for relevance. Format: 1:8, 2:6, etc.
Scores:"""
            
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,
                    'num_predict': 50
                }
            }, timeout=3)
            
            if response.status_code == 200:
                scores_text = response.json().get('response', '')
                for match in re.finditer(r'(\d+):(\d+)', scores_text):
                    idx = int(match.group(1)) - 1
                    score = int(match.group(2))
                    if 0 <= idx < len(top_5):
                        # Blend AI score with concept score
                        current = top_5[idx].get('relevance_score', 0)
                        top_5[idx]['relevance_score'] = (current * 0.6 + score/10 * 0.4)
                
                # Re-sort top 5
                top_5.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
                
                # Update main results list
                for i, patent in enumerate(top_5):
                    results[i] = patent
                    
        except Exception as e:
            logging.info(f"AI refinement skipped: {e}")
    
    def generate_report(self, results: List[Dict], concepts: Dict[str, List[str]], search_id: str) -> Dict:
        """Generate report with concept analysis"""
        if search_id:
            search_progress[search_id] = {
                'status': 'finalizing',
                'progress': 95,
                'message': 'Generating report...'
            }
        
        report = {
            'concepts_found': {
                'technical_phrases': concepts['combined_phrases'][:5],
                'medical_terms': concepts['medical_terms'][:5],
                'method_terms': concepts['method_terms'][:3]
            },
            'total_results': len(results),
            'high_relevance': sum(1 for r in results if r.get('relevance_score', 0) > 0.5),
            'results': []
        }
        
        # Process top 20 results
        for patent in results[:20]:
            score = patent.get('relevance_score', 0)
            
            # Determine level
            if score > 0.15:
                level = 'H'
            elif score > 0.08:
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
                'match_details': patent.get('match_details', {}),
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
search_engine = SmartPatentSearch()

@app.route('/')
def home():
    return render_template_string(SEARCH_HTML)

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    """Smart patent search with concept extraction"""
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
            'message': 'Extracting technical concepts...'
        }
        
        # Extract technical concepts
        concepts = search_engine.extract_technical_concepts(invention_description)
        
        # Search with concepts
        results = search_engine.search_with_concepts(concepts, search_id)
        
        # Score results
        scored_results = search_engine.score_results_by_concepts(results, concepts, search_id)
        
        # Optional AI refinement for top results
        search_engine.use_ai_for_top_results(scored_results, invention_description, search_id)
        
        # Generate report
        report = search_engine.generate_report(scored_results, concepts, search_id)
        
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

# HTML interface
SEARCH_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Patent Search System</title>
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
        .concepts {
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .concept-group {
            margin: 10px 0;
        }
        .concept-label {
            font-weight: 600;
            color: #555;
            margin-bottom: 5px;
        }
        .concept-tag {
            display: inline-block;
            padding: 3px 10px;
            margin: 3px;
            border-radius: 15px;
            font-size: 12px;
        }
        .phrase-tag {
            background: #27ae60;
            color: white;
        }
        .medical-tag {
            background: #e74c3c;
            color: white;
        }
        .method-tag {
            background: #8e44ad;
            color: white;
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
        .match-info {
            font-size: 11px;
            color: #666;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Smart Patent Search System</h1>
        <p>Technical concept extraction and intelligent matching</p>
    </div>
    
    <div class="container">
        <div class="panel">
            <h2>Search Patents</h2>
            <textarea id="description" placeholder="Paste patent description or invention details..."></textarea>
            <button class="btn" id="searchBtn" onclick="search()">Search Patents</button>
            
            <div class="progress-container" id="progressContainer">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill">0%</div>
                </div>
                <div class="progress-message" id="progressMessage">Starting search...</div>
            </div>
            
            <div class="concepts" id="concepts" style="display: none;">
                <strong>Technical Concepts Found:</strong>
                <div id="conceptsList"></div>
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
                    
                    // Display results after progress completes
                    setTimeout(() => {
                        clearInterval(progressTimer);
                        displayResults(data.report);
                        progressContainer.classList.remove('active');
                    }, 3000);
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
            // Show concepts
            const conceptsDiv = document.getElementById('concepts');
            const conceptsList = document.getElementById('conceptsList');
            conceptsDiv.style.display = 'block';
            
            let conceptsHtml = '';
            
            if (report.concepts_found.technical_phrases && report.concepts_found.technical_phrases.length > 0) {
                conceptsHtml += '<div class="concept-group">';
                conceptsHtml += '<div class="concept-label">Technical Phrases:</div>';
                report.concepts_found.technical_phrases.forEach(phrase => {
                    conceptsHtml += '<span class="concept-tag phrase-tag">' + phrase + '</span>';
                });
                conceptsHtml += '</div>';
            }
            
            if (report.concepts_found.medical_terms && report.concepts_found.medical_terms.length > 0) {
                conceptsHtml += '<div class="concept-group">';
                conceptsHtml += '<div class="concept-label">Medical/Device Terms:</div>';
                report.concepts_found.medical_terms.forEach(term => {
                    conceptsHtml += '<span class="concept-tag medical-tag">' + term + '</span>';
                });
                conceptsHtml += '</div>';
            }
            
            conceptsList.innerHTML = conceptsHtml;
            
            // Show results
            const resultsDiv = document.getElementById('results');
            let html = '<p>Found ' + report.total_results + ' patents (' + report.high_relevance + ' high relevance)</p>';
            
            if (report.results.length === 0) {
                html += '<p style="color: #999; text-align: center; padding: 20px;">No matching patents found. Try different search terms.</p>';
            } else {
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
                    
                    // Show match details
                    if (patent.match_details) {
                        html += '<div class="match-info">Matches: ';
                        if (patent.match_details.phrases > 0) html += 'Phrases: ' + patent.match_details.phrases + ' ';
                        if (patent.match_details.medical > 0) html += 'Medical: ' + patent.match_details.medical + ' ';
                        if (patent.match_details.method > 0) html += 'Methods: ' + patent.match_details.method + ' ';
                        html += '</div>';
                    }
                    
                    if (patent.abstract) {
                        html += '<p style="margin-top: 10px; font-size: 14px;">' + patent.abstract + '...</p>';
                    }
                    html += '</div>';
                });
            }
            
            resultsDiv.innerHTML = html;
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8092))
    app.run(host='0.0.0.0', port=port, debug=False)
