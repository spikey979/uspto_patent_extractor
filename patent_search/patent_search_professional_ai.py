#!/usr/bin/env python3
"""
AI-Enhanced Patent Search System
Uses LLM for intelligent keyword extraction and relevance scoring
"""

from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor, Json
import json
import re
import os
import requests
import logging
from datetime import datetime
from typing import List, Dict, Tuple
import hashlib
import uuid
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

class AIPatentSearch:
    def __init__(self):
        self.technical_domains = {
            'medical': ['catheter', 'ablation', 'cardiac', 'surgical', 'implant', 'diagnostic', 'therapeutic'],
            'electronics': ['circuit', 'processor', 'memory', 'sensor', 'display', 'semiconductor', 'transistor'],
            'software': ['algorithm', 'database', 'interface', 'network', 'protocol', 'encryption', 'compression'],
            'mechanical': ['gear', 'bearing', 'valve', 'pump', 'actuator', 'mechanism', 'assembly'],
            'chemical': ['polymer', 'catalyst', 'compound', 'synthesis', 'reaction', 'formulation', 'composition']
        }
    
    def extract_keywords_with_ai(self, text: str, search_id: str) -> Dict:
        """Use AI to extract meaningful technical keywords and concepts"""
        
        # Update progress
        search_progress[search_id] = {
            'status': 'analyzing',
            'progress': 15,
            'message': 'AI analyzing invention description...'
        }
        
        prompt = f"""Analyze this patent/invention description and extract:
1. Primary technical keywords (specific components, methods, materials)
2. Technical field/domain
3. Key concepts and terminology
4. Related technical terms that might appear in similar patents

Description: {text[:2000]}

Return a JSON object with these keys:
- primary_keywords: list of 5-10 most important technical terms
- technical_field: main technical domain
- concepts: list of 3-5 broader concepts
- related_terms: list of 5-10 related technical terms
- search_queries: list of 3-5 optimized search phrases

Focus on technical terminology that would appear in patent descriptions.
JSON:"""
        
        try:
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.3,
                    'num_predict': 500
                }
            }, timeout=30)
            
            if response.status_code == 200:
                result = response.json().get('response', '{}')
                # Extract JSON from response
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    extracted = json.loads(json_match.group())
                    
                    # Ensure all expected keys exist
                    extracted.setdefault('primary_keywords', [])
                    extracted.setdefault('technical_field', '')
                    extracted.setdefault('concepts', [])
                    extracted.setdefault('related_terms', [])
                    extracted.setdefault('search_queries', [])
                    
                    return extracted
        except Exception as e:
            logging.error(f"AI keyword extraction failed: {e}")
        
        # Fallback to basic extraction
        return self.extract_keywords_fallback(text)
    
    def extract_keywords_fallback(self, text: str) -> Dict:
        """Fallback keyword extraction without AI"""
        # Extract technical terms using patterns
        text_lower = text.lower()
        
        # Find technical terms (words with specific patterns)
        technical_terms = re.findall(r'\b[a-z]{3,}(?:ing|tion|ment|able|ator|izer|ical|onic)\b', text_lower)
        compound_terms = re.findall(r'\b[a-z]+[-\s][a-z]+\b', text_lower)
        
        # Combine and deduplicate
        all_terms = list(set(technical_terms[:10] + compound_terms[:5]))
        
        return {
            'primary_keywords': all_terms[:10],
            'technical_field': 'general',
            'concepts': all_terms[:5],
            'related_terms': [],
            'search_queries': [' '.join(all_terms[:3])]
        }
    
    def search_patents_smart(self, keywords_data: Dict, search_id: str, limit: int = 100) -> List[Dict]:
        """Smart patent search using AI-extracted keywords"""
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Update progress
        search_progress[search_id] = {
            'status': 'searching',
            'progress': 30,
            'message': 'Searching patent database with AI-optimized queries...'
        }
        
        try:
            all_results = []
            seen_patents = set()
            
            # Combine all keywords for search
            search_terms = (
                keywords_data.get('primary_keywords', [])[:10] +
                keywords_data.get('concepts', [])[:3] +
                keywords_data.get('related_terms', [])[:5]
            )
            
            # Remove duplicates and empty terms
            search_terms = list(set(term for term in search_terms if term and len(term) > 2))
            
            if not search_terms:
                return []
            
            # Build optimized search query
            # Use full-text search for better performance
            search_conditions = []
            params = []
            
            # Search in batches for better performance
            for term in search_terms[:15]:  # Limit to top 15 terms
                search_conditions.append("""
                    (LOWER(u.title) LIKE %s OR 
                     LOWER(u.abstract_text) LIKE %s OR
                     LOWER(SUBSTRING(u.description_text, 1, 10000)) LIKE %s)
                """)
                pattern = f'%{term.lower()}%'
                params.extend([pattern, pattern, pattern])
            
            query = f"""
            SELECT 
                u.pub_number,
                u.title,
                u.abstract_text,
                LEFT(u.description_text, 5000) as description_text,
                u.pub_date,
                u.year,
                u.inventors,
                u.assignees
            FROM patent_data_unified u
            WHERE {' OR '.join(search_conditions)}
            ORDER BY u.pub_date DESC
            LIMIT %s
            """
            
            params.append(limit * 2)  # Get more for AI ranking
            
            # Update progress
            search_progress[search_id] = {
                'status': 'searching',
                'progress': 50,
                'message': 'Retrieving matching patents...'
            }
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            # Process results
            for patent in results:
                if patent['pub_number'] not in seen_patents:
                    seen_patents.add(patent['pub_number'])
                    
                    # Parse JSON fields
                    for field in ['inventors', 'assignees']:
                        if patent.get(field) and isinstance(patent[field], str):
                            try:
                                patent[field] = json.loads(patent[field])
                            except:
                                patent[field] = []
                    
                    all_results.append(patent)
            
            return all_results[:limit]
            
        except Exception as e:
            logging.error(f"Search error: {e}")
            return []
        finally:
            cur.close()
            conn.close()
    
    def rank_results_with_ai(self, results: List[Dict], original_description: str, keywords_data: Dict, search_id: str) -> List[Dict]:
        """Use AI to rank search results by relevance"""
        
        if not results:
            return []
        
        # Update progress
        search_progress[search_id] = {
            'status': 'ranking',
            'progress': 70,
            'message': 'AI analyzing relevance of results...'
        }
        
        # For performance, only send top results to AI for detailed ranking
        top_results = results[:20]
        
        # Create a batch relevance check
        patents_summary = []
        for i, patent in enumerate(top_results):
            summary = f"{i}. {patent.get('title', '')} - {(patent.get('abstract_text', '') or '')[:200]}"
            patents_summary.append(summary)
        
        prompt = f"""Compare these patents to the target invention and score relevance (0-100):

Target Invention: {original_description[:500]}
Key concepts: {', '.join(keywords_data.get('primary_keywords', [])[:5])}

Patents:
{chr(10).join(patents_summary[:10])}

For each patent number (0-9), provide a relevance score and brief reason.
Format: 
0: [score] - [reason]
1: [score] - [reason]
etc."""
        
        relevance_scores = {}
        
        try:
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.3,
                    'num_predict': 500
                }
            }, timeout=30)
            
            if response.status_code == 200:
                result = response.json().get('response', '')
                
                # Parse scores from response
                lines = result.split('\n')
                for line in lines:
                    match = re.match(r'(\d+):\s*(\d+)', line)
                    if match:
                        idx = int(match.group(1))
                        score = int(match.group(2))
                        if 0 <= idx < len(top_results):
                            relevance_scores[idx] = score / 100.0
        except Exception as e:
            logging.error(f"AI ranking failed: {e}")
        
        # Apply AI scores to results
        for i, patent in enumerate(top_results):
            if i in relevance_scores:
                patent['ai_relevance_score'] = relevance_scores[i]
            else:
                # Fallback scoring based on keyword matches
                patent['ai_relevance_score'] = self.calculate_keyword_relevance(
                    patent, keywords_data.get('primary_keywords', [])
                )
        
        # Sort by AI relevance score
        top_results.sort(key=lambda x: x.get('ai_relevance_score', 0), reverse=True)
        
        # Add remaining results with basic scoring
        remaining = results[20:]
        for patent in remaining:
            patent['ai_relevance_score'] = self.calculate_keyword_relevance(
                patent, keywords_data.get('primary_keywords', [])
            )
        
        # Combine and return
        return top_results + remaining
    
    def calculate_keyword_relevance(self, patent: Dict, keywords: List[str]) -> float:
        """Calculate basic keyword-based relevance"""
        text = f"{patent.get('title', '')} {patent.get('abstract_text', '')} {patent.get('description_text', '')[:1000]}".lower()
        
        matches = 0
        for keyword in keywords:
            if keyword.lower() in text:
                matches += 1
        
        return matches / len(keywords) if keywords else 0.0
    
    def generate_report(self, description: str, keywords_data: Dict, results: List[Dict], search_id: str) -> Dict:
        """Generate report with AI insights"""
        
        # Update progress
        search_progress[search_id] = {
            'status': 'finalizing',
            'progress': 90,
            'message': 'Generating report...'
        }
        
        report = {
            'report_id': hashlib.md5(description.encode()).hexdigest()[:8],
            'generated_date': datetime.now().isoformat(),
            'ai_analysis': {
                'technical_field': keywords_data.get('technical_field', 'Unknown'),
                'primary_keywords': keywords_data.get('primary_keywords', []),
                'concepts': keywords_data.get('concepts', []),
                'related_terms': keywords_data.get('related_terms', [])
            },
            'summary': {
                'total_results': len(results),
                'high_relevance_count': sum(1 for r in results if r.get('ai_relevance_score', 0) > 0.7),
                'medium_relevance_count': sum(1 for r in results if 0.4 <= r.get('ai_relevance_score', 0) <= 0.7),
                'low_relevance_count': sum(1 for r in results if r.get('ai_relevance_score', 0) < 0.4)
            },
            'results': []
        }
        
        # Process top results for report
        for patent in results[:20]:
            relevance_score = patent.get('ai_relevance_score', 0)
            
            # Determine relevance level
            if relevance_score > 0.7:
                relevance_level = 'H'
            elif relevance_score > 0.4:
                relevance_level = 'M'
            else:
                relevance_level = 'L'
            
            # Extract assignee names
            assignees = []
            if patent.get('assignees'):
                for ass in patent.get('assignees', []):
                    if isinstance(ass, dict) and ass.get('name'):
                        assignees.append(ass['name'])
            
            report['results'].append({
                'patent_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'pub_date': str(patent.get('pub_date')),
                'relevance_level': relevance_level,
                'ai_relevance_score': relevance_score,
                'assignees': assignees,
                'abstract': (patent.get('abstract_text') or '')[:300],
                'description_snippet': (patent.get('description_text') or '')[:300]
            })
        
        # Final progress update
        search_progress[search_id] = {
            'status': 'complete',
            'progress': 100,
            'message': 'Search complete!'
        }
        
        return report

# Initialize search engine
search_engine = AIPatentSearch()

@app.route('/')
def home():
    """Serve the search interface"""
    return render_template_string(SEARCH_INTERFACE_HTML)

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    """AI-enhanced patent search"""
    try:
        data = request.get_json()
        invention_description = data.get('invention_description', '')
        
        if not invention_description:
            return jsonify({'error': 'Invention description is required'}), 400
        
        # Generate search ID
        search_id = str(uuid.uuid4())
        
        # Initialize progress
        search_progress[search_id] = {
            'status': 'starting',
            'progress': 10,
            'message': 'Initializing AI-powered search...'
        }
        
        # Extract keywords with AI
        keywords_data = search_engine.extract_keywords_with_ai(invention_description, search_id)
        
        # Perform smart search
        search_results = search_engine.search_patents_smart(keywords_data, search_id, limit=100)
        
        # Rank results with AI
        ranked_results = search_engine.rank_results_with_ai(
            search_results, 
            invention_description, 
            keywords_data, 
            search_id
        )
        
        # Generate report
        report = search_engine.generate_report(
            invention_description,
            keywords_data,
            ranked_results,
            search_id
        )
        
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
    """Get search progress"""
    progress = search_progress.get(search_id, {
        'status': 'not_found',
        'progress': 0,
        'message': 'Search not found'
    })
    return jsonify(progress)

# Keep the same HTML interface but update to show AI-extracted keywords
SEARCH_INTERFACE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI-Enhanced Patent Search</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }
        .header {
            background: #1a1a2e;
            color: white;
            padding: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .header-content {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 20px;
        }
        .header h1 {
            font-size: 24px;
            font-weight: 600;
        }
        .header p {
            font-size: 14px;
            opacity: 0.9;
            margin-top: 5px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .search-panel {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        .results-panel {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            max-height: calc(100vh - 120px);
            overflow-y: auto;
        }
        .section-title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            color: #1a1a2e;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: #555;
        }
        textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 5px;
            font-size: 14px;
            resize: vertical;
            min-height: 200px;
        }
        textarea:focus {
            outline: none;
            border-color: #4a90e2;
        }
        .btn {
            background: #4a90e2;
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
            transition: background 0.3s;
        }
        .btn:hover {
            background: #357abd;
        }
        .btn:disabled {
            background: #bdc3c7;
            cursor: not-allowed;
        }
        .progress-bar {
            width: 100%;
            height: 30px;
            background: #ecf0f1;
            border-radius: 15px;
            overflow: hidden;
            margin: 20px 0;
            display: none;
        }
        .progress-bar.active {
            display: block;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #4a90e2, #357abd);
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 12px;
            font-weight: 600;
        }
        .progress-message {
            text-align: center;
            color: #7f8c8d;
            font-size: 14px;
            margin-top: 10px;
        }
        .ai-insights {
            background: #e8f4fd;
            border: 1px solid #b8e0ff;
            border-radius: 5px;
            padding: 15px;
            margin-bottom: 20px;
        }
        .ai-insights h4 {
            font-size: 16px;
            margin-bottom: 10px;
            color: #2c3e50;
        }
        .keyword-group {
            margin-bottom: 10px;
        }
        .keyword-label {
            font-weight: 600;
            color: #555;
            margin-bottom: 5px;
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
        .concept-tag {
            background: #27ae60;
        }
        .related-tag {
            background: #8e44ad;
        }
        .patent-item {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
            transition: all 0.3s;
        }
        .patent-item:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .patent-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 10px;
        }
        .patent-number {
            font-weight: 600;
            color: #4a90e2;
        }
        .relevance-badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            color: white;
        }
        .relevance-H { background: #27ae60; }
        .relevance-M { background: #f39c12; }
        .relevance-L { background: #95a5a6; }
        .ai-score {
            font-size: 11px;
            color: #666;
            margin-left: 5px;
        }
        .patent-title {
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 10px;
        }
        .patent-meta {
            font-size: 14px;
            color: #7f8c8d;
            margin-bottom: 10px;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }
        .summary-item {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            text-align: center;
        }
        .summary-item h4 {
            font-size: 14px;
            color: #7f8c8d;
            margin-bottom: 5px;
        }
        .summary-item p {
            font-size: 20px;
            font-weight: 600;
            color: #2c3e50;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>AI-Enhanced Patent Search System</h1>
            <p>Intelligent keyword extraction and relevance ranking powered by AI</p>
        </div>
    </div>

    <div class="container">
        <div class="search-panel">
            <h2 class="section-title">Patent Search Configuration</h2>
            
            <div class="form-group">
                <label>Invention Disclosure</label>
                <textarea id="inventionDescription" placeholder="Paste your invention description here. The AI will analyze it to extract technical keywords, identify the technical field, and find related concepts for comprehensive patent searching."></textarea>
            </div>
            
            <button id="searchBtn" class="btn" onclick="conductProfessionalSearch()">
                Conduct AI-Powered Search
            </button>
            
            <div class="progress-bar" id="progressBar">
                <div class="progress-fill" id="progressFill" style="width: 0%">0%</div>
            </div>
            <div class="progress-message" id="progressMessage"></div>
        </div>
        
        <div class="results-panel" id="resultsPanel">
            <h2 class="section-title">Search Results & Analysis</h2>
            <div id="resultsContent">
                <p style="color: #7f8c8d; text-align: center; padding: 40px;">
                    Enter invention details and click "Conduct AI-Powered Search" to begin analysis.
                </p>
            </div>
        </div>
    </div>

    <script>
        let currentSearchId = null;
        let progressInterval = null;
        
        async function conductProfessionalSearch() {
            const inventionDescription = document.getElementById("inventionDescription").value.trim();
            
            if (!inventionDescription) {
                alert("Please provide an invention description");
                return;
            }
            
            const searchBtn = document.getElementById("searchBtn");
            const resultsContent = document.getElementById("resultsContent");
            const progressBar = document.getElementById("progressBar");
            const progressFill = document.getElementById("progressFill");
            const progressMessage = document.getElementById("progressMessage");
            
            searchBtn.disabled = true;
            searchBtn.textContent = "AI Analyzing...";
            progressBar.classList.add("active");
            resultsContent.innerHTML = '<p style="color: #7f8c8d; text-align: center; padding: 40px;">AI is analyzing your invention description...</p>';
            
            try {
                const response = await fetch("/api/professional-search", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        invention_description: inventionDescription
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    currentSearchId = data.search_id;
                    
                    // Start progress monitoring
                    progressInterval = setInterval(updateProgress, 500);
                    
                    // Wait for completion
                    setTimeout(() => {
                        clearInterval(progressInterval);
                        progressBar.classList.remove("active");
                        displayAIReport(data.report);
                    }, 5000);
                    
                } else {
                    resultsContent.innerHTML = '<div style="padding: 20px; color: #e74c3c;">Error: ' + (data.error || "Search failed") + '</div>';
                    progressBar.classList.remove("active");
                }
                
            } catch (error) {
                resultsContent.innerHTML = '<div style="padding: 20px; color: #e74c3c;">Error: ' + error.message + '</div>';
                progressBar.classList.remove("active");
            } finally {
                searchBtn.disabled = false;
                searchBtn.textContent = "Conduct AI-Powered Search";
            }
        }
        
        async function updateProgress() {
            if (!currentSearchId) return;
            
            try {
                const response = await fetch('/api/search-progress/' + currentSearchId);
                const progress = await response.json();
                
                const progressFill = document.getElementById("progressFill");
                const progressMessage = document.getElementById("progressMessage");
                
                progressFill.style.width = progress.progress + "%";
                progressFill.textContent = progress.progress + "%";
                progressMessage.textContent = progress.message;
                
                if (progress.status === "complete") {
                    clearInterval(progressInterval);
                }
            } catch (error) {
                console.error("Error updating progress:", error);
            }
        }
        
        function displayAIReport(report) {
            const resultsContent = document.getElementById("resultsContent");
            
            let html = '';
            
            // AI Insights section
            if (report.ai_analysis) {
                html += '<div class="ai-insights">';
                html += '<h4>AI Analysis</h4>';
                
                html += '<div class="keyword-group">';
                html += '<div class="keyword-label">Technical Field: ' + report.ai_analysis.technical_field + '</div>';
                html += '</div>';
                
                if (report.ai_analysis.primary_keywords && report.ai_analysis.primary_keywords.length > 0) {
                    html += '<div class="keyword-group">';
                    html += '<div class="keyword-label">Primary Keywords:</div>';
                    report.ai_analysis.primary_keywords.forEach(kw => {
                        html += '<span class="keyword-tag">' + kw + '</span>';
                    });
                    html += '</div>';
                }
                
                if (report.ai_analysis.concepts && report.ai_analysis.concepts.length > 0) {
                    html += '<div class="keyword-group">';
                    html += '<div class="keyword-label">Key Concepts:</div>';
                    report.ai_analysis.concepts.forEach(concept => {
                        html += '<span class="keyword-tag concept-tag">' + concept + '</span>';
                    });
                    html += '</div>';
                }
                
                if (report.ai_analysis.related_terms && report.ai_analysis.related_terms.length > 0) {
                    html += '<div class="keyword-group">';
                    html += '<div class="keyword-label">Related Terms:</div>';
                    report.ai_analysis.related_terms.forEach(term => {
                        html += '<span class="keyword-tag related-tag">' + term + '</span>';
                    });
                    html += '</div>';
                }
                
                html += '</div>';
            }
            
            // Summary section
            html += '<div class="report-section">';
            html += '<h3 style="margin-bottom: 15px;">Search Summary</h3>';
            html += '<div class="summary-grid">';
            html += '<div class="summary-item">';
            html += '<h4>High Relevance</h4>';
            html += '<p>' + report.summary.high_relevance_count + '</p>';
            html += '</div>';
            html += '<div class="summary-item">';
            html += '<h4>Medium Relevance</h4>';
            html += '<p>' + report.summary.medium_relevance_count + '</p>';
            html += '</div>';
            html += '<div class="summary-item">';
            html += '<h4>Total Results</h4>';
            html += '<p>' + report.summary.total_results + '</p>';
            html += '</div>';
            html += '</div>';
            html += '</div>';
            
            // Results section
            html += '<div class="report-section">';
            html += '<h3 style="margin-bottom: 15px;">AI-Ranked Patent Results</h3>';
            
            if (report.results && report.results.length > 0) {
                report.results.forEach((patent, index) => {
                    html += '<div class="patent-item">';
                    html += '<div class="patent-header">';
                    html += '<span class="patent-number">#' + (index + 1) + ' - ' + patent.patent_number + '</span>';
                    html += '<span class="relevance-badge relevance-' + patent.relevance_level + '">';
                    html += 'Relevance: ' + patent.relevance_level;
                    html += '<span class="ai-score">(AI: ' + (patent.ai_relevance_score * 100).toFixed(0) + '%)</span>';
                    html += '</span>';
                    html += '</div>';
                    html += '<div class="patent-title">' + patent.title + '</div>';
                    html += '<div class="patent-meta">';
                    html += 'Published: ' + patent.pub_date;
                    if (patent.assignees && patent.assignees.length > 0) {
                        html += ' | Assignee: ' + patent.assignees[0];
                    }
                    html += '</div>';
                    
                    if (patent.abstract) {
                        html += '<p style="font-size: 14px; color: #666; margin-top: 10px;">';
                        html += patent.abstract + '...';
                        html += '</p>';
                    }
                    
                    html += '</div>';
                });
            } else {
                html += '<p style="text-align: center; color: #7f8c8d; padding: 20px;">No patents found matching your search criteria.</p>';
            }
            
            html += '</div>';
            
            resultsContent.innerHTML = html;
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8092))
    app.run(host='0.0.0.0', port=port, debug=False)
