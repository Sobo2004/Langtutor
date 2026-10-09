// ============== VALIDATION FUNCTIONS ==============

function validateEmail(email) {
  const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  return re.test(email);
}

// AI-powered domain check — returns { valid: true } or { valid: false, error: '...' }
async function checkEmailDomain(email) {
  const domain = email.split('@')[1]?.toLowerCase();
  if (!domain) return { valid: false, error: 'Invalid email format' };

  try {
    const res = await fetch('/api/validate-email-domain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain })
    });
    const data = await res.json().catch(() => ({}));
    if (data.is_typo && data.suggestion) {
      return { valid: false, error: `Did you mean ${data.suggestion}? Please check the spelling.` };
    }
    return { valid: true };
  } catch {
    return { valid: true }; // fail open on network error
  }
}

function validateUsername(username) {
  if (username.length < 3) return { valid: false, error: "Username must be at least 3 characters" };
  if (username.length > 20) return { valid: false, error: "Username must be less than 20 characters" };
  if (!/^[a-zA-Z0-9_]+$/.test(username)) return { valid: false, error: "Username can only contain letters, numbers, and underscores" };
  return { valid: true };
}

function validatePassword(password) {
  const errors = [];
  if (password.length < 8) errors.push("At least 8 characters");
  if (!/[A-Z]/.test(password)) errors.push("One uppercase letter");
  if (!/[a-z]/.test(password)) errors.push("One lowercase letter");
  if (!/[0-9]/.test(password)) errors.push("One number");
  
  if (errors.length === 0) return { valid: true, strength: 'strong' };
  if (errors.length <= 2) return { valid: false, strength: 'medium', errors };
  return { valid: false, strength: 'weak', errors };
}

function showPasswordStrength(inputId, strengthId) {
  const input = document.getElementById(inputId);
  const indicator = document.getElementById(strengthId);
  
  input.addEventListener('input', function() {
    const result = validatePassword(this.value);
    
    if (this.value.length === 0) {
      indicator.className = 'password-strength';
      return;
    }
    
    indicator.className = 'password-strength active ' + result.strength;
  });
}

// ============== OTP INPUT HANDLING ==============

function setupOTPInputs(prefix) {
  for (let i = 1; i <= 6; i++) {
    const input = document.getElementById(prefix + i);
    if (!input) continue;
    
    input.addEventListener('input', function(e) {
      // Only allow numbers
      this.value = this.value.replace(/[^0-9]/g, '');
      
      // Auto-focus next box
      if (this.value.length === 1 && i < 6) {
        document.getElementById(prefix + (i + 1)).focus();
      }
    });
    
    input.addEventListener('keydown', function(e) {
      // Backspace moves to previous box
      if (e.key === 'Backspace' && this.value === '' && i > 1) {
        document.getElementById(prefix + (i - 1)).focus();
      }
    });
    
    // Paste handling - split 6 digits across boxes
    input.addEventListener('paste', function(e) {
      e.preventDefault();
      const pastedData = e.clipboardData.getData('text').replace(/[^0-9]/g, '');
      
      for (let j = 0; j < Math.min(6, pastedData.length); j++) {
        const box = document.getElementById(prefix + (j + 1));
        if (box) box.value = pastedData[j];
      }
      
      // Focus last filled box
      const lastBox = Math.min(6, pastedData.length);
      document.getElementById(prefix + lastBox).focus();
    });
  }
}

function getOTPValue(prefix) {
  let code = '';
  for (let i = 1; i <= 6; i++) {
    const input = document.getElementById(prefix + i);
    if (input) code += input.value;
  }
  return code;
}

function clearOTP(prefix) {
  for (let i = 1; i <= 6; i++) {
    const input = document.getElementById(prefix + i);
    if (input) {
      input.value = '';
      input.classList.remove('error');
    }
  }
  document.getElementById(prefix + '1').focus();
}

function showOTPError(prefix) {
  for (let i = 1; i <= 6; i++) {
    const input = document.getElementById(prefix + i);
    if (input) input.classList.add('error');
  }
}

// ============== COUNTDOWN TIMER ==============

function startCountdown(btnId, timerId, seconds, callback) {
  const btn = document.getElementById(btnId);
  const timer = document.getElementById(timerId);
  let remaining = seconds;
  
  btn.disabled = true;
  
  const interval = setInterval(() => {
    remaining--;
    timer.textContent = remaining;
    
    if (remaining <= 0) {
      clearInterval(interval);
      btn.disabled = false;
      btn.textContent = btn.textContent.replace(/\(\d+s\)/, '');
      if (callback) callback();
    }
  }, 1000);
}

// Sign-up and login forms are handled by the inline script in index.html.
// This file provides validation helpers and the forgot-password flow.

// Immediately start onboarding/recap flow after login
if (window.startPostLoginFlow) {
  window.startPostLoginFlow();
} else {
  // fallback: fire an event if app.js loads later
  window.dispatchEvent(new Event("auth:loggedin"));
}


// ============== FORGOT PASSWORD FLOW ==============

let forgotPasswordEmail = '';

function showForgotPassword() {
  document.getElementById('forgotPasswordModal').classList.add('active');
  document.getElementById('forgotStep1').classList.add('active');
  document.getElementById('forgotStep2').classList.remove('active');
  document.getElementById('forgotStep3').classList.remove('active');
}

function closeForgotPassword() {
  document.getElementById('forgotPasswordModal').classList.remove('active');
}

async function sendResetCode() {
  const email = document.getElementById('forgotEmail').value.trim();
  
  if (!validateEmail(email)) {
    document.getElementById('forgotError1').textContent = 'Please enter a valid email (e.g. name@gmail.com)';
    return;
  }

  const domainCheck = await checkEmailDomain(email);
  if (!domainCheck.valid) {
    document.getElementById('forgotError1').textContent = domainCheck.error;
    return;
  }

  try {
    const res = await fetch('/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });
    
    const data = await res.json();
    
    if (res.ok) {
      forgotPasswordEmail = email;
      document.getElementById('forgotEmailDisplay').textContent = email;
      document.getElementById('forgotStep1').classList.remove('active');
      document.getElementById('forgotStep2').classList.add('active');
      clearOTP('reset');
      document.getElementById('reset1').focus();
      startCountdown('btnResendReset', 'resetTimer', 30);

      // Dev mode: no SMTP configured — show code directly in UI
      if (data.dev_code) {
        const notice = document.getElementById('devCodeNotice');
        if (notice) {
          notice.textContent = `Dev mode — your code is: ${data.dev_code}`;
          notice.style.display = 'block';
        }
      }
    } else {
      document.getElementById('forgotError1').textContent = data.detail || 'Failed to send code.';
    }
  } catch (err) {
    document.getElementById('forgotError1').textContent = 'Network error. Please try again.';
  }
}

async function resetPassword() {
  const code = getOTPValue('reset');
  const newPassword = document.getElementById('resetNewPassword').value;
  const confirmPassword = document.getElementById('resetConfirmPassword').value;
  
  if (code.length !== 6) {
    document.getElementById('forgotError2').textContent = 'Please enter all 6 digits';
    showOTPError('reset');
    return;
  }
  
  const passwordCheck = validatePassword(newPassword);
  if (!passwordCheck.valid) {
    document.getElementById('forgotError2').textContent = 'Password requirements: ' + passwordCheck.errors.join(', ');
    return;
  }
  
  if (newPassword !== confirmPassword) {
    document.getElementById('forgotError2').textContent = 'Passwords do not match';
    return;
  }
  
  try {
    const res = await fetch('/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: forgotPasswordEmail,
        code: code,
        new_password: newPassword
      })
    });
    
    const data = await res.json();
    
    if (!res.ok) {
      document.getElementById('forgotError2').textContent = data.detail || 'Reset failed';
      showOTPError('reset');
      clearOTP('reset');
      return;
    }
    
    // Success!
    document.getElementById('forgotStep2').classList.remove('active');
    document.getElementById('forgotStep3').classList.add('active');
  } catch (err) {
    document.getElementById('forgotError2').textContent = 'Network error. Please try again.';
  }
}

async function resendResetCode() {
  try {
    const res = await fetch('/auth/resend-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: forgotPasswordEmail,
        purpose: 'forgot_password'
      })
    });
    
    if (res.ok) {
      clearOTP('reset');
      document.getElementById('forgotError2').textContent = '';
      alert('A new code has been sent to your email.');
      startCountdown('btnResendReset', 'resetTimer', 30);
    }
  } catch (err) {
    console.error('Resend failed:', err);
  }
}

// ============== INITIALIZE ==============

document.addEventListener('DOMContentLoaded', function() {
  // Setup the reset-code inputs
  setupOTPInputs('reset');

  // Setup password strength indicators
  showPasswordStrength('resetNewPassword', 'resetPasswordStrength');

  function on(id, handler) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', handler);
  }

  // Forgot Password buttons
  on('closeForgotPassword', closeForgotPassword);
  on('btnSendResetCode', sendResetCode);
  on('btnResetPassword', resetPassword);
  on('btnResendReset', resendResetCode);
  on('btnBackToLogin', function() {
    closeForgotPassword();
    showLoginPage();
  });
});