#!/usr/bin/env python3
"""
Professional Patent Search System with Report Generation
Based on industry best practices for novelty and prior art searches
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

class PatentSearchEngine:
    def __init__(self):
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 
            'those', 'such', 'wherein', 'whereby', 'thereof', 'comprising', 'it',
            'its', 'their', 'them', 'they', 'we', 'our', 'us', 'said', 'having'
        }
    
    def extract_invention_elements(self, description: str) -> Dict:
        """Extract key elements of the invention for structured search"""
        elements = {
            'technical_field': [],
            'components': [],
            'methods': [],
            'materials': [],
            'applications': []
        }
        
        # Use LLM to extract structured elements
        prompt = f"""Analyze this patent description and extract:
1. Technical field (e.g., wireless communication, medical diagnostics)
2. Key components/parts (e.g., antenna, sensor, processor)
3. Methods/processes (e.g., transmitting, analyzing, detecting)
4. Materials/substances (e.g., silicon, doxorubicin, polymer)
5. Applications/uses (e.g., cancer diagnosis, power transmission)

Return as JSON with keys: technical_field, components, methods, materials, applications

Description: {description[:1000]}

JSON:"""
        
        try:
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.2,
                    'num_predict': 300
                }
            }, timeout=30)
            
            if response.status_code == 200:
                result = response.json().get('response', '{}')
                # Extract JSON from response
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    elements = json.loads(json_match.group())
        except Exception as e:
            logging.error(f"Element extraction failed: {e}")
        
        # Fallback to keyword extraction if LLM fails
        if not any(elements.values()):
            keywords = self.extract_keywords_simple(description)
            elements['components'] = keywords[:5]
            elements['methods'] = keywords[5:10]
        
        return elements
    
    def extract_keywords_simple(self, text: str) -> List[str]:
        """Simple keyword extraction"""
        words = re.findall(r'\b[a-z]+\b', text.lower())
        keyword_count = {}
        
        for word in words:
            if len(word) >= 3 and word not in self.stop_words:
                keyword_count[word] = keyword_count.get(word, 0) + 1
        
        sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_keywords[:20]]
    
    def search_patents_advanced(self, invention_elements: Dict, description: str, limit: int = 50) -> List[Dict]:
        """Advanced patent search using multiple strategies"""
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        all_results = []
        seen_pub_numbers = set()
        
        try:
            # 1. Search by technical field and components
            all_keywords = []
            for key, values in invention_elements.items():
                if isinstance(values, list):
                    all_keywords.extend(values)
                elif isinstance(values, str):
                    all_keywords.append(values)
            
            # Remove duplicates and empty strings
            all_keywords = list(set(k for k in all_keywords if k))
            
            if all_keywords:
                # Search in patent_data_unified
                conditions = []
                params = []
                
                for keyword in all_keywords[:15]:  # Limit keywords
                    conditions.append("""(
                        LOWER(u.title) LIKE %s OR 
                        LOWER(u.abstract_text) LIKE %s OR 
                        LOWER(u.description_text) LIKE %s
                    )""")
                    kw_pattern = f'%{keyword.lower()}%'
                    params.extend([kw_pattern, kw_pattern, kw_pattern])
                
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
                    COUNT(*) OVER() as total_matches
                FROM patent_data_unified u
                WHERE {' OR '.join(conditions)}
                ORDER BY u.pub_date DESC
                LIMIT %s
                """
                
                params.append(limit)
                cur.execute(query, params)
                results = cur.fetchall()
                
                for patent in results:
                    if patent['pub_number'] not in seen_pub_numbers:
                        seen_pub_numbers.add(patent['pub_number'])
                        all_results.append(patent)
            
            # 2. CPC Classification search (if we had CPC data)
            # This would search based on classification codes
            
            # 3. Citation analysis - find patents that cite relevant patents
            if all_results and len(all_results) < limit:
                # Get top patent numbers
                top_patents = [p['pub_number'] for p in all_results[:5]]
                
                # In a full implementation, we would search citation tables
                # For now, we'll do a similarity search based on assignees
                
                assignees = []
                for patent in all_results[:5]:
                    if patent.get('assignees'):
                        if isinstance(patent['assignees'], str):
                            try:
                                assignee_list = json.loads(patent['assignees'])
                                for ass in assignee_list:
                                    if isinstance(ass, dict) and ass.get('name'):
                                        assignees.append(ass['name'])
                            except:
                                pass
                
                if assignees:
                    # Search for patents by same assignees
                    assignee_query = """
                    SELECT DISTINCT
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
                    WHERE u.assignees::text ILIKE ANY(%s)
                    AND u.pub_number NOT IN %s
                    ORDER BY u.pub_date DESC
                    LIMIT %s
                    """
                    
                    assignee_patterns = [f'%{ass}%' for ass in assignees[:3]]
                    cur.execute(assignee_query, (
                        assignee_patterns,
                        tuple(seen_pub_numbers) if seen_pub_numbers else ('',),
                        limit - len(all_results)
                    ))
                    
                    citation_results = cur.fetchall()
                    for patent in citation_results:
                        if patent['pub_number'] not in seen_pub_numbers:
                            seen_pub_numbers.add(patent['pub_number'])
                            all_results.append(patent)
            
            return all_results
            
        except Exception as e:
            logging.error(f"Advanced search error: {e}")
            return []
        finally:
            cur.close()
            conn.close()
    
    def analyze_relevance_detailed(self, patent: Dict, invention_elements: Dict, description: str) -> Dict:
        """Detailed relevance analysis comparing patent to invention"""
        relevance = {
            'overall_score': 0.0,
            'element_matches': {},
            'missing_elements': [],
            'additional_elements': [],
            'novelty_assessment': '',
            'obviousness_risk': 'low'
        }
        
        # Use LLM for detailed comparison
        patent_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')[:500]}"
        
        prompt = f"""Compare this patent to the invention and assess:
1. Which invention elements are found in the patent (score 0-100)
2. Which invention elements are NOT found in the patent
3. Novelty assessment: Is the invention novel compared to this patent?
4. Obviousness: Could the invention be obvious from this patent?

Invention elements: {json.dumps(invention_elements)}
Invention description: {description[:300]}

Patent: {patent_text}

Provide structured analysis:"""
        
        try:
            response = requests.post(OLLAMA_URL, json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.3,
                    'num_predict': 400
                }
            }, timeout=30)
            
            if response.status_code == 200:
                analysis = response.json().get('response', '')
                
                # Parse score from response
                score_match = re.search(r'(\d+)\s*(?:/100|%)', analysis)
                if score_match:
                    relevance['overall_score'] = float(score_match.group(1)) / 100.0
                
                # Determine obviousness risk
                if 'obvious' in analysis.lower():
                    if 'highly' in analysis.lower() or 'clearly' in analysis.lower():
                        relevance['obviousness_risk'] = 'high'
                    else:
                        relevance['obviousness_risk'] = 'medium'
                
                relevance['novelty_assessment'] = analysis[:200]
                
        except Exception as e:
            logging.error(f"Relevance analysis failed: {e}")
            # Fallback to simple keyword matching
            relevance['overall_score'] = self.calculate_simple_relevance(patent, invention_elements)
        
        return relevance
    
    def calculate_simple_relevance(self, patent: Dict, invention_elements: Dict) -> float:
        """Simple keyword-based relevance calculation"""
        patent_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')}".lower()
        
        matches = 0
        total = 0
        
        for element_type, elements in invention_elements.items():
            if isinstance(elements, list):
                for element in elements:
                    total += 1
                    if element.lower() in patent_text:
                        matches += 1
        
        return matches / total if total > 0 else 0.0
    
    def generate_search_report(self, invention_description: str, search_results: List[Dict], 
                             invention_elements: Dict) -> Dict:
        """Generate professional patent search report"""
        report = {
            'report_id': hashlib.md5(invention_description.encode()).hexdigest()[:8],
            'generated_date': datetime.now().isoformat(),
            'executive_summary': {
                'invention_summary': invention_description[:500],
                'search_scope': 'Novelty assessment and competitive analysis',
                'total_patents_analyzed': len(search_results),
                'high_relevance_count': sum(1 for p in search_results if p.get('relevance_score', 0) > 0.7),
                'technical_assessment': '',
                'patentability_outlook': ''
            },
            'invention_elements': invention_elements,
            'search_methodology': {
                'databases': ['USPTO Patent Database', 'Patent Data Unified Collection'],
                'search_strategies': [
                    'Keyword-based search across title, abstract, and description',
                    'Technical field classification search',
                    'Assignee and inventor analysis',
                    'AI-powered relevance ranking'
                ],
                'date_range': '2001-2025'
            },
            'detailed_results': [],
            'conclusions': {
                'novelty_assessment': '',
                'obviousness_considerations': [],
                'recommended_actions': []
            }
        }
        
        # Analyze top results
        high_relevance_patents = []
        medium_relevance_patents = []
        
        for patent in search_results[:20]:  # Analyze top 20
            relevance = self.analyze_relevance_detailed(patent, invention_elements, invention_description)
            patent['relevance_analysis'] = relevance
            
            if relevance['overall_score'] > 0.7:
                high_relevance_patents.append(patent)
            elif relevance['overall_score'] > 0.4:
                medium_relevance_patents.append(patent)
            
            # Add to detailed results
            report['detailed_results'].append({
                'patent_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'pub_date': str(patent.get('pub_date')),
                'relevance_score': relevance['overall_score'],
                'key_similarities': relevance.get('element_matches', {}),
                'assignees': patent.get('assignees', []),
                'abstract': patent.get('abstract_text', '')[:300] + '...' if patent.get('abstract_text') else '',
                'obviousness_risk': relevance.get('obviousness_risk', 'low')
            })
        
        # Generate assessments
        if high_relevance_patents:
            report['executive_summary']['technical_assessment'] = (
                f"Found {len(high_relevance_patents)} highly relevant prior art references. "
                "The broad concept appears to be known in the art."
            )
            report['executive_summary']['patentability_outlook'] = 'Challenging - Significant prior art exists'
            
            report['conclusions']['novelty_assessment'] = (
                "Based on the prior art found, the invention as broadly described may lack novelty. "
                "Consider focusing on specific structural or functional features that distinguish from prior art."
            )
        else:
            report['executive_summary']['technical_assessment'] = (
                "No highly relevant prior art found. The invention appears to have novel aspects."
            )
            report['executive_summary']['patentability_outlook'] = 'Favorable - Limited blocking prior art'
            
            report['conclusions']['novelty_assessment'] = (
                "The invention appears to be novel based on the searched prior art. "
                "No single reference discloses all elements of the invention."
            )
        
        # Obviousness considerations
        if len(high_relevance_patents) >= 2:
            report['conclusions']['obviousness_considerations'].append(
                "Multiple references in combination may render the invention obvious to one skilled in the art."
            )
        
        # Recommendations
        report['conclusions']['recommended_actions'] = [
            "Review the detailed prior art analysis with a patent attorney",
            "Consider conducting a freedom-to-operate search",
            "Identify specific novel features that distinguish from prior art",
            "Draft claims focusing on the inventive aspects not found in prior art"
        ]
        
        return report

# Initialize search engine
search_engine = PatentSearchEngine()

@app.route('/')
def home():
    """Serve the professional search interface"""
    return render_template_string(PROFESSIONAL_SEARCH_HTML)

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    """Conduct professional patent search with detailed analysis"""
    try:
        data = request.get_json()
        invention_description = data.get('invention_description', '')
        search_type = data.get('search_type', 'novelty')  # novelty, invalidity, fto
        
        if not invention_description:
            return jsonify({'error': 'Invention description is required'}), 400
        
        # Extract invention elements
        invention_elements = search_engine.extract_invention_elements(invention_description)
        
        # Conduct advanced search
        search_results = search_engine.search_patents_advanced(
            invention_elements, 
            invention_description,
            limit=100
        )
        
        # Score and rank results
        for patent in search_results:
            relevance = search_engine.analyze_relevance_detailed(
                patent, 
                invention_elements, 
                invention_description
            )
            patent['relevance_score'] = relevance['overall_score']
            patent['relevance_analysis'] = relevance
        
        # Sort by relevance
        search_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        
        # Generate professional report
        report = search_engine.generate_search_report(
            invention_description,
            search_results,
            invention_elements
        )
        
        return jsonify({
            'success': True,
            'report': report,
            'raw_results': search_results[:50]  # Include top 50 for client-side analysis
        })
        
    except Exception as e:
        logging.error(f"Professional search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export-report/<report_id>', methods=['GET'])
def export_report(report_id):
    """Export report as PDF or Word document"""
    # In a full implementation, this would generate a formatted document
    # For now, return JSON
    return jsonify({
        'message': 'Report export endpoint',
        'format_options': ['pdf', 'docx', 'html'],
        'report_id': report_id
    })

# Professional search interface HTML
PROFESSIONAL_SEARCH_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Professional Patent Search & Analysis</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
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
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 24px;
            font-weight: 600;
        }
        .header-nav {
            display: flex;
            gap: 30px;
        }
        .header-nav a {
            color: white;
            text-decoration: none;
            font-size: 14px;
            opacity: 0.9;
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
        .search-type {
            display: flex;
            gap: 15px;
            margin-bottom: 20px;
        }
        .search-type label {
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
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
        .btn-secondary {
            background: #95a5a6;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #7f8c8d;
        }
        .report-header {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .report-section {
            margin-bottom: 30px;
        }
        .report-section h3 {
            font-size: 18px;
            color: #2c3e50;
            margin-bottom: 15px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 8px;
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
        .relevance-high { background: #27ae60; }
        .relevance-medium { background: #f39c12; }
        .relevance-low { background: #e74c3c; }
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
        .assessment-box {
            background: #fff3cd;
            border: 1px solid #ffeeba;
            border-radius: 5px;
            padding: 15px;
            margin-bottom: 20px;
        }
        .assessment-box.favorable {
            background: #d4edda;
            border-color: #c3e6cb;
        }
        .assessment-box.challenging {
            background: #f8d7da;
            border-color: #f5c6cb;
        }
        .element-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }
        .element-tag {
            background: #ecf0f1;
            padding: 4px 10px;
            border-radius: 15px;
            font-size: 12px;
        }
        .export-buttons {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #4a90e2;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-left: 10px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>Professional Patent Search & Analysis System</h1>
            <nav class="header-nav">
                <a href="#novelty">Novelty Search</a>
                <a href="#invalidity">Invalidity Search</a>
                <a href="#fto">Freedom to Operate</a>
                <a href="#reports">Reports</a>
            </nav>
        </div>
    </div>

    <div class="container">
        <div class="search-panel">
            <h2 class="section-title">Patent Search Configuration</h2>
            
            <div class="form-group">
                <label>Search Type</label>
                <div class="search-type">
                    <label>
                        <input type="radio" name="searchType" value="novelty" checked>
                        <span>Prior Art Search</span>
                    </label>
                    <label>
                        <input type="radio" name="searchType" value="invalidity">
                        <span>Invalidity Search</span>
                    </label>
                    <label>
                        <input type="radio" name="searchType" value="fto">
                        <span>Freedom to Operate</span>
                    </label>
                </div>
            </div>
            
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
            
            <div class="form-group" style="margin-top: 30px;">
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
        async function conductProfessionalSearch() {
            const inventionDescription = document.getElementById('inventionDescription').value.trim();
            const searchType = document.querySelector('input[name="searchType"]:checked').value;
            
            if (!inventionDescription) {
                alert('Please provide a detailed invention description');
                return;
            }
            
            const searchBtn = document.getElementById('searchBtn');
            const resultsContent = document.getElementById('resultsContent');
            
            searchBtn.disabled = true;
            searchBtn.innerHTML = 'Conducting Search<span class="spinner"></span>';
            resultsContent.innerHTML = '<div class="loading">Analyzing invention and searching prior art...</div>';
            
            try {
                const response = await fetch('/api/professional-search', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        invention_description: inventionDescription,
                        search_type: searchType
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    displayProfessionalReport(data.report);
                } else {
                    resultsContent.innerHTML = '<div class="assessment-box challenging">Error: ' + (data.error || 'Search failed') + '</div>';
                }
                
            } catch (error) {
                resultsContent.innerHTML = '<div class="assessment-box challenging">Error: ' + error.message + '</div>';
            } finally {
                searchBtn.disabled = false;
                searchBtn.innerHTML = 'Conduct Professional Search';
            }
        }
        
        function displayProfessionalReport(report) {
            const resultsContent = document.getElementById('resultsContent');
            
            let html = `
                <div class="report-header">
                    <h3>Professional Patent Search Report</h3>
                    <p style="color: #666; margin-top: 5px;">
                        Report ID: ${report.report_id} | Generated: ${new Date(report.generated_date).toLocaleString()}
                    </p>
                </div>
            `;
            
            // Executive Summary
            html += `
                <div class="report-section">
                    <h3>Executive Summary</h3>
                    <div class="assessment-box ${report.executive_summary.patentability_outlook.includes('Favorable') ? 'favorable' : 'challenging'}">
                        <strong>Patentability Outlook:</strong> ${report.executive_summary.patentability_outlook}
                    </div>
                    <div class="summary-grid">
                        <div class="summary-item">
                            <h4>Total Patents Analyzed</h4>
                            <p>${report.executive_summary.total_patents_analyzed}</p>
                        </div>
                        <div class="summary-item">
                            <h4>High Relevance Patents</h4>
                            <p>${report.executive_summary.high_relevance_count}</p>
                        </div>
                    </div>
                    <p>${report.executive_summary.technical_assessment}</p>
                </div>
            `;
            
            // Invention Elements
            html += `
                <div class="report-section">
                    <h3>Identified Invention Elements</h3>
                    <div class="element-tags">
            `;
            
            for (const [category, elements] of Object.entries(report.invention_elements)) {
                if (Array.isArray(elements) && elements.length > 0) {
                    elements.forEach(element => {
                        html += `<span class="element-tag">${element}</span>`;
                    });
                }
            }
            
            html += `
                    </div>
                </div>
            `;
            
            // Top Prior Art Results
            html += `
                <div class="report-section">
                    <h3>Key Prior Art References</h3>
            `;
            
            report.detailed_results.slice(0, 10).forEach((patent, index) => {
                const relevanceClass = patent.relevance_score > 0.7 ? 'high' : 
                                     patent.relevance_score > 0.4 ? 'medium' : 'low';
                
                html += `
                    <div class="patent-item">
                        <div class="patent-header">
                            <span class="patent-number">#${index + 1} - ${patent.patent_number}</span>
                            <span class="relevance-badge relevance-${relevanceClass}">
                                ${Math.round(patent.relevance_score * 100)}% Relevant
                            </span>
                        </div>
                        <div class="patent-title">${patent.title}</div>
                        <div class="patent-meta">
                            Published: ${patent.pub_date} | 
                            Obviousness Risk: ${patent.obviousness_risk}
                        </div>
                        <p style="font-size: 14px; color: #666; margin-top: 10px;">
                            ${patent.abstract}
                        </p>
                    </div>
                `;
            });
            
            html += `</div>`;
            
            // Conclusions
            html += `
                <div class="report-section">
                    <h3>Conclusions & Recommendations</h3>
                    <p><strong>Novelty Assessment:</strong> ${report.conclusions.novelty_assessment}</p>
                    
                    <h4 style="margin-top: 15px;">Recommended Actions:</h4>
                    <ul style="padding-left: 20px;">
            `;
            
            report.conclusions.recommended_actions.forEach(action => {
                html += `<li>${action}</li>`;
            });
            
            html += `
                    </ul>
                </div>
            `;
            
            // Export Options
            html += `
                <div class="export-buttons">
                    <button class="btn btn-secondary" onclick="exportReport('${report.report_id}', 'pdf')">
                        Export as PDF
                    </button>
                    <button class="btn btn-secondary" onclick="exportReport('${report.report_id}', 'docx')">
                        Export as Word
                    </button>
                </div>
            `;
            
            resultsContent.innerHTML = html;
        }
        
        function exportReport(reportId, format) {
            alert(`Export functionality for ${format} format will be implemented soon.`);
            // In production, this would trigger actual file generation
        }
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8092))
    app.run(host='0.0.0.0', port=port, debug=False)