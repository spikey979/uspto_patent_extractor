#!/usr/bin/env python3
"""
Patent Search with Claims - Enhanced AI Relevance Scoring
Extracts patent claims for better AI scoring
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
import requests
import uuid
import threading
import time
import zipfile
import tarfile
import xml.etree.ElementTree as ET
import tempfile
import shutil
from datetime import datetime
import glob

app = Flask(__name__,
            template_folder='../templates',
            static_folder='../static')
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', 5432)),
    'database': os.environ.get('DB_NAME', 'companies_db'),
    'user': os.environ.get('DB_USER', 'mark'),
    'password': os.environ.get('DB_PASSWORD', 'mark123')
}

OLLAMA_URL = 'http://localhost:11434/api/generate'
MODEL_NAME = 'gpt-oss:20b'

STORES = ['/mnt/store1/originals', '/mnt/store2/originals']
TEMP_DIR = '/tmp/patent_extraction'

search_sessions = {}

class ClaimsExtractor:
    """Extract claims from patent XML files"""
    
    def __init__(self):
        self.archive_cache = {}
        os.makedirs(TEMP_DIR, exist_ok=True)
        
    def find_and_extract_claims(self, patent_number, pub_date=None):
        """Find patent in archives and extract claims"""
        
        # Try to find from description_text first (if claims were already extracted)
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cur.execute("""
                SELECT description_text 
                FROM patent_data_unified 
                WHERE pub_number = %s
            """, (patent_number,))
            
            result = cur.fetchone()
            if result and result['description_text']:
                # Check if claims are already in description
                if result['description_text'].startswith('CLAIMS:'):
                    claims_end = result['description_text'].find('\n\nDESCRIPTION:')
                    if claims_end > 0:
                        claims_text = result['description_text'][7:claims_end].strip()
                    else:
                        claims_text = result['description_text'][7:].strip()
                    
                    if claims_text:
                        logger.info(f"Found claims in database for {patent_number}")
                        return claims_text
        finally:
            cur.close()
            conn.close()
        
        # Otherwise, extract from XML archives
        logger.info(f"Searching archives for patent {patent_number} claims")
        
        # Determine likely archive based on date or patent number
        archives_to_check = self.get_likely_archives(patent_number, pub_date)
        
        for archive_path in archives_to_check:
            claims = self.extract_claims_from_archive(archive_path, patent_number)
            if claims:
                return claims
                
        logger.warning(f"No claims found for patent {patent_number}")
        return None
        
    def get_likely_archives(self, patent_number, pub_date):
        """Get list of archives likely to contain this patent"""
        archives = []
        
        # Extract year from patent number if possible
        year_match = re.search(r'(20\d{2})', patent_number)
        target_year = None
        if year_match:
            target_year = year_match.group(1)
        elif pub_date:
            target_year = str(pub_date)[:4]
            
        # Find relevant archives
        for store in STORES:
            for ext in ['*.ZIP', '*.zip', '*.tar']:
                pattern_files = glob.glob(os.path.join(store, ext))
                
                for archive in pattern_files:
                    basename = os.path.basename(archive)
                    # Check if archive name contains the target year
                    if target_year and target_year in basename:
                        archives.append(archive)
                    # Or check date pattern YYYYMMDD
                    elif target_year:
                        date_match = re.search(r'(\d{8})', basename)
                        if date_match and date_match.group(1).startswith(target_year):
                            archives.append(archive)
                            
        # Sort by filename (usually date)
        archives.sort()
        
        # Limit to most likely archives
        return archives[:10] if archives else []
        
    def extract_claims_from_archive(self, archive_path, patent_number):
        """Extract claims from a specific archive"""
        temp_dir = tempfile.mkdtemp(dir=TEMP_DIR)
        
        try:
            if archive_path.endswith(('.ZIP', '.zip')):
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for file_info in zf.namelist():
                        if patent_number in file_info and file_info.endswith('.XML'):
                            zf.extract(file_info, temp_dir)
                            xml_path = os.path.join(temp_dir, file_info)
                            return self.parse_claims_from_xml(xml_path)
                            
            elif archive_path.endswith('.tar'):
                with tarfile.open(archive_path, 'r') as tf:
                    for member in tf.getmembers():
                        if patent_number in member.name and member.name.endswith('.XML'):
                            tf.extract(member, temp_dir)
                            xml_path = os.path.join(temp_dir, member.name)
                            return self.parse_claims_from_xml(xml_path)
                            
        except Exception as e:
            logger.error(f"Error extracting from {archive_path}: {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        return None
        
    def parse_claims_from_xml(self, xml_path):
        """Parse claims from patent XML"""
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            claims = []
            claims_elem = root.find('.//claims')
            if claims_elem is not None:
                for claim in claims_elem.findall('.//claim'):
                    claim_text = ' '.join(claim.itertext()).strip()
                    if claim_text:
                        # Clean up claim text
                        claim_text = re.sub(r'\s+', ' ', claim_text)
                        claims.append(claim_text)
            
            if claims:
                logger.info(f"Extracted {len(claims)} claims from {xml_path}")
                return '\n\n'.join(claims)
                
        except Exception as e:
            logger.error(f"Error parsing XML {xml_path}: {e}")
            
        return None

class SmartPatentSearchWithClaims:
    def __init__(self):
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be'
        }
        self.claims_extractor = ClaimsExtractor()
    
    def extract_concepts(self, description: str) -> Dict[str, List[str]]:
        text = re.sub(r'\([^)]*\)', '', description)
        words = re.findall(r'\b[a-z]+\b', text.lower())
        
        keywords = []
        seen = set()
        for word in words:
            if len(word) >= 3 and word not in self.stop_words and word not in seen:
                keywords.append(word)
                seen.add(word)
        
        return {'primary_terms': keywords[:30]}
    
    def search_by_concepts(self, concepts: Dict[str, List[str]]) -> List[Dict]:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            keywords = concepts.get('primary_terms', [])[:20]
            conditions = []
            params = []
            
            for keyword in keywords:
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
                u.assignees
            FROM patent_data_unified u
            WHERE {' OR '.join(conditions)}
            ORDER BY u.year DESC
            LIMIT 50
            """
            
            cur.execute(query, params)
            results = cur.fetchall()
            
            for patent in results:
                for field in ['inventors', 'assignees']:
                    if patent.get(field) and isinstance(patent[field], str):
                        try:
                            patent[field] = json.loads(patent[field])
                        except:
                            patent[field] = []
            
            return results
            
        except Exception as e:
            logger.error(f"Database search error: {e}")
            return []
        finally:
            cur.close()
            conn.close()
    
    def score_with_ai_async(self, results: List[Dict], description: str, search_id: str):
        if not results:
            search_sessions[search_id]['stage'] = 'complete'
            search_sessions[search_id]['results'] = []
            return
        
        search_sessions[search_id]['stage'] = 'extracting_claims'
        search_sessions[search_id]['total'] = len(results)
        search_sessions[search_id]['current'] = 0
        
        # Extract claims for each patent
        logger.info(f"Extracting claims for {len(results)} patents")
        for i, patent in enumerate(results):
            search_sessions[search_id]['current'] = i + 1
            
            # Try to extract claims
            claims = self.claims_extractor.find_and_extract_claims(
                patent['pub_number'],
                patent.get('pub_date')
            )
            
            if claims:
                patent['claims_text'] = claims[:5000]  # Limit claims length
                logger.info(f"Patent {i+1}: Found claims ({len(claims)} chars)")
            else:
                patent['claims_text'] = None
                logger.info(f"Patent {i+1}: No claims found")
        
        # Now score with AI including claims
        search_sessions[search_id]['stage'] = 'scoring'
        search_sessions[search_id]['current'] = 0
        
        scored_results = []
        
        for i, patent in enumerate(results):
            try:
                search_sessions[search_id]['current'] = i + 1
                
                # Prepare patent content for AI
                patent_content = f"Title: {patent.get('title', 'N/A')}\n\n"
                
                # Add abstract
                patent_abstract = patent.get('abstract_text', '')
                if patent_abstract:
                    patent_content += f"Abstract: {patent_abstract[:2000]}\n\n"
                
                # Add claims if available - MOST IMPORTANT FOR RELEVANCE
                if patent.get('claims_text'):
                    patent_content += f"Claims: {patent['claims_text'][:3000]}\n\n"
                elif patent.get('description_text') and patent['description_text'].startswith('CLAIMS:'):
                    # Extract claims from description if stored there
                    claims_end = patent['description_text'].find('\n\nDESCRIPTION:')
                    if claims_end > 0:
                        claims = patent['description_text'][7:claims_end]
                    else:
                        claims = patent['description_text'][7:3000]
                    patent_content += f"Claims: {claims[:3000]}\n\n"
                
                # Create enhanced prompt with claims emphasis
                prompt = f"""You are an expert in patents and intellectual property. Your task is to compare a user's invention description against a patent's claims, abstract, and title.

IMPORTANT: Patent claims define the legal scope of the invention. Pay special attention to claim language when scoring relevance.

Provide:
1. Relevance Score: A number from 1 to 100, where:
   - 90-100 = Claims directly overlap with user's invention
   - 70-89 = Strong overlap in claims or technical approach
   - 40-69 = Some shared technical concepts but different claims
   - 1-39 = Different technical field or no claim overlap

2. Reasoning: A short explanation (2-5 sentences) focusing on:
   - How the patent claims relate to the user's invention
   - Key technical similarities or differences
   - Whether the patent would block or relate to the user's invention

User's invention description: {description[:2000] if len(description) > 2000 else description}

Patent information:
{patent_content}

Output format:
Score: [number]/100
Reasoning: [explanation focusing on claim overlap]"""

                response = requests.post(OLLAMA_URL, json={
                    'model': MODEL_NAME,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.3,
                        'num_predict': 250,
                        'num_ctx': 6000  # Increased context for claims
                    }
                }, timeout=60)  # 60 second timeout
                
                if response.status_code == 200:
                    result = response.json()
                    score_text = result.get('response', '').strip()
                    
                    if score_text:
                        logger.info(f"AI response: {score_text[:200]}")
                        
                        # Extract score
                        score_match = re.search(r'Score:\s*(\d+)', score_text, re.IGNORECASE)
                        if score_match:
                            score = min(100, max(1, int(score_match.group(1))))
                        else:
                            numbers = re.findall(r'\d+', score_text)
                            if numbers:
                                score = min(100, max(1, int(numbers[0])))
                            else:
                                score = 50
                                
                        # Extract reasoning
                        reasoning_match = re.search(r'Reasoning:\s*(.+)', score_text, re.IGNORECASE | re.DOTALL)
                        if reasoning_match:
                            patent['ai_reasoning'] = reasoning_match.group(1).strip()[:500]
                    else:
                        score = 50
                else:
                    logger.error(f"Ollama returned status {response.status_code}")
                    score = 50
                
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout for patent {i+1}, using default score")
                score = 50
            except Exception as e:
                logger.error(f"AI scoring error for patent {i+1}: {e}")
                score = 50
            
            patent['relevance_score'] = score / 100.0
            patent['has_claims'] = bool(patent.get('claims_text'))
            scored_results.append(patent)
            logger.info(f"Scored patent {i+1}/{len(results)}: {score}% (claims: {patent['has_claims']})")
        
        scored_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        
        search_sessions[search_id]['stage'] = 'complete'
        search_sessions[search_id]['results'] = scored_results[:50]

search_engine = SmartPatentSearchWithClaims()

# Include the same HTML template but with claims indicator
SEARCH_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Patent Search with Claims Analysis</title>
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
    .header h1 { margin-bottom: 5px; }
    .header p { color: #aaa; font-size: 14px; }
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
    
    /* Progress Bar */
    .progress-container {
        display: none;
        margin-top: 20px;
        padding: 15px;
        background: #f8f9fa;
        border-radius: 8px;
    }
    .progress-container.active {
        display: block;
    }
    .progress-stages {
        display: flex;
        justify-content: space-between;
        margin-bottom: 15px;
    }
    .stage {
        flex: 1;
        text-align: center;
        padding: 8px;
        background: #e0e0e0;
        margin: 0 2px;
        border-radius: 5px;
        font-size: 12px;
        font-weight: 500;
        color: #666;
    }
    .stage.active {
        background: #4a90e2;
        color: white;
    }
    .stage.completed {
        background: #27ae60;
        color: white;
    }
    .progress-bar {
        width: 100%;
        height: 25px;
        background: #e0e0e0;
        border-radius: 12px;
        overflow: hidden;
    }
    .progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #4a90e2, #3a7bc8);
        transition: width 0.3s;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 12px;
        font-weight: 600;
    }
    .progress-text {
        text-align: center;
        margin-top: 10px;
        color: #666;
        font-size: 13px;
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
    .claims-indicator {
        display: inline-block;
        padding: 2px 8px;
        background: #8e44ad;
        color: white;
        border-radius: 10px;
        font-size: 10px;
        margin-left: 5px;
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
    .ai-reasoning {
        font-size: 12px;
        color: #2c3e50;
        background: #ecf0f1;
        padding: 8px;
        border-radius: 5px;
        margin-top: 8px;
        font-style: italic;
    }
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
        <p>Enhanced with Claims Analysis for Superior Relevance Scoring</p>
    </div>
    
    <div class="container">
        <div class="panel">
            <h2>Search Patents</h2>
            <textarea id="description" placeholder="Paste patent description or invention details..."></textarea>
            <button class="btn" id="searchBtn" onclick="search()">Search Patents with Claims Analysis</button>
            
            <div class="progress-container" id="progressContainer">
                <div class="progress-stages">
                    <div class="stage" id="stage1">Keywords</div>
                    <div class="stage" id="stage2">Database</div>
                    <div class="stage" id="stage3">Claims</div>
                    <div class="stage" id="stage4">AI Scoring</div>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill" style="width: 0%">0%</div>
                </div>
                <div class="progress-text" id="progressText">Initializing...</div>
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
        let progressInterval = null;
        let searchResults = [];
        
        async function search() {
            const description = document.getElementById('description').value.trim();
            if (!description) {
                alert('Please enter a description');
                return;
            }
            
            const btn = document.getElementById('searchBtn');
            const results = document.getElementById('results');
            const progressContainer = document.getElementById('progressContainer');
            
            btn.disabled = true;
            btn.textContent = 'Searching...';
            progressContainer.classList.add('active');
            updateProgress(0, 'Extracting keywords...', 1);
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
                    pollProgress();
                } else {
                    results.innerHTML = '<p style="color: red;">Error: ' + (data.error || 'Search failed') + '</p>';
                    btn.disabled = false;
                    btn.textContent = 'Search Patents with Claims Analysis';
                    progressContainer.classList.remove('active');
                }
            } catch (error) {
                results.innerHTML = '<p style="color: red;">Error: ' + error.message + '</p>';
                btn.disabled = false;
                btn.textContent = 'Search Patents with Claims Analysis';
                progressContainer.classList.remove('active');
            }
        }
        
        function updateProgress(percent, text, stage) {
            document.getElementById('progressFill').style.width = percent + '%';
            document.getElementById('progressFill').textContent = Math.round(percent) + '%';
            document.getElementById('progressText').textContent = text;
            
            for (let i = 1; i <= 4; i++) {
                const stageEl = document.getElementById('stage' + i);
                if (i < stage) {
                    stageEl.classList.add('completed');
                    stageEl.classList.remove('active');
                } else if (i === stage) {
                    stageEl.classList.add('active');
                    stageEl.classList.remove('completed');
                } else {
                    stageEl.classList.remove('active', 'completed');
                }
            }
        }
        
        async function pollProgress() {
            progressInterval = setInterval(async () => {
                try {
                    const response = await fetch('/api/search-progress/' + currentSearchId);
                    const data = await response.json();
                    
                    if (data.stage === 'extracting') {
                        updateProgress(10, 'Extracting keywords...', 1);
                    } else if (data.stage === 'searching') {
                        updateProgress(25, 'Searching database...', 2);
                    } else if (data.stage === 'extracting_claims') {
                        const progress = 25 + (data.current / data.total * 25);
                        updateProgress(progress, 'Extracting claims: ' + data.current + '/' + data.total + ' patents...', 3);
                    } else if (data.stage === 'scoring') {
                        const progress = 50 + (data.current / data.total * 45);
                        updateProgress(progress, 'AI scoring: ' + data.current + '/' + data.total + ' patents...', 4);
                    } else if (data.stage === 'complete') {
                        clearInterval(progressInterval);
                        updateProgress(100, 'Search complete!', 4);
                        searchResults = data.results;
                        displayResults(searchResults);
                        document.getElementById('searchBtn').disabled = false;
                        document.getElementById('searchBtn').textContent = 'Search Patents with Claims Analysis';
                        setTimeout(() => {
                            document.getElementById('progressContainer').classList.remove('active');
                        }, 1500);
                    }
                } catch (error) {
                    console.error('Progress error:', error);
                }
            }, 500);
        }
        
        function displayResults(results) {
            const resultsDiv = document.getElementById('results');
            
            if (!results || results.length === 0) {
                resultsDiv.innerHTML = '<p style="color: #999;">No patents found</p>';
                return;
            }
            
            resultsDiv.innerHTML = results.map((patent, idx) => {
                const score = Math.round((patent.relevance_score || 0) * 100);
                let badge = 'L';
                if (score >= 65) badge = 'H';
                else if (score >= 35) badge = 'M';
                
                const assignee = patent.assignees && patent.assignees.length > 0 ? 
                    (typeof patent.assignees[0] === 'object' ? patent.assignees[0].name : patent.assignees[0]) : 'N/A';
                const inventor = patent.inventors && patent.inventors.length > 0 ? 
                    (typeof patent.inventors[0] === 'object' ? patent.inventors[0].name : patent.inventors[0]) : 'N/A';
                
                const claimsIndicator = patent.has_claims ? '<span class="claims-indicator">CLAIMS</span>' : '';
                const reasoning = patent.ai_reasoning ? 
                    '<div class="ai-reasoning">AI Analysis: ' + patent.ai_reasoning + '</div>' : '';
                
                return \`
                    <div class="patent-item" onclick="showDetails(\${idx})">
                        <div class="patent-header">
                            <div class="patent-number">\${patent.pub_number} \${claimsIndicator}</div>
                            <span class="relevance-badge relevance-\${badge}">\${badge} \${score}%</span>
                        </div>
                        <div class="patent-title">\${patent.title || 'Untitled'}</div>
                        <div class="patent-meta">
                            📅 \${patent.pub_date || 'N/A'} | 
                            🏢 \${assignee} | 
                            👤 \${inventor}
                        </div>
                        <div class="patent-abstract">
                            \${patent.abstract_text ? patent.abstract_text.substring(0, 200) + '...' : 'No abstract'}
                        </div>
                        \${reasoning}
                    </div>
                \`;
            }).join('');
        }
        
        function showDetails(index) {
            const patent = searchResults[index];
            if (!patent) return;
            
            const modal = document.getElementById('patentModal');
            const modalContent = document.getElementById('modalContent');
            
            let html = '<h2 style="color: #2c3e50; margin-bottom: 20px;">' + patent.pub_number + 
                       ' <a href="https://patents.google.com/patent/US' + patent.pub_number + 
                       '" target="_blank" style="float: right; padding: 6px 15px; background: #4a90e2; ' +
                       'color: white; text-decoration: none; border-radius: 5px; font-size: 14px; ' +
                       'font-weight: normal;">View Patent →</a></h2>';
            
            // Title
            html += '<div class="detail-section">';
            html += '<div class="detail-label">Title</div>';
            html += '<div class="detail-content">' + (patent.title || 'N/A') + '</div>';
            html += '</div>';
            
            // Basic Info
            html += '<div class="detail-section">';
            html += '<div class="detail-label">Basic Information</div>';
            html += '<div class="detail-content">';
            html += '<strong>Publication Date:</strong> ' + (patent.pub_date || 'N/A') + '<br>';
            html += '<strong>Year:</strong> ' + (patent.year || 'N/A') + '<br>';
            html += '<strong>AI Relevance Score:</strong> ' + Math.round((patent.relevance_score || 0) * 100) + '%<br>';
            html += '<strong>Claims Available:</strong> ' + (patent.has_claims ? 'Yes' : 'No') + '<br>';
            html += '</div>';
            html += '</div>';
            
            // AI Reasoning
            if (patent.ai_reasoning) {
                html += '<div class="detail-section">';
                html += '<div class="detail-label">AI Analysis</div>';
                html += '<div class="detail-content">' + patent.ai_reasoning + '</div>';
                html += '</div>';
            }
            
            // Claims (if available)
            if (patent.claims_text) {
                html += '<div class="detail-section">';
                html += '<div class="detail-label">Patent Claims</div>';
                html += '<div class="detail-content" style="white-space: pre-line;">' + patent.claims_text + '</div>';
                html += '</div>';
            }
            
            // Assignees
            if (patent.assignees && patent.assignees.length > 0) {
                html += '<div class="detail-section">';
                html += '<div class="detail-label">Assignees / Companies</div>';
                html += '<div class="detail-content">';
                patent.assignees.forEach(ass => {
                    const name = (typeof ass === 'object' ? ass.name : ass) || 'Unknown';
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
                    const name = (typeof inv === 'object' ? inv.name : inv) || 'Unknown';
                    html += '<span class="person-tag">👤 ' + name + '</span>';
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
            
            modalContent.innerHTML = html;
            modal.style.display = 'block';
        }
        
        function closeModal() {
            document.getElementById('patentModal').style.display = 'none';
        }
        
        window.onclick = function(event) {
            const modal = document.getElementById('patentModal');
            if (event.target == modal) {
                closeModal();
            }
        }
    </script>
</body>
</html>'''

@app.route('/')
def home():
    return SEARCH_HTML

@app.route('/api/professional-search', methods=['POST'])
def professional_search():
    try:
        data = request.get_json()
        description = data.get('invention_description', '').strip()
        
        if not description:
            return jsonify({'success': False, 'error': 'Description required'}), 400
        
        search_id = str(uuid.uuid4())
        
        search_sessions[search_id] = {
            'stage': 'extracting',
            'current': 0,
            'total': 0,
            'results': []
        }
        
        thread = threading.Thread(target=process_search, args=(search_id, description))
        thread.start()
        
        return jsonify({
            'success': True,
            'search_id': search_id
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def process_search(search_id, description):
    try:
        search_sessions[search_id]['stage'] = 'extracting'
        concepts = search_engine.extract_concepts(description)
        time.sleep(0.5)
        
        search_sessions[search_id]['stage'] = 'searching'
        results = search_engine.search_by_concepts(concepts)
        time.sleep(0.5)
        
        search_engine.score_with_ai_async(results, description, search_id)
        
    except Exception as e:
        logger.error(f"Background search error: {e}")
        search_sessions[search_id]['stage'] = 'error'
        search_sessions[search_id]['error'] = str(e)

@app.route('/api/search-progress/<search_id>')
def get_progress(search_id):
    if search_id not in search_sessions:
        return jsonify({'stage': 'not_found'})
    
    session = search_sessions[search_id]
    return jsonify({
        'stage': session['stage'],
        'current': session.get('current', 0),
        'total': session.get('total', 0),
        'results': session.get('results', [])
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8095))
    app.run(host='0.0.0.0', port=port, debug=True)