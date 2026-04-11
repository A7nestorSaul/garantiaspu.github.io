const form = document.getElementById('login-form');
const message = document.getElementById('login-message');

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;

  message.textContent = '';

  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });

    const data = await response.json();

    if (!response.ok) {
      message.textContent = data.message || 'No se pudo iniciar sesión.';
      return;
    }

    localStorage.setItem('authUser', JSON.stringify(data.user));
    window.location.href = '/app.html';
  } catch (_error) {
    message.textContent = 'Error de conexión con el servidor.';
  }
});
