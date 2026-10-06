const form = document.getElementById('authForm');
const error = document.getElementById('error');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  error.textContent = '';
  const button = form.querySelector('button');
  button.disabled = true;
  button.textContent = 'Signing in...';
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.getElementById('email').value,
        password: document.getElementById('password').value
      })
    });
    const data = await response.json();
    if (!response.ok) {
      error.textContent = data.error || 'Unable to sign in.';
      return;
    }
    window.location.href = '/';
  } catch (err) {
    error.textContent = 'Network error. Please try again.';
  } finally {
    button.disabled = false;
    button.textContent = 'Sign in';
  }
});
