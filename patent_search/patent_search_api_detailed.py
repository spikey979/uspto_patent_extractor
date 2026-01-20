#!/usr/bin/env python3
"""
Patent Search API with Detailed Patent View
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor, Json
import json
import re
import os
import requests
import logging

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

def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(**DB_CONFIG)

def extract_keywords(description):
    """Extract keywords from description using simple NLP"""
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                  'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 
                  'those', 'such', 'wherein', 'whereby', 'thereof', 'comprising'}
    
    words = re.findall(r'\b[a-z]+\b', description.lower())
    keyword_count = {}
    
    for word in words:
        if len(word) >= 3 and word not in stop_words:
            keyword_count[word] = keyword_count.get(word, 0) + 1
    
    sorted_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
    return [word for word, count in sorted_keywords[:15]]

def extract_keywords_with_llm(description):
    """Use LLM to extract keywords"""
    prompt = f"""Extract the most important technical keywords from this patent description. 
Focus on unique technical terms, components, methods, and innovations.
Return only a comma-separated list of keywords (maximum 15 keywords).

Patent description:
{description}

Keywords:"""
    
    try:
        response = requests.post(OLLAMA_URL, json={
            'model': MODEL_NAME,
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': 0.3,
                'num_predict': 100
            }
        }, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            keywords_text = result.get('response', '').strip()
            keywords = [k.strip() for k in keywords_text.split(',') if k.strip()]
            return keywords[:15]
    except Exception as e:
        logging.error(f"LLM keyword extraction failed: {e}")
    
    return extract_keywords(description)

def search_patents_with_llm(keywords, description, limit=20):
    """Search patents and rank with LLM"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # First search in patent_data_unified for full data
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
            u.assignees,
            u.applicants
        FROM patent_data_unified u
        WHERE {' OR '.join(conditions)}
        LIMIT %s
        """
        
        params.append(limit * 2)  # Get more to rank with LLM
        cur.execute(query, params)
        patents = cur.fetchall()
        
        # If not enough results, search in publication table
        if len(patents) < limit:
            remaining = limit - len(patents)
            
            title_conditions = []
            title_params = []
            for keyword in keywords:
                title_conditions.append("LOWER(p.invention_title) LIKE %s")
                title_params.append(f'%{keyword.lower()}%')
            
            # Get pub_numbers already found
            found_pub_numbers = [p['pub_number'] for p in patents]
            
            title_query = f"""
            SELECT 
                p.pub_number,
                p.invention_title as title,
                p.pub_date,
                p.kind,
                pp.name as assignee_name
            FROM publication p
            LEFT JOIN publication_party pp ON p.pub_number = pp.publication_pub_number 
                AND pp.party_type = 'ASSIGNEE'
            WHERE ({' OR '.join(title_conditions)})
            AND p.pub_number NOT IN ({','.join(['%s'] * len(found_pub_numbers))}) 
            ORDER BY p.pub_date DESC
            LIMIT %s
            """
            
            title_params.extend(found_pub_numbers)
            title_params.append(remaining * 2)
            
            if found_pub_numbers:
                cur.execute(title_query, title_params)
            else:
                # No exclusion needed
                title_query = title_query.replace(
                    f"AND p.pub_number NOT IN ({','.join(['%s'] * len(found_pub_numbers))})", 
                    ""
                )
                title_params = title_params[:-len(found_pub_numbers)]
                cur.execute(title_query, title_params)
            
            title_patents = cur.fetchall()
            
            # Group assignees by patent
            patent_assignees = {}
            for row in title_patents:
                pub_num = row['pub_number']
                if pub_num not in patent_assignees:
                    patent_assignees[pub_num] = {
                        'pub_number': pub_num,
                        'title': row['title'],
                        'pub_date': row['pub_date'],
                        'kind': row['kind'],
                        'assignees': []
                    }
                if row['assignee_name']:
                    patent_assignees[pub_num]['assignees'].append(row['assignee_name'])
            
            patents.extend(list(patent_assignees.values()))
        
        # Rank with LLM
        ranked_patents = []
        for patent in patents[:limit]:
            patent_text = f"{patent.get('title', '')} {patent.get('abstract_text', '')[:200]}"
            
            prompt = f"""Compare this patent to the search description and rate relevance from 0-100:
Search: {description[:200]}
Patent: {patent_text}
Return only a number 0-100:"""
            
            try:
                response = requests.post(OLLAMA_URL, json={
                    'model': MODEL_NAME,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.1,
                        'num_predict': 10
                    }
                }, timeout=10)
                
                if response.status_code == 200:
                    score_text = response.json().get('response', '0').strip()
                    score = float(re.findall(r'\d+', score_text)[0]) / 100.0
                else:
                    score = 0.5
            except:
                score = 0.5
            
            # Convert JSON fields to lists if needed
            if patent.get('inventors') and isinstance(patent['inventors'], str):
                try:
                    patent['inventors'] = json.loads(patent['inventors'])
                except:
                    patent['inventors'] = []
            
            if patent.get('assignees') and isinstance(patent['assignees'], str):
                try:
                    patent['assignees'] = json.loads(patent['assignees'])
                except:
                    patent['assignees'] = []
            
            patent['relevance_score'] = score
            ranked_patents.append(patent)
        
        # Sort by relevance score
        ranked_patents.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        return ranked_patents[:limit]
        
    except Exception as e:
        logging.error(f"Search error: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def search_patents_simple(keywords, limit=20):
    """Simple keyword-based search without LLM"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Similar to above but without LLM ranking
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
        
        # Build keyword matching score
        keyword_cases = []
        for kw in keywords:
            keyword_cases.append(f"""
                CASE WHEN (
                    LOWER(u.title) LIKE '%{kw}%' OR
                    LOWER(u.abstract_text) LIKE '%{kw}%' OR
                    LOWER(u.description_text) LIKE '%{kw}%'
                ) THEN 1 ELSE 0 END
            """)
        
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
            ({' + '.join(keyword_cases)}) as keyword_matches
        FROM patent_data_unified u
        WHERE {' OR '.join(conditions)}
        ORDER BY keyword_matches DESC, u.pub_date DESC
        LIMIT %s
        """
        
        params.append(limit)
        cur.execute(query, params)
        patents = cur.fetchall()
        
        # Calculate relevance scores
        for patent in patents:
            matches = patent.pop('keyword_matches', 0)
            patent['relevance_score'] = matches / len(keywords) if keywords else 0
            
            # Convert JSON fields
            if patent.get('inventors') and isinstance(patent['inventors'], str):
                try:
                    patent['inventors'] = json.loads(patent['inventors'])
                except:
                    patent['inventors'] = []
            
            if patent.get('assignees') and isinstance(patent['assignees'], str):
                try:
                    patent['assignees'] = json.loads(patent['assignees'])
                except:
                    patent['assignees'] = []
        
        return patents
        
    except Exception as e:
        logging.error(f"Search error: {e}")
        return []
    finally:
        cur.close()
        conn.close()

@app.route('/')
def home():
    """Serve the search interface"""
    try:
        with open('patent_search_clickable.html', 'r') as f:
            return Response(f.read(), mimetype='text/html')
    except:
        # Fallback if file not found
        return jsonify({'status': 'API is running', 'endpoints': ['/search', '/patent/<pub_number>']})

@app.route('/search', methods=['POST'])
def search():
    """Search for similar patents"""
    try:
        data = request.get_json()
        description = data.get('description', '')
        use_llm = data.get('use_llm', False)
        limit = min(data.get('limit', 20), 100)
        
        if not description:
            return jsonify({'error': 'Description is required'}), 400
        
        # Extract keywords
        if use_llm:
            keywords = extract_keywords_with_llm(description)
            results = search_patents_with_llm(keywords, description, limit)
        else:
            keywords = extract_keywords(description)
            results = search_patents_simple(keywords, limit)
        
        # Format results
        formatted_results = []
        for patent in results:
            formatted = {
                'pub_number': patent.get('pub_number'),
                'title': patent.get('title'),
                'pub_date': str(patent.get('pub_date')) if patent.get('pub_date') else None,
                'relevance_score': patent.get('relevance_score', 0),
                'abstract': patent.get('abstract_text', '')[:500] if patent.get('abstract_text') else None,
                'has_description': bool(patent.get('description_text')),
                'inventors': patent.get('inventors', []),
                'assignees': patent.get('assignees', [])
            }
            formatted_results.append(formatted)
        
        return jsonify({
            'keywords': keywords,
            'results': formatted_results,
            'total_found': len(formatted_results)
        })
        
    except Exception as e:
        logging.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/patent/<pub_number>', methods=['GET'])
def get_patent_details(pub_number):
    """Get detailed information about a specific patent"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # First try patent_data_unified for full data
        cur.execute("""
            SELECT 
                u.pub_number,
                u.title,
                u.abstract_text,
                u.description_text,
                u.pub_date,
                u.filing_date,
                u.year,
                u.inventors,
                u.assignees,
                u.applicants,
                u.addresses
            FROM patent_data_unified u
            WHERE u.pub_number = %s
        """, (pub_number,))
        
        patent = cur.fetchone()
        
        if patent:
            # Convert JSON fields
            for field in ['inventors', 'assignees', 'applicants', 'addresses']:
                if patent.get(field) and isinstance(patent[field], str):
                    try:
                        patent[field] = json.loads(patent[field])
                    except:
                        patent[field] = []
            
            # Extract inventor names
            if patent.get('inventors'):
                inventor_names = []
                for inv in patent['inventors']:
                    if isinstance(inv, dict):
                        inventor_names.append(inv.get('name', 'Unknown'))
                    elif isinstance(inv, str):
                        inventor_names.append(inv)
                patent['inventors'] = inventor_names
            
            # Extract assignee names
            if patent.get('assignees'):
                assignee_names = []
                for ass in patent['assignees']:
                    if isinstance(ass, dict):
                        assignee_names.append(ass.get('name', 'Unknown'))
                    elif isinstance(ass, str):
                        assignee_names.append(ass)
                patent['assignees'] = assignee_names
        
        else:
            # Fallback to publication table
            cur.execute("""
                SELECT 
                    p.pub_number,
                    p.invention_title as title,
                    p.pub_date,
                    p.kind,
                    p.app_number,
                    p.app_date
                FROM publication p
                WHERE p.pub_number = %s
            """, (pub_number,))
            
            patent = cur.fetchone()
            
            if patent:
                # Get parties (inventors and assignees)
                cur.execute("""
                    SELECT 
                        pp.party_type,
                        pp.name
                    FROM publication_party pp
                    WHERE pp.publication_pub_number = %s
                    ORDER BY pp.party_type, pp.seq_num
                """, (pub_number,))
                
                parties = cur.fetchall()
                
                patent['inventors'] = [p['name'] for p in parties if p['party_type'] == 'INVENTOR']
                patent['assignees'] = [p['name'] for p in parties if p['party_type'] == 'ASSIGNEE']
        
        if not patent:
            return jsonify({'error': 'Patent not found'}), 404
        
        # Format dates
        for date_field in ['pub_date', 'filing_date', 'app_date']:
            if patent.get(date_field):
                patent[date_field] = str(patent[date_field])
        
        return jsonify(patent)
        
    except Exception as e:
        logging.error(f"Error fetching patent details: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8091))
    app.run(host='0.0.0.0', port=port, debug=False)