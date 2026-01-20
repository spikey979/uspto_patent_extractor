// Patent Search Application JavaScript

let searchResults = [];
let progressInterval = null;

async function performSearch() {
    const description = document.getElementById('description').value.trim();
    if (!description) {
        alert('Please enter a description');
        return;
    }
    
    // Reset and show progress
    document.getElementById('searchBtn').disabled = true;
    document.getElementById('progressContainer').classList.add('active');
    document.getElementById('results').classList.remove('active');
    
    // Start progress animation
    let progress = 0;
    updateProgress(0, 'Extracting keywords...');
    
    progressInterval = setInterval(() => {
        if (progress < 90) {
            progress += Math.random() * 15;
            progress = Math.min(progress, 90);
            
            if (progress < 30) {
                updateProgress(progress, 'Extracting keywords...');
            } else if (progress < 60) {
                updateProgress(progress, 'Searching patent database...');
            } else {
                updateProgress(progress, 'Calculating relevance scores...');
            }
        }
    }, 500);
    
    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({description: description})
        });
        
        const data = await response.json();
        
        clearInterval(progressInterval);
        
        if (data.error) {
            alert('Search failed: ' + data.error);
            document.getElementById('progressContainer').classList.remove('active');
            return;
        }
        
        updateProgress(100, 'Search complete!');
        setTimeout(() => {
            document.getElementById('progressContainer').classList.remove('active');
            displayResults(data);
        }, 500);
        
    } catch (error) {
        clearInterval(progressInterval);
        alert('Search failed: ' + error.message);
        document.getElementById('progressContainer').classList.remove('active');
    } finally {
        document.getElementById('searchBtn').disabled = false;
    }
}

function updateProgress(percent, text) {
    percent = Math.round(percent);
    document.getElementById('progressFill').style.width = percent + '%';
    document.getElementById('progressFill').textContent = percent + '%';
    document.getElementById('progressText').textContent = text;
}

function displayResults(data) {
    searchResults = data.results || [];
    
    // Display stats
    document.getElementById('results').classList.add('active');
    document.getElementById('stats').innerHTML = `
        <div class="stat-item">
            <div class="stat-value">${data.total_results}</div>
            <div class="stat-label">Total Results</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.high_relevance}</div>
            <div class="stat-label">High Relevance (≥65%)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.medium_relevance}</div>
            <div class="stat-label">Medium Relevance (35-64%)</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${data.low_relevance}</div>
            <div class="stat-label">Low Relevance (<35%)</div>
        </div>
    `;
    
    // Display results
    const resultsList = document.getElementById('resultsList');
    
    if (!searchResults || searchResults.length === 0) {
        resultsList.innerHTML = '<div class="no-results">No patents found matching your description</div>';
        return;
    }
    
    resultsList.innerHTML = searchResults.map((patent, idx) => {
        const relevancePercent = Math.round((patent.relevance_score || 0) * 100);
        
        // Format assignees - handle both string and object formats
        let assigneeDisplay = 'N/A';
        if (patent.assignees && patent.assignees.length > 0) {
            if (typeof patent.assignees[0] === 'string') {
                assigneeDisplay = patent.assignees[0];
            } else if (patent.assignees[0].name) {
                assigneeDisplay = patent.assignees[0].name;
            }
        }
        
        // Format inventors - handle both string and object formats
        let inventorDisplay = 'N/A';
        if (patent.inventors && patent.inventors.length > 0) {
            const inventorNames = patent.inventors.slice(0, 2).map(inv => {
                if (typeof inv === 'string') return inv;
                return inv.name || 'Unknown';
            });
            inventorDisplay = inventorNames.join(', ');
            if (patent.inventors.length > 2) inventorDisplay += '...';
        }
        
        return `
            <div class="patent-item" onclick="showPatentDetail('${patent.pub_number}')">
                <div class="patent-header">
                    <div style="flex: 1;">
                        <span style="font-weight: 600; color: #666;">#${idx + 1}</span> - 
                        <span style="font-weight: 600; color: #2c3e50;">${patent.pub_number}</span>
                    </div>
                    <span class="relevance-badge relevance-${patent.relevance_level}">
                        ${patent.relevance_level} (${relevancePercent}%)
                    </span>
                </div>
                <div class="patent-title">${patent.title || 'Untitled'}</div>
                <div class="patent-meta">
                    📅 ${patent.pub_date || 'N/A'} | 
                    🏢 ${assigneeDisplay} | 
                    👤 ${inventorDisplay}
                </div>
                <div class="patent-abstract">
                    ${patent.abstract ? patent.abstract.substring(0, 200) + '...' : 'No abstract available'}
                </div>
            </div>
        `;
    }).join('');
}

async function showPatentDetail(pubNumber) {
    try {
        const response = await fetch(`/api/patent/${pubNumber}`);
        const data = await response.json();
        
        if (data.error) {
            alert('Failed to load patent details');
            return;
        }
        
        const patent = data.patent;
        
        // Format inventors list
        let inventorsHtml = 'None listed';
        if (patent.inventors && patent.inventors.length > 0) {
            inventorsHtml = '<ul>' + patent.inventors.map(inv => {
                const name = typeof inv === 'string' ? inv : (inv.name || 'Unknown');
                return `<li>${name}</li>`;
            }).join('') + '</ul>';
        }
        
        // Format assignees list
        let assigneesHtml = 'None listed';
        if (patent.assignees && patent.assignees.length > 0) {
            assigneesHtml = '<ul>' + patent.assignees.map(ass => {
                const name = typeof ass === 'string' ? ass : (ass.name || 'Unknown');
                return `<li>${name}</li>`;
            }).join('') + '</ul>';
        }
        
        const detailHTML = `
            <h2>${patent.title || 'Untitled Patent'}</h2>
            
            <div class="detail-meta">
                <div class="detail-meta-item">
                    <div class="detail-meta-label">Patent Number</div>
                    <div class="detail-meta-value">${patent.pub_number}</div>
                </div>
                <div class="detail-meta-item">
                    <div class="detail-meta-label">Publication Date</div>
                    <div class="detail-meta-value">${patent.pub_date || 'N/A'}</div>
                </div>
                <div class="detail-meta-item">
                    <div class="detail-meta-label">Filing Date</div>
                    <div class="detail-meta-value">${patent.filing_date || 'N/A'}</div>
                </div>
                <div class="detail-meta-item">
                    <div class="detail-meta-label">Year</div>
                    <div class="detail-meta-value">${patent.year || 'N/A'}</div>
                </div>
            </div>
            
            <div class="detail-section">
                <h3>Abstract</h3>
                <p>${patent.abstract_text || 'No abstract available'}</p>
            </div>
            
            <div class="detail-section">
                <h3>Inventors</h3>
                ${inventorsHtml}
            </div>
            
            <div class="detail-section">
                <h3>Assignees</h3>
                ${assigneesHtml}
            </div>
            
            ${patent.description_text ? `
            <div class="detail-section">
                <h3>Description</h3>
                <p>${patent.description_text.substring(0, 3000)}${patent.description_text.length > 3000 ? '...' : ''}</p>
            </div>
            ` : ''}
        `;
        
        document.getElementById('patentDetail').innerHTML = detailHTML;
        document.getElementById('patentModal').classList.add('active');
        
    } catch (error) {
        alert('Failed to load patent details: ' + error.message);
    }
}

function closeModal() {
    document.getElementById('patentModal').classList.remove('active');
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('patentModal');
    if (event.target == modal) {
        closeModal();
    }
}
EOF"