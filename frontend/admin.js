document.addEventListener('DOMContentLoaded', () => {

console.log('✅ admin.js v2 loaded — ' + new Date().toLocaleTimeString());
checkAdminAuth();

async function checkAdminAuth() {
  try {
    const res  = await fetch('/admin/check');
    const data = await res.json();
    if (data.authenticated) {
      showAdminPanel();
      loadDashboard();
    } else {
      showLoginPage();
    }
  } catch (e) {
    console.error('Auth check failed:', e);
    showLoginPage();
  }
}

function showLoginPage() {
  document.getElementById('loginPage').classList.remove('hidden');
  document.getElementById('adminPanel').classList.remove('active');
  document.getElementById('loginError').classList.remove('show');
}

function showAdminPanel() {
  document.getElementById('adminPanel').classList.add('active');
  document.getElementById('loginPage').classList.add('hidden');
}

// ---- login ----
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorDiv = document.getElementById('loginError');
  errorDiv.classList.remove('show');
  errorDiv.textContent = '';

  const username = document.getElementById('adminUsername').value.trim();
  const password = document.getElementById('adminPassword').value;

  if (!username || !password) {
    errorDiv.textContent = 'Please enter username and password.';
    errorDiv.classList.add('show');
    return;
  }

  try {
    const res  = await fetch('/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();

    if (res.ok && data.success) {
      showAdminPanel();
      loadDashboard();
    } else {
      errorDiv.textContent = data.detail || 'Login failed';
      errorDiv.classList.add('show');
    }
  } catch (err) {
    console.error('Admin login error:', err);
    errorDiv.textContent = 'Network error. Please try again.';
    errorDiv.classList.add('show');
  }
});

// ---- logout ----
document.getElementById('logoutBtn').addEventListener('click', async () => {
  try {
    await fetch('/admin/logout', { method: 'POST' });
  } catch (e) { /* ignore */ }
  showLoginPage();
});

// ---- dashboard ----
async function loadDashboard() {
  try {
    const res  = await fetch('/admin/dashboard');
    const data = await res.json();
    document.getElementById('totalUsers').textContent    = data.stats.total_users;
    document.getElementById('totalMessages').textContent = data.stats.total_messages;
    document.getElementById('totalXP').textContent       = data.stats.total_xp;
    document.getElementById('activeToday').textContent   = data.stats.active_today;
    loadUsers();
  } catch (e) {
    console.error('Dashboard load failed:', e);
  }
}

// ---- users table ----
async function loadUsers() {
  try {
    const res  = await fetch('/admin/users');
    const data = await res.json();
    const tbody = document.getElementById('usersTableBody');
    tbody.innerHTML = '';

    if (!data.users || data.users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">No users yet</td></tr>';
      return;
    }

    data.users.forEach(user => {
      const row = document.createElement('tr');
      row.innerHTML =
        '<td><strong>' + user.username + '</strong></td>' +
        '<td>' + (user.email || 'N/A') + '</td>' +
        '<td><span class="badge badge-success">' + user.xp + ' XP</span></td>' +
        '<td><span class="badge badge-warning">' + user.level + '</span></td>' +
        '<td>' + user.streak + ' 🔥</td>' +
        '<td>' + (user.last_active || 'Never') + '</td>' +
        '<td>' +
          '<button class="action-btn btn-view"  onclick="viewUser(\'' + user.id + '\')">View</button>' +
          '<button class="action-btn btn-edit"  onclick="editUser(\'' + user.id + '\',' + user.xp + ',\'' + user.level + '\',' + user.streak + ')">Edit</button>' +
          '<button class="action-btn btn-delete" onclick="deleteUser(\'' + user.id + '\',\'' + user.username + '\')">Delete</button>' +
        '</td>';
      tbody.appendChild(row);
    });
  } catch (e) {
    console.error('Users load failed:', e);
  }
}

// ---- view user modal ----
async function viewUser(userId) {
  try {
    const res  = await fetch('/admin/user/' + userId);
    const data = await res.json();
    const user = data.user;

    let html =
      '<h3>' + user.username + '</h3>' +
      '<p><strong>Email:</strong> ' + (user.email || 'N/A') + '</p>' +
      '<p><strong>XP:</strong> ' + user.xp + '</p>' +
      '<p><strong>Level:</strong> ' + user.level + '</p>' +
      '<p><strong>Streak:</strong> ' + user.streak + ' days 🔥</p>' +
      '<p><strong>Created:</strong> ' + user.created_at + '</p>' +
      '<p><strong>Last Active:</strong> ' + user.last_active + '</p>';

    // XP history
    html += '<h4 style="margin-top:20px;">XP History</h4>' +
      '<table style="font-size:12px;"><thead><tr><th>Date</th><th>Event</th><th>XP</th><th>Total</th></tr></thead><tbody>';
    (data.xp_history || []).forEach(function(log) {
      html += '<tr><td>' + log.ts + '</td><td>' + log.event + '</td><td>+' + log.xp_delta + '</td><td>' + log.xp_total + '</td></tr>';
    });
    html += '</tbody></table>';

    // Chat history
    html += '<h4 style="margin-top:20px;">Recent Chat</h4><div class="chat-log">';
    (data.chat_history || []).forEach(function(msg) {
      var preview = msg.content.length > 100 ? msg.content.substring(0, 100) + '...' : msg.content;
      html += '<div class="chat-message ' + msg.role + '"><strong>' + msg.role + ':</strong> ' + preview + '</div>';
    });
    html += '</div>';

    document.getElementById('userDetailContent').innerHTML = html;
    document.getElementById('userModal').classList.add('active');
  } catch (e) {
    console.error('View user failed:', e);
    alert('Failed to load user details');
  }
}

function closeModal() {
  document.getElementById('userModal').classList.remove('active');
}

// ---- edit user modal ----
function editUser(userId, xp, level, streak) {
  document.getElementById('editUserId').value  = userId;
  document.getElementById('editXP').value      = xp;
  document.getElementById('editLevel').value   = level;
  document.getElementById('editStreak').value  = streak;
  document.getElementById('editModal').classList.add('active');
}

function closeEditModal() {
  document.getElementById('editModal').classList.remove('active');
}

document.getElementById('editUserForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const userId = document.getElementById('editUserId').value;
  const xp     = document.getElementById('editXP').value;
  const level  = document.getElementById('editLevel').value;
  const streak = document.getElementById('editStreak').value;

  try {
    const res = await fetch('/admin/user/' + userId + '?xp=' + xp + '&level=' + level + '&streak=' + streak, {
      method: 'PUT'
    });
    if (res.ok) {
      closeEditModal();
      loadUsers();
    } else {
      alert('Failed to update user');
    }
  } catch (e) {
    console.error('Edit user failed:', e);
    alert('Failed to update user');
  }
});

// ---- delete user ----
async function deleteUser(userId, username) {
  if (!confirm('Delete "' + username + '"? This is permanent!')) return;
  try {
    const res = await fetch('/admin/user/' + userId, { method: 'DELETE' });
    if (res.ok) {
      loadDashboard();
    } else {
      alert('Failed to delete user');
    }
  } catch (e) {
    console.error('Delete user failed:', e);
    alert('Failed to delete user');
  }
}

// ---- auto-refresh every 30s ----
setInterval(() => {
  if (document.getElementById('adminPanel').classList.contains('active')) {
    loadDashboard();
  }
}, 30000);

}); // end DOMContentLoaded