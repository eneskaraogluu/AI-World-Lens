let selectedPromptId = null;
let charts = { gender: null, age: null, location: null, socio: null };
let runTracker = {}; // Tracks if we ran the AI for a prompt in this session

// Chart default styling
Chart.defaults.color = '#8b949e';
Chart.defaults.font.family = 'Inter';
Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(15, 17, 26, 0.9)';
Chart.defaults.plugins.tooltip.titleColor = '#fff';
Chart.defaults.plugins.tooltip.padding = 12;

document.addEventListener('DOMContentLoaded', async () => {
    await initSidebar();

    document.getElementById('btn-run-mock').addEventListener('click', async (e) => {
        if (!selectedPromptId) return;
        const btn = e.target;
        btn.disabled = true;
        btn.innerText = "Running 10 AI...";
        
        // Start Overlay Animation
        const overlay = document.getElementById('loadingOverlay');
        const subtext = document.getElementById('loadingSubtext');
        overlay.classList.add('active');
        
        const texts = [
            "Connecting to OpenAI DALL-E 2...",
            "Generating 10 images...",
            "Initializing Gemini 2.5 Flash Coder...",
            "Initializing GPT-4o-mini Coder...",
            "Calculating Inter-coder reliability...",
            "Finalizing bias percentages..."
        ];
        let textIndex = 0;
        const textInterval = setInterval(() => {
            textIndex = (textIndex + 1) % texts.length;
            subtext.innerText = texts[textIndex];
        }, 3000);
        
        // Wait for a tiny bit for the animation to be visible
        await new Promise(r => setTimeout(r, 500));
        
        await runMockExperiment(selectedPromptId);
        runTracker[selectedPromptId] = true; // Mark as run
        await loadDashboardData(selectedPromptId);
        
        // End Overlay Animation
        clearInterval(textInterval);
        overlay.classList.remove('active');
        
        btn.innerText = "Run +10 AI";
        btn.disabled = false;
    });
});

async function initSidebar() {
    const promptList = document.getElementById('prompt-list');
    
    try {
        const categories = await fetchCategories();
        const prompts = await fetchPrompts();
        
        let html = '';
        categories.forEach(cat => {
            html += `<h3 style="margin-top: 1.5rem; margin-bottom: 0.5rem; color: #fff; font-size: 0.95rem; font-family: 'Syne', sans-serif;">${cat.name}</h3>`;
            const catPrompts = prompts.filter(p => p.category_id === cat.id);
            catPrompts.forEach(p => {
                html += `
                    <li class="nav-item prompt-item" data-id="${p.id}" data-text="${p.text}">
                        "${p.text}"
                    </li>
                `;
            });
        });
        
        promptList.innerHTML = html;

        // Add click events to prompts
        document.querySelectorAll('.prompt-item').forEach(item => {
            item.addEventListener('click', (e) => {
                document.querySelectorAll('.prompt-item').forEach(i => i.classList.remove('active'));
                e.target.classList.add('active');
                
                selectedPromptId = e.target.dataset.id;
                document.getElementById('current-prompt-title').innerText = `Prompt: "${e.target.dataset.text}"`;
                document.getElementById('btn-run-mock').disabled = false;
                
                // Eski haline getirildi: Tıklanınca geçmiş veriyi direkt yükle
                loadDashboardData(selectedPromptId);
            });
        });

    } catch (e) {
        console.error("Error loading sidebar", e);
        categoryList.innerHTML = "<li>Error connecting to API</li>";
    }
}

async function loadDashboardData(promptId) {
    try {
        let data = await fetchComparison(promptId);
        
        // If not run in this session, mask the AI data to surprise the user later
        if (!runTracker[promptId]) {
            data = JSON.parse(JSON.stringify(data)); // Deep clone
            data.total_generations = 0;
            data.avg_agreement_score = 0;
            
            const maskKeys = ["gender_comparison", "age_group_comparison", "location_comparison", "socioeconomic_comparison"];
            maskKeys.forEach(mk => {
                if(data[mk]) {
                    Object.keys(data[mk]).forEach(key => {
                        data[mk][key].ai_percentage = 0;
                        data[mk][key].difference = 0;
                    });
                }
            });
        }
        
        updateStats(data);
        drawChart('genderChart', 'gender', data.gender_comparison);
        drawChart('ageChart', 'age', data.age_group_comparison);
        
        if(data.location_comparison) drawChart('locationChart', 'location', data.location_comparison);
        if(data.socioeconomic_comparison) drawChart('socioChart', 'socio', data.socioeconomic_comparison);
        
        // Fetch and display images
        const images = await fetchImages(promptId);
        const gallery = document.getElementById('image-gallery');
        if (images && images.length > 0 && runTracker[promptId]) {
            gallery.innerHTML = images.map(img => 
                `<img src="/assets/generations/${img}" class="gallery-item" alt="AI Generated Evidence" loading="lazy">`
            ).join('');
        } else {
            gallery.innerHTML = `<p class="text-muted" style="grid-column: 1/-1; text-align: center;">No images generated yet. Click "Run +10 AI" to generate.</p>`;
        }
    } catch (e) {
        console.error("Error loading dashboard data", e);
    }
}

function updateStats(data) {
    document.getElementById('stat-total').innerText = data.total_generations;
    document.getElementById('stat-source').innerText = data.source;
    
    // Calculate a simple avg bias metric for UI wow factor
    let totalBias = 0;
    let count = 0;
    for (const key in data.gender_comparison) {
        totalBias += Math.abs(data.gender_comparison[key].difference);
        count++;
    }
    const avgBias = count > 0 ? (totalBias / count).toFixed(1) : 0;
    document.getElementById('stat-bias').innerText = `%${avgBias} Error`;
    
    // Update Reliability Score
    const relScore = data.avg_agreement_score !== undefined ? data.avg_agreement_score : 0;
    document.getElementById('stat-reliability').innerText = `%${relScore}`;
}

function drawChart(canvasId, type, comparisonData) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    // Destroy previous chart if exists
    if (charts[type]) charts[type].destroy();

    const labels = Object.keys(comparisonData);
    const realData = labels.map(l => comparisonData[l].real_world_percentage);
    const aiData = labels.map(l => comparisonData[l].ai_percentage);

    charts[type] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Real World (TÜİK)',
                    data: realData,
                    backgroundColor: 'rgba(16, 185, 129, 0.7)',
                    borderColor: 'rgb(16, 185, 129)',
                    borderWidth: 1,
                    borderRadius: 4
                },
                {
                    label: 'AI Generated',
                    data: aiData,
                    backgroundColor: 'rgba(99, 102, 241, 0.7)',
                    borderColor: 'rgb(99, 102, 241)',
                    borderWidth: 1,
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 1000,
                easing: 'easeOutQuart'
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { callback: (val) => val + '%' }
                },
                x: {
                    grid: { display: false }
                }
            },
            plugins: {
                legend: { position: 'top', labels: { color: '#f8f9fa' } },
                tooltip: {
                    callbacks: {
                        label: (context) => `${context.dataset.label}: ${context.parsed.y}%`
                    }
                }
            }
        }
    });
}
