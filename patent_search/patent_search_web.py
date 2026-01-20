#\!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import subprocess
import urllib.parse

class PatentSearchHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            with open('/home/mark/web/patent_search.html', 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        if self.path == '/search':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data)
            
            description = data.get('description', '')
            
            # Run the search script
            try:
                result = subprocess.run(
                    ['python3', '/home/mark/patent_search_fixed.py', description],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                # Parse the output
                output_lines = result.stdout.split('\n')
                keywords = []
                patents = []
                
                for line in output_lines:
                    if 'Extracted keywords:' in line:
                        keywords = line.split(': ', 1)[1].split(', ')
                    elif 'Patent:' in line and not line.startswith('🔍'):
                        patent_num = line.split('Patent: ')[1].strip()
                        patents.append({'pub_number': patent_num, 'lines': [line]})
                    elif patents and line.strip():
                        patents[-1]['lines'].append(line)
                
                # Format patents
                formatted_patents = []
                for p in patents[:20]:
                    patent_data = {'pub_number': p['pub_number']}
                    for line in p['lines']:
                        if 'Title:' in line:
                            patent_data['title'] = line.split('Title: ', 1)[1].strip()
                        elif 'Published:' in line:
                            patent_data['date_published'] = line.split('Published: ', 1)[1].strip()
                        elif 'Relevance:' in line:
                            score_str = line.split('Relevance: ')[1].replace('%', '').strip()
                            try:
                                patent_data['relevance_score'] = float(score_str) / 100.0
                            except:
                                patent_data['relevance_score'] = 0.0
                    formatted_patents.append(patent_data)
                
                response = {
                    'success': True,
                    'keywords': keywords,
                    'results': formatted_patents,
                    'total_found': len(formatted_patents)
                }
                
            except Exception as e:
                response = {
                    'success': False,
                    'error': str(e),
                    'results': []
                }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8080), PatentSearchHandler)
    print('Patent Search Server running on port 8080...')
    server.serve_forever()
