const form = document.getElementById('authForm');
const error = document.getElementById('error');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  error.textContent = '';
  error.classList.remove('auth-success');
  const button = form.querySelector('button');
  button.disabled = true;
  button.textContent = 'Creating...';
  try {
    const response = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: document.getElementById('name').value,
        email: document.getElementById('email').value,
        password: document.getElementById('password').value
      })
    });
    const data = await response.json();
    if (!response.ok) {
      error.textContent = data.error || 'Unable to create account.';
      return;
    }
    error.classList.add('auth-success');
    error.textContent = data.message || 'Check your email to verify your account.';
    form.reset();
  } catch (err) {
    error.textContent = 'Network error. Please try again.';
  } finally {
    button.disabled = false;
    button.textContent = 'Create account';
  }
});
