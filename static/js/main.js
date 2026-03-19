/* ── TOAST ── */
function toast(msg, type='info') {
  const t = document.getElementById('toast');
  if(!t) return;
  const d = document.createElement('div');
  d.className = `toast-msg ${type}`;
  d.textContent = msg;
  t.appendChild(d);
  setTimeout(() => d.remove(), 3400);
}

/* ── API KEY MODAL ── */
document.getElementById('key-modal')?.addEventListener('click', function(e){
  if(e.target === this) this.classList.remove('open');
});

async function saveApiKey() {
  const key = document.getElementById('api-key-input')?.value.trim();
  if(!key) { toast('Please enter a key', 'error'); return; }
  const res = await fetch('/api/set_key', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key})});
  const d = await res.json();
  if(d.ok) { document.getElementById('key-modal')?.classList.remove('open'); toast('API key saved ✓', 'success'); }
  else toast('Failed to save key', 'error');
}

async function testKey() {
  const key = document.getElementById('api-key-input')?.value.trim();
  if(!key) { toast('Enter a key first', 'error'); return; }
  // Save it first so test_key route can use it
  await fetch('/api/set_key', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key})});
  const result = document.getElementById('key-test-result');
  if(result) { result.style.display='block'; result.textContent='Testing...'; result.style.color='var(--text3)'; }
  const res = await fetch('/api/test_key');
  const d = await res.json();
  if(result) {
    result.style.display = 'block';
    if(d.ok) { result.textContent = '✓ Key is valid and working!'; result.style.color = 'var(--green)'; }
    else { result.textContent = '✗ ' + (d.msg||'Key invalid'); result.style.color = 'var(--red)'; }
  }
}

/* ── UPLOAD ZONES ── */
document.querySelectorAll('.upload-zone').forEach(zone => {
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag-over');
    const inp = zone.querySelector('input[type=file]');
    if(e.dataTransfer.files.length && inp) {
      const dt = new DataTransfer(); dt.items.add(e.dataTransfer.files[0]);
      inp.files = dt.files;
      const nameEl = zone.querySelector('strong');
      if(nameEl) nameEl.textContent = e.dataTransfer.files[0].name;
    }
  });
  const inp = zone.querySelector('input[type=file]');
  if(inp) inp.addEventListener('change', () => {
    if(inp.files[0]) { const s = zone.querySelector('strong'); if(s) s.textContent = inp.files[0].name; }
  });
});

/* ── UPLOAD FORM ── */
const uploadForm = document.getElementById('upload-form');
if(uploadForm) {
  uploadForm.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = uploadForm.querySelector('button[type=submit]');
    btn.disabled = true;

    const pIS = document.getElementById('prog-is');
    const pBS = document.getElementById('prog-bs');

    function anim(bar) {
      if(!bar) return;
      bar.classList.add('active');
      let w = 0;
      const fill = bar.querySelector('.progress-fill');
      const pct = bar.querySelector('.pct');
      const iv = setInterval(() => {
        w += Math.random()*14+4;
        if(w>=92) { w=92; clearInterval(iv); }
        if(fill) fill.style.width = w+'%';
        if(pct)  pct.textContent = Math.round(w)+'%';
      }, 80);
    }

    anim(pIS); setTimeout(() => anim(pBS), 280);
    await new Promise(r => setTimeout(r, 1600));
    [pIS, pBS].forEach(bar => {
      if(!bar) return;
      const fill = bar.querySelector('.progress-fill'); const pct = bar.querySelector('.pct');
      if(fill) fill.style.width = '100%'; if(pct) pct.textContent = '100%';
    });
    await new Promise(r => setTimeout(r, 300));

    const fd = new FormData(uploadForm);
    const res = await fetch('/upload', {method:'POST', body:fd});
    const d = await res.json();
    if(d.ok) { toast('Files loaded ✓', 'success'); setTimeout(() => window.location.href='/statements', 500); }
    else { toast(d.msg||'Upload failed', 'error'); btn.disabled=false; }
  });
}

/* ── CHART SETUP ── */
Chart.defaults.color = '#475569';
Chart.defaults.borderColor = 'rgba(255,255,255,0.05)';
Chart.defaults.font.family = "'IBM Plex Mono', monospace";
Chart.defaults.font.size = 10;

const TOOLTIP = {
  backgroundColor:'#182035', borderColor:'rgba(255,255,255,0.07)', borderWidth:1,
  titleColor:'#E2E8F4', bodyColor:'#94A3B8', padding:10
};

function makeBarChart(id, labels, datasets, extraOpts={}) {
  const ctx = document.getElementById(id); if(!ctx) return null;
  return new Chart(ctx, {type:'bar', data:{labels, datasets},
    options:{responsive:true,
      plugins:{legend:{display:datasets.length>1, labels:{color:'#64748b',boxWidth:10,padding:14}}, tooltip:TOOLTIP},
      scales:{x:{grid:{color:'rgba(255,255,255,0.035)'},ticks:{color:'#475569'}},
              y:{grid:{color:'rgba(255,255,255,0.035)'},ticks:{color:'#475569'}}},
      ...extraOpts}});
}

function makeDonutChart(id, labels, data, colors) {
  const ctx = document.getElementById(id); if(!ctx) return null;
  return new Chart(ctx, {type:'doughnut',
    data:{labels, datasets:[{data, backgroundColor:colors, borderColor:'rgba(0,0,0,0)', borderWidth:0, hoverOffset:4}]},
    options:{responsive:true, cutout:'68%',
      plugins:{legend:{position:'bottom',labels:{color:'#64748b',boxWidth:10,padding:14}}, tooltip:TOOLTIP}}});
}

function makeRadarChart(id, labels, datasets) {
  const ctx = document.getElementById(id); if(!ctx) return null;
  return new Chart(ctx, {type:'radar', data:{labels, datasets},
    options:{responsive:true,
      scales:{r:{grid:{color:'rgba(255,255,255,0.06)'},angleLines:{color:'rgba(255,255,255,0.06)'},
                 ticks:{color:'#475569',backdropColor:'transparent',font:{size:9}},
                 pointLabels:{color:'#64748b',font:{size:9}}}},
      plugins:{legend:{labels:{color:'#64748b',boxWidth:10}}, tooltip:TOOLTIP}}});
}

/* ── AI STREAM ── */
let aiStreamInFlight = false;
function startAIStream() {
  if (aiStreamInFlight) return;
  const btn = document.getElementById('ai-btn');
  const spin = document.getElementById('ai-spin');
  const out = document.getElementById('ai-output');
  if(!out) return;
  aiStreamInFlight = true;

  btn.style.display = 'none';
  spin.style.display = 'flex';
  out.innerHTML = '';
  out.classList.add('typing-cursor');

  const es = new EventSource('/ai/stream');
  let full = '';

  es.onmessage = e => {
    try {
      const d = JSON.parse(e.data);
      if(d.done) {
        es.close(); out.classList.remove('typing-cursor');
        spin.style.display='none'; btn.style.display='inline-flex';
        aiStreamInFlight = false;
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Regenerate';
        return;
      }
      if(d.error) {
        es.close(); out.classList.remove('typing-cursor');
        spin.style.display='none'; btn.style.display='inline-flex';
        aiStreamInFlight = false;
        const msg = d.error==='NO_API_KEY'
          ? '⚠ No API key — click <strong>Set Gemini API Key</strong> in the sidebar.'
          : '⚠ Error: ' + d.error;
        out.innerHTML = `<div class="alert alert-warn">${msg}</div>`;
        return;
      }
      if(d.chunk) {
        full += d.chunk;
        out.innerHTML = mdToHtml(full);
        out.scrollTop = out.scrollHeight;
      }
    } catch(err) {}
  };
  es.onerror = () => { es.close(); spin.style.display='none'; btn.style.display='inline-flex'; aiStreamInFlight = false; };
}

/* ── CHAT ── */
let chatInFlight = false;
async function sendChat() {
  if (chatInFlight) return;
  const inp = document.getElementById('chat-input');
  const msgs = document.getElementById('chat-messages');
  const msg = inp?.value.trim();
  if(!msg || !msgs) return;
  chatInFlight = true;

  inp.value = '';
  inp.style.height = 'auto';

  const userDiv = document.createElement('div');
  userDiv.className = 'chat-msg user';
  userDiv.textContent = msg;
  msgs.appendChild(userDiv);

  const think = document.createElement('div');
  think.className = 'chat-msg assistant';
  think.innerHTML = '<div class="spinner" style="display:inline-block;margin:4px 0;"></div>';
  msgs.appendChild(think);
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const res = await fetch('/chat/send', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({msg})});
    const d = await res.json();
    think.remove();

    const replyDiv = document.createElement('div');
    replyDiv.className = 'chat-msg assistant';
    replyDiv.innerHTML = mdToHtml(d.reply || 'Error getting response.');
    msgs.appendChild(replyDiv);
    msgs.scrollTop = msgs.scrollHeight;
  } catch (e) {
    think.remove();
    const replyDiv = document.createElement('div');
    replyDiv.className = 'chat-msg assistant';
    replyDiv.textContent = 'Connection error. Please try again in a few seconds.';
    msgs.appendChild(replyDiv);
    msgs.scrollTop = msgs.scrollHeight;
  } finally {
    chatInFlight = false;
  }
}

document.getElementById('chat-input')?.addEventListener('keydown', e => {
  if(e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

/* ── MARKDOWN → HTML ── */
function mdToHtml(md) {
  if(!md) return '';
  return md
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g,'<em>$1</em>')
    .replace(/`([^`\n]+)`/g,'<code>$1</code>')
    .replace(/^### (.+)$/gm,'<h3>$1</h3>')
    .replace(/^## (.+)$/gm,'<h2>$1</h2>')
    .replace(/^# (.+)$/gm,'<h1>$1</h1>')
    .replace(/^[•\-\*] (.+)$/gm,'<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g,'<ul>$1</ul>')
    .replace(/\n{2,}/g,'</p><p>')
    .replace(/\n/g,'<br>');
}
