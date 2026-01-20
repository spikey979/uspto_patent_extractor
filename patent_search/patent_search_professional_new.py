#!/usr/bin/env python3
"""
Professional Patent Search System with Description-Focused Searching
Maintains original UI design with enhanced search capabilities
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

class EnhancedPatentSearch:
    def __init__(self):
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 
            'those', 'such', 'wherein', 'whereby', 'thereof', 'comprising', 'it',
            'its', 'their', 'them', 'they', 'we', 'our', 'us', 'said', 'having'
        }
    
    def extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from search text"""
        # Remove punctuation and split
        words = re.findall(r'\b[a-z]+\b', text.lower())
        
        # Filter stop words and short words
        keywords = []
        for word in words:
            if len(word) >= 3 and word not in self.stop_words:
                keywords.append(word)
        
        # Also extract phrases (2-3 word combinations)
        text_clean = re.sub(r'[^\w\s]', ' ', text.lower())
        phrases = re.findall(r'\b\w+\s+\w+\b', text_clean)
        for phrase in phrases[:5]:  # Limit phrases
            if all(w not in self.stop_words for w in phrase.split()):
                keywords.append(phrase)
        
        return list(set(keywords))[:20]  # Limit total keywords
    
    def search_patents_weighted(self, keywords: List[str], search_id: str, limit: int = 100) -> List[Dict]:
        """Search patents with weighted scoring prioritizing descriptions"""
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Update progress
        search_progress[search_id] = {
            'status': 'searching',
            'progress': 20,
            'message': 'Searching patent database...'
        }
        
        try:
            if not keywords:
                return []
            
            # Build weighted search query
            # Description matches get 3x weight, abstract 2x, title 1x
            select_parts = []
            where_parts = []
            params = []
            
            for i, keyword in enumerate(keywords):
                kw_pattern = f'%{keyword}%'
                
                # Add weighted scoring for each field
                select_parts.append(f"""
                    (CASE WHEN LOWER(u.description_text) LIKE %s THEN 3 ELSE 0 END +
                     CASE WHEN LOWER(u.abstract_text) LIKE %s THEN 2 ELSE 0 END +
                     CASE WHEN LOWER(u.title) LIKE %s THEN 1 ELSE 0 END)
                """)
                params.extend([kw_pattern, kw_pattern, kw_pattern])
                
                # Where clause - must match in at least one field
                where_parts.append(f"""
                    (LOWER(u.description_text) LIKE %s OR 
                     LOWER(u.abstract_text) LIKE %s OR 
                     LOWER(u.title) LIKE %s)
                """)
                params.extend([kw_pattern, kw_pattern, kw_pattern])
            
            # Combine scores
            score_calculation = ' + '.join(select_parts)
            where_clause = ' OR '.join(where_parts)
            
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
                u.applicants,
                ({score_calculation}) as relevance_score,
                COUNT(*) OVER() as total_matches
            FROM patent_data_unified u
            WHERE {where_clause}
            ORDER BY relevance_score DESC, u.pub_date DESC
            LIMIT %s
            """
            
            params.append(limit)
            
            # Update progress
            search_progress[search_id] = {
                'status': 'searching',
                'progress': 40,
                'message': 'Analyzing patent descriptions...'
            }
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            # Process results
            processed_results = []
            for patent in results:
                # Calculate match locations
                patent['match_locations'] = self.identify_match_locations(patent, keywords)
                
                # Convert score to percentage
                max_possible_score = len(keywords) * 6  # Each keyword can contribute max 6 points
                patent['relevance_percentage'] = (patent['relevance_score'] / max_possible_score * 100) if max_possible_score > 0 else 0
                
                # Parse JSON fields
                for field in ['inventors', 'assignees', 'applicants']:
                    if patent.get(field):
                        if isinstance(patent[field], str):
                            try:
                                patent[field] = json.loads(patent[field])
                            except:
                                patent[field] = []
                        
                        # Extract names for display
                        if field == 'assignees' and isinstance(patent[field], list):
                            assignee_names = []
                            for ass in patent[field]:
                                if isinstance(ass, dict) and ass.get('name'):
                                    assignee_names.append(ass['name'])
                                elif isinstance(ass, str):
                                    assignee_names.append(ass)
                            patent['assignee_names'] = assignee_names
                
                processed_results.append(patent)
            
            return processed_results
            
        except Exception as e:
            logging.error(f"Search error: {e}")
            return []
        finally:
            cur.close()
            conn.close()
    
    def identify_match_locations(self, patent: Dict, keywords: List[str]) -> Dict:
        """Identify where keywords were found in the patent"""
        locations = {
            'title': 0,
            'abstract': 0,
            'description': 0
        }
        
        title = (patent.get('title') or '').lower()
        abstract = (patent.get('abstract_text') or '').lower()
        description = (patent.get('description_text') or '').lower()
        
        for keyword in keywords:
            kw_lower = keyword.lower()
            if kw_lower in title:
                locations['title'] += 1
            if kw_lower in abstract:
                locations['abstract'] += 1
            if kw_lower in description:
                locations['description'] += 1
        
        return locations
    
    def calculate_detailed_relevance(self, patent: Dict, keywords: List[str]) -> Dict:
        """Calculate detailed relevance with focus on descriptions"""
        title = (patent.get('title') or '').lower()
        abstract = (patent.get('abstract_text') or '').lower()[:1000]
        description = (patent.get('description_text') or '').lower()[:5000]
        
        # Count matches with weighted scoring
        title_matches = 0
        abstract_matches = 0
        description_matches = 0
        
        for keyword in keywords:
            kw_lower = keyword.lower()
            if kw_lower in title:
                title_matches += 1
            if kw_lower in abstract:
                abstract_matches += 2  # 2x weight
            if kw_lower in description:
                description_matches += 3  # 3x weight
        
        # Calculate weighted score
        weighted_score = title_matches + abstract_matches + description_matches
        max_possible = len(keywords) * 6  # Max if all keywords found in all sections
        
        # Determine relevance level based on weighted score
        if weighted_score > len(keywords) * 4:
            relevance_level = 'H'  # High
        elif weighted_score > len(keywords) * 2.5:
            relevance_level = 'M+'  # Medium-High
        elif weighted_score > len(keywords) * 1.5:
            relevance_level = 'M'  # Medium
        else:
            relevance_level = 'L'  # Low
        
        return {
            'level': relevance_level,
            'score': weighted_score / max_possible if max_possible > 0 else 0,
            'description_matches': description_matches > 0
        }
    
    def generate_report(self, description: str, keywords: List[str], results: List[Dict], search_id: str) -> Dict:
        """Generate simplified report with progress updates"""
        # Update progress
        search_progress[search_id] = {
            'status': 'analyzing',
            'progress': 60,
            'message': 'Analyzing search results...'
        }
        
        report = {
            'report_id': hashlib.md5(description.encode()).hexdigest()[:8],
            'generated_date': datetime.now().isoformat(),
            'summary': {
                'total_results': len(results),
                'keywords_found': keywords,
                'high_relevance_count': 0,
                'description_matches_count': 0
            },
            'results': []
        }
        
        # Process top results
        for i, patent in enumerate(results[:20]):
            # Update progress
            if i % 5 == 0:
                search_progress[search_id] = {
                    'status': 'analyzing',
                    'progress': 60 + (i * 2),
                    'message': f'Analyzing patent {i+1} of {min(20, len(results))}...'
                }
            
            relevance = self.calculate_detailed_relevance(patent, keywords)
            
            if relevance['level'] in ['H', 'M+']:
                report['summary']['high_relevance_count'] += 1
            
            if relevance['description_matches']:
                report['summary']['description_matches_count'] += 1
            
            # Extract relevant snippet from description
            description_snippet = self.extract_relevant_snippet(
                patent.get('description_text', ''), 
                keywords
            )
            
            report['results'].append({
                'patent_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'pub_date': str(patent.get('pub_date')),
                'relevance_level': relevance['level'],
                'relevance_score': relevance['score'],
                'match_locations': patent.get('match_locations', {}),
                'assignees': patent.get('assignee_names', []),
                'abstract': (patent.get('abstract_text') or '')[:300],
                'description_snippet': description_snippet,
                'has_description_matches': relevance['description_matches']
            })
        
        # Final progress update
        search_progress[search_id] = {
            'status': 'complete',
            'progress': 100,
            'message': 'Search complete!'
        }
        
        return report
    
    def extract_relevant_snippet(self, text: str, keywords: List[str], snippet_length: int = 300) -> str:
        """Extract most relevant snippet from description"""
        if not text:
            return ""
        
        text_lower = text.lower()
        best_position = 0
        best_score = 0
        
        # Find position with most keyword matches
        for i in range(0, min(len(text) - snippet_length, 5000), 100):
            snippet = text_lower[i:i+snippet_length]
            score = sum(1 for kw in keywords if kw.lower() in snippet)
            if score > best_score:
                best_score = score
                best_position = i
        
        if best_score > 0:
            snippet = text[best_position:best_position+snippet_length]
            # Clean up snippet
            if best_position > 0:
                snippet = "..." + snippet
            if best_position + snippet_length < len(text):
                snippet = snippet + "..."
            return snippet
        
        # Fallback to beginning of description
        return text[:snippet_length] + "..." if len(text) > snippet_length else text

# Initialize search engine
search_engine = EnhancedPatentSearch()

@app.route('/')
def home():
    """Serve the professional search interface"""
    return render_template_string(PROFESSIONAL_SEARCH_HTML)

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    """Conduct professional patent search with description focus"""
    try:
        data = request.get_json()
        invention_description = data.get('invention_description', '')
        
        if not invention_description:
            return jsonify({'error': 'Invention description is required'}), 400
        
        # Generate search ID for progress tracking
        search_id = str(uuid.uuid4())
        
        # Initialize progress
        search_progress[search_id] = {
            'status': 'starting',
            'progress': 10,
            'message': 'Extracting keywords from invention description...'
        }
        
        # Extract keywords
        keywords = search_engine.extract_keywords(invention_description)
        
        if not keywords:
            return jsonify({'error': 'No meaningful keywords found'}), 400
        
        # Conduct weighted search
        search_results = search_engine.search_patents_weighted(
            keywords, 
            search_id,
            limit=100
        )
        
        # Generate report
        report = search_engine.generate_report(
            invention_description,
            keywords,
            search_results,
            search_id
        )
        
        return jsonify({
            'success': True,
            'search_id': search_id,
            'report': report,
            'raw_results': search_results[:50]
        })
        
    except Exception as e:
        logging.error(f"Professional search error: {e}")
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

@app.route('/api/export-report/<report_id>', methods=['GET'])
def export_report(report_id):
    """Export report as PDF or Word document"""
    return jsonify({
        'message': 'Report export endpoint',
        'format_options': ['pdf', 'docx', 'html'],
        'report_id': report_id
    })

# Professional search interface HTML (keeping original design)
PROFESSIONAL_SEARCH_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Professional Patent Search & Analysis</title>
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
        .summary-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 20px;
        }
        .summary-item {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
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
        .relevance-M\+ { background: #2ecc71; }
        .relevance-M { background: #f39c12; }
        .relevance-L { background: #95a5a6; }
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
        .match-indicators {
            display: flex;
            gap: 10px;
            margin: 10px 0;
            font-size: 12px;
        }
        .match-indicator {
            padding: 3px 8px;
            border-radius: 12px;
            background: #f8f9fa;
        }
        .match-indicator.description {
            background: #d4edda;
            color: #155724;
        }
        .match-indicator.abstract {
            background: #fff3cd;
            color: #856404;
        }
        .match-indicator.title {
            background: #cce5ff;
            color: #004085;
        }
        .description-snippet {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin-top: 10px;
            font-size: 13px;
            line-height: 1.5;
            border-left: 3px solid #4a90e2;
        }
        .keywords-display {
            margin-top: 15px;
            padding: 10px;
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
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>Professional Patent Search & Analysis System</h1>
            <p>Advanced Patent Analysis System</p>
        </div>
    </div>

    <div class="container">
        <div class="search-panel">
            <h2 class="section-title">Patent Search Configuration</h2>
            
            
            <div class="form-group">
                <label>Invention Disclosure</label>
                <textarea id="inventionDescription" placeholder="Provide a detailed description of the invention including:
- Technical field
- Key components or elements  
- Methods or processes
- Materials used
- Applications and advantages
- Any specific features that distinguish from prior art"></textarea>
            </div>
            
            <button id="searchBtn" class="btn" onclick="conductProfessionalSearch()">
                Conduct Professional Search
            </button>
            
            <div class="progress-bar" id="progressBar">
                <div class="progress-fill" id="progressFill" style="width: 0%">0%</div>
            </div>
            <div class="progress-message" id="progressMessage"></div>
            
            <div class="keywords-display" id="keywordsDisplay" style="display: none;">
                <strong>Extracted Keywords:</strong>
                <div id="keywordsList"></div>
            </div>
        </div>
        
        <div class="results-panel" id="resultsPanel">
            <h2 class="section-title">Search Results & Analysis</h2>
            <div id="resultsContent">
                <p style="color: #7f8c8d; text-align: center; padding: 40px;">
                    Enter invention details and click "Conduct Professional Search" to begin analysis.
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
                alert("Please provide a detailed invention description");
                return;
            }
            
            const searchBtn = document.getElementById("searchBtn");
            const resultsContent = document.getElementById("resultsContent");
            const progressBar = document.getElementById("progressBar");
            const progressFill = document.getElementById("progressFill");
            const progressMessage = document.getElementById("progressMessage");
            
            searchBtn.disabled = true;
            searchBtn.textContent = "Searching...";
            progressBar.classList.add("active");
            resultsContent.innerHTML = '<p style="color: #7f8c8d; text-align: center; padding: 40px;">Searching patent database...</p>';
            
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
                    
                    // Wait a bit for progress to complete
                    setTimeout(() => {
                        clearInterval(progressInterval);
                        progressBar.classList.remove("active");
                        displayProfessionalReport(data.report);
                    }, 3000);
                    
                } else {
                    resultsContent.innerHTML = '<div style="padding: 20px; color: #e74c3c;">Error: ' + (data.error || "Search failed") + '</div>';
                    progressBar.classList.remove("active");
                }
                
            } catch (error) {
                resultsContent.innerHTML = '<div style="padding: 20px; color: #e74c3c;">Error: ' + error.message + '</div>';
                progressBar.classList.remove("active");
            } finally {
                searchBtn.disabled = false;
                searchBtn.textContent = "Conduct Professional Search";
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
        
        function displayProfessionalReport(report) {
            const resultsContent = document.getElementById("resultsContent");
            
            // Display keywords
            if (report.summary.keywords_found && report.summary.keywords_found.length > 0) {
                const keywordsDisplay = document.getElementById("keywordsDisplay");
                const keywordsList = document.getElementById("keywordsList");
                keywordsDisplay.style.display = "block";
                keywordsList.innerHTML = report.summary.keywords_found.map(kw => 
                    '<span class="keyword-tag">' + kw + '</span>'
                ).join("");
            }
            
            let html = '';
            
            // Summary section
            html += '<div class="report-section">';
            html += '<h3 style="margin-bottom: 15px;">Search Summary</h3>';
            html += '<div class="summary-grid">';
            html += '<div class="summary-item">';
            html += '<h4>Total Patents Found</h4>';
            html += '<p>' + report.summary.total_results + '</p>';
            html += '</div>';
            html += '<div class="summary-item">';
            html += '<h4>High Relevance</h4>';
            html += '<p>' + report.summary.high_relevance_count + '</p>';
            html += '</div>';
            html += '<div class="summary-item">';
            html += '<h4>Description Matches</h4>';
            html += '<p>' + report.summary.description_matches_count + '</p>';
            html += '</div>';
            html += '<div class="summary-item">';
            html += '<h4>Keywords Extracted</h4>';
            html += '<p>' + report.summary.keywords_found.length + '</p>';
            html += '</div>';
            html += '</div>';
            html += '</div>';
            
            // Results section
            html += '<div class="report-section">';
            html += '<h3 style="margin-bottom: 15px;">Key Prior Art References</h3>';
            
            report.results.forEach((patent, index) => {
                html += '<div class="patent-item" style="cursor: pointer;" onclick="showPatentDetails(window.searchId, patent.patent_number)">';
                html += '<div class="patent-header">';
                html += '<span class="patent-number">#' + (index + 1) + ' - ' + patent.patent_number + '</span>';
                html += '<span class="relevance-badge relevance-' + patent.relevance_level + '">';
                html += 'Relevance: ' + patent.relevance_level;
                html += '</span>';
                html += '</div>';
                html += '<div class="patent-title">' + patent.title + '</div>';
                html += '<div class="patent-meta">';
                html += 'Published: ' + patent.pub_date;
                if (patent.assignees && patent.assignees.length > 0) {
                    html += ' | Assignee: ' + patent.assignees[0];
                }
                html += '</div>';
                
                // Match indicators
                html += '<div class="match-indicators">';
                if (patent.match_locations.description > 0) {
                    html += '<span class="match-indicator description">📄 ' + patent.match_locations.description + ' description matches</span>';
                }
                if (patent.match_locations.abstract > 0) {
                    html += '<span class="match-indicator abstract">📋 ' + patent.match_locations.abstract + ' abstract matches</span>';
                }
                if (patent.match_locations.title > 0) {
                    html += '<span class="match-indicator title">📌 ' + patent.match_locations.title + ' title matches</span>';
                }
                html += '</div>';
                
                // Show description snippet if available and has matches
                if (patent.has_description_matches && patent.description_snippet) {
                    html += '<div class="description-snippet">';
                    html += '<strong>Relevant Description Excerpt:</strong><br>';
                    html += patent.description_snippet;
                    html += '</div>';
                }
                
                // Show abstract if no description matches
                if (!patent.has_description_matches && patent.abstract) {
                    html += '<div class="description-snippet" style="border-left-color: #f39c12;">';
                    html += '<strong>Abstract:</strong><br>';
                    html += patent.abstract + '...';
                    html += '</div>';
                }
                
                html += '</div>';
            });
            
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

@app.route('/api/patent/<search_id>/<patent_number>', methods=['GET'])
def get_patent_details(search_id, patent_number):
    """Get detailed patent information"""
    if search_id in search_results_cache:
        for patent in search_results_cache[search_id]:
            if patent.get('pub_number') == patent_number:
                return jsonify({'success': True, 'patent': patent})
    return jsonify({'success': False, 'error': 'Patent not found'}), 404
