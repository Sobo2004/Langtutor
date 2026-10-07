async function getJSON(url) {
  const r = await fetch(url);
  return await r.json();
}

function drawChart(canvas, points) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  if (!points.length) {
    ctx.font = "14px system-ui";
    ctx.fillStyle = "#666";
    ctx.fillText("No XP history yet. Use the chat and complete a lesson step.", 20, 40);
    return;
  }

  const padL = 50, padR = 20, padT = 20, padB = 40;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  const xs = points.map((p, i) => i);
  const ys = points.map(p => p.xp_total);

  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanY = Math.max(1, maxY - minY);

  function xToPx(x) {
    if (xs.length === 1) return padL + plotW / 2;
    return padL + (x / (xs.length - 1)) * plotW;
  }
  function yToPx(y) {
    return padT + (1 - (y - minY) / spanY) * plotH;
  }

  ctx.strokeStyle = "#ddd";
  ctx.beginPath();
  ctx.moveTo(padL, padT);
  ctx.lineTo(padL, padT + plotH);
  ctx.lineTo(padL + plotW, padT + plotH);
  ctx.stroke();

  ctx.strokeStyle = "#667eea";
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((p, i) => {
    const px = xToPx(i);
    const py = yToPx(p.xp_total);
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.stroke();

  ctx.fillStyle = "#333";
  ctx.font = "12px system-ui";
  ctx.fillText(`XP`, 10, padT + 10);
  ctx.fillText(`${minY}`, 10, padT + plotH);
  ctx.fillText(`${maxY}`, 10, padT + 12);

  const first = points[0].date;
  const last = points[points.length - 1].date;
  ctx.fillText(first, padL, padT + plotH + 28);
  ctx.fillText(last, padL + plotW - ctx.measureText(last).width, padT + plotH + 28);
}

function renderTable(container, points) {
  if (!points.length) {
    container.innerHTML = `<div class="empty">No history yet.</div>`;
    return;
  }
  const rows = [...points].slice(-10).reverse();
  const html = `
    <table>
      <thead>
        <tr><th>Date</th><th>Event</th><th>XP Gained</th><th>Total XP</th></tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>${r.date}</td>
            <td>${r.event || 'Activity'}</td>
            <td>+${r.xp_gained}</td>
            <td>${r.xp_total}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  container.innerHTML = html;
}

function renderQuizHistory(container, quizzes) {
  if (!quizzes.length) {
    container.innerHTML = `<div class="empty">No quizzes taken yet. <a href="/quiz" style="color:#667eea;">Take your first quiz!</a></div>`;
    return;
  }
  
  const rows = quizzes.slice(0, 10);
  const html = `
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Category</th>
          <th>Difficulty</th>
          <th>Mode</th>
          <th>Score</th>
          <th>Questions</th>
          <th>Time</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(q => {
          const date = new Date(q.created_at).toLocaleDateString();
          const scoreClass = q.score_percentage >= 80 ? 'badge-success' : 
                             q.score_percentage >= 60 ? 'badge-warning' : 'badge-danger';
          const minutes = Math.floor(q.time_taken / 60);
          const seconds = q.time_taken % 60;
          const timeStr = `${minutes}:${seconds.toString().padStart(2, '0')}`;
          const modeIcon = q.language_mode === 'en-ru' ? '🇬🇧→🇷🇺' : '🇷🇺→🇬🇧';
          
          return `
            <tr>
              <td>${date}</td>
              <td style="text-transform:capitalize;">${q.category}</td>
              <td style="text-transform:capitalize;">${q.difficulty}</td>
              <td>${modeIcon}</td>
              <td><span class="badge ${scoreClass}">${q.score_percentage}%</span></td>
              <td>${q.correct_answers}/${q.total_questions}</td>
              <td>${timeStr}</td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
  container.innerHTML = html;
}

(async function init() {
  const canvas = document.getElementById("chart");
  const tableWrap = document.getElementById("tableWrap");
  const quizWrap = document.getElementById("quizHistoryWrap");

  // Load progress data
  const p = await getJSON("/api/progress");
  if (p.error) {
    document.getElementById("statXP").textContent = "0";
    document.getElementById("statStreak").textContent = "0";
    document.getElementById("statWords").textContent = "0";
    document.getElementById("statLevel").textContent = "A1";
    return;
  }

  document.getElementById("statXP").textContent = p.xp || 0;
  document.getElementById("statStreak").textContent = p.streak || 0;
  document.getElementById("statWords").textContent = p.words_completed || 0;
  document.getElementById("statLevel").textContent = p.level || "A1";

  // Set defaults first
  document.getElementById("statQuizzes").textContent = "0";
  document.getElementById("statAvgScore").textContent = "0%";

  // Load quiz stats
  try {
    const quizStats = await getJSON("/api/quiz/stats");
    console.log('Quiz stats:', quizStats);
    
    if (quizStats.error) {
      console.error('Quiz stats error:', quizStats.error);
      document.getElementById("statQuizzes").textContent = "Error";
      document.getElementById("statAvgScore").textContent = "Error";
    } else {
      const totalQuizzes = quizStats.total_quizzes || 0;
      const avgScore = quizStats.average_score || 0;
      
      document.getElementById("statQuizzes").textContent = totalQuizzes;
      document.getElementById("statAvgScore").textContent = avgScore > 0 ? avgScore + '%' : '0%';
      
      console.log(`Displayed: ${totalQuizzes} quizzes, ${avgScore}% avg`);
    }
  } catch (error) {
    console.error('Failed to load quiz stats:', error);
    document.getElementById("statQuizzes").textContent = "—";
    document.getElementById("statAvgScore").textContent = "—";
  }

  // Load XP history
  const h = await getJSON("/api/progress/history?days=30");
  const points = (h.history || []);
  drawChart(canvas, points);
  renderTable(tableWrap, points);

  // Load quiz history
  try {
    const quizHistory = await getJSON("/api/quiz/history");
    console.log('Quiz history:', quizHistory);
    renderQuizHistory(quizWrap, quizHistory.history || []);
  } catch (error) {
    console.error('Failed to load quiz history:', error);
    quizWrap.innerHTML = `<div class="empty">Failed to load quiz history.</div>`;
  }
})();