const loginView = document.getElementById('loginView');
const appView = document.getElementById('appView');
const loginForm = document.getElementById('loginForm');
const loginError = document.getElementById('loginError');
const currentUser = document.getElementById('currentUser');
const logoutBtn = document.getElementById('logoutBtn');

const recordForm = document.getElementById('recordForm');
const recordIdInput = document.getElementById('recordId');
const formTitle = document.getElementById('formTitle');
const cancelEditBtn = document.getElementById('cancelEdit');
const filterNavieraInput = document.getElementById('filterNaviera');
const recordsTableBody = document.getElementById('recordsTableBody');
const fileInput = document.getElementById('fileInput');
const importBtn = document.getElementById('importBtn');
const pendingCount = document.getElementById('pendingCount');
const pendingList = document.getElementById('pendingList');
const paymentsFileInput = document.getElementById('paymentsFileInput');
const validatePaymentsBtn = document.getElementById('validatePaymentsBtn');
const paymentSuggestions = document.getElementById('paymentSuggestions');
const docRecordSelect = document.getElementById('docRecordSelect');
const bankSelect = document.getElementById('bankSelect');
const bankCoverInput = document.getElementById('bankCoverInput');
const emailCaptureInput = document.getElementById('emailCaptureInput');
const fiscalFileInput = document.getElementById('fiscalFileInput');
const generateDocBtn = document.getElementById('generateDocBtn');

const estatusClass = {
  'Pendiente': 'status-pendiente',
  'En Proceso': 'status-en-proceso',
  'Recuperado': 'status-recuperado',
  'Pagado': 'status-pagado',
};

function setSession(user) {
  localStorage.setItem('sessionUser', JSON.stringify(user));
}

function getSession() {
  const raw = localStorage.getItem('sessionUser');
  return raw ? JSON.parse(raw) : null;
}

function clearSession() {
  localStorage.removeItem('sessionUser');
}

function showApp(user) {
  loginView.classList.add('hidden');
  appView.classList.remove('hidden');
  currentUser.textContent = `Usuario: ${user.username}`;
  loadRecords();
}

function showLogin() {
  appView.classList.add('hidden');
  loginView.classList.remove('hidden');
}

async function loadRecords() {
  const naviera = filterNavieraInput.value.trim();
  const url = naviera ? `/api/records?naviera=${encodeURIComponent(naviera)}` : '/api/records';
  const res = await fetch(url);
  const records = await res.json();
  recordsTableBody.innerHTML = '';
  renderPendingSection(records);
  renderRecordOptions(records);

  records.forEach((record) => {
    const overdue = isOverdue(record.fecha_recuperacion) && record.estatus !== 'Pagado';
    const tr = document.createElement('tr');
    if (overdue) tr.classList.add('overdue-row');
    tr.innerHTML = `
      <td>${record.referencia}</td>
      <td>${record.naviera}</td>
      <td>${record.bl}</td>
      <td>${Number(record.total).toFixed(2)}</td>
      <td>${record.fecha_recuperacion}</td>
      <td><span class="badge ${estatusClass[record.estatus] || ''}">${record.estatus}</span></td>
      <td>${overdue ? '<span class="overdue-indicator"></span>' : '<span class="ok-indicator"></span>'}</td>
      <td>${renderExpiryInfo(record)}</td>
      <td>
        <button data-action="edit" data-id="${record.id}">Editar</button>
        <button data-action="delete" data-id="${record.id}" class="secondary">Eliminar</button>
        ${record.generated_pdf_path ? `<a href="/api/documents/download/${record.id}" target="_blank">Descargar PDF</a>` : ''}
      </td>
    `;
    recordsTableBody.appendChild(tr);
  });
}

function daysRemaining(isoDate) {
  if (!isoDate) return null;
  const now = new Date();
  const end = new Date(`${isoDate}T00:00:00`);
  now.setHours(0, 0, 0, 0);
  const diff = Math.ceil((end - now) / (1000 * 60 * 60 * 24));
  return diff;
}

function expiryBadge(label, isoDate) {
  const days = daysRemaining(isoDate);
  if (days === null) return `<div class="expiry missing">${label}: sin carga</div>`;
  if (days < 0) return `<div class="expiry expired">${label}: vencido</div>`;
  return `<div class="expiry valid">${label}: ${days} días</div>`;
}

function renderExpiryInfo(record) {
  return [
    expiryBadge('Carátula', record.bank_cover_expires_at),
    expiryBadge('Fiscal', record.fiscal_expires_at),
  ].join('');
}

function renderRecordOptions(records) {
  const current = docRecordSelect.value;
  docRecordSelect.innerHTML = '<option value="">Selecciona registro...</option>';
  records.forEach((r) => {
    const option = document.createElement('option');
    option.value = r.id;
    option.textContent = `#${r.id} - ${r.referencia} | ${r.naviera} | ${r.bl}`;
    docRecordSelect.appendChild(option);
  });
  if (current) docRecordSelect.value = current;
}

async function loadDocumentConfig() {
  const res = await fetch('/api/document-config');
  if (!res.ok) return;
  const data = await res.json();
  bankSelect.innerHTML = '<option value="">Selecciona banco...</option>';
  (data.banks || []).forEach((bank) => {
    const option = document.createElement('option');
    option.value = bank;
    option.textContent = bank;
    bankSelect.appendChild(option);
  });
}

function isOverdue(fecha) {
  if (!fecha) return false;
  const today = new Date();
  const date = new Date(`${fecha}T00:00:00`);
  today.setHours(0, 0, 0, 0);
  return date < today;
}

function renderPendingSection(records) {
  const pending = records.filter((r) => isOverdue(r.fecha_recuperacion) && r.estatus !== 'Pagado');
  pendingCount.textContent = String(pending.length);

  if (!pending.length) {
    pendingList.innerHTML = '<p class="muted">Sin pendientes por ahora.</p>';
    return;
  }

  pendingList.innerHTML = pending
    .slice(0, 10)
    .map(
      (p) => `
        <div class="pending-item">
          <strong>${p.referencia}</strong> — ${p.naviera} / ${p.bl}
          <span>Vencido: ${p.fecha_recuperacion}</span>
        </div>
      `,
    )
    .join('');
}

function resetForm() {
  recordForm.reset();
  recordIdInput.value = '';
  formTitle.textContent = 'Agregar registro';
  cancelEditBtn.classList.add('hidden');
}

async function submitRecord(event) {
  event.preventDefault();
  const payload = {
    referencia: document.getElementById('referencia').value,
    naviera: document.getElementById('naviera').value,
    bl: document.getElementById('bl').value,
    total: document.getElementById('total').value,
    fecha_recuperacion: document.getElementById('fecha_recuperacion').value,
    estatus: document.getElementById('estatus').value,
  };

  const id = recordIdInput.value;
  const method = id ? 'PUT' : 'POST';
  const url = id ? `/api/records/${id}` : '/api/records';

  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const data = await res.json();
    alert(data.error || 'Error al guardar');
    return;
  }

  resetForm();
  loadRecords();
}

async function deleteRecord(id) {
  if (!confirm('¿Seguro que deseas eliminar este registro?')) return;
  const res = await fetch(`/api/records/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    alert('No se pudo eliminar');
    return;
  }
  loadRecords();
}

async function startEdit(id) {
  const res = await fetch('/api/records');
  const records = await res.json();
  const record = records.find((r) => String(r.id) === String(id));
  if (!record) return;

  recordIdInput.value = record.id;
  document.getElementById('referencia').value = record.referencia;
  document.getElementById('naviera').value = record.naviera;
  document.getElementById('bl').value = record.bl;
  document.getElementById('total').value = record.total;
  document.getElementById('fecha_recuperacion').value = record.fecha_recuperacion;
  document.getElementById('estatus').value = record.estatus;

  formTitle.textContent = `Editar registro #${record.id}`;
  cancelEditBtn.classList.remove('hidden');
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.textContent = '';

  const payload = {
    username: document.getElementById('username').value,
    password: document.getElementById('password').value,
  };

  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    loginError.textContent = 'No se pudo iniciar sesión';
    return;
  }

  const data = await res.json();
  setSession(data.user);
  showApp(data.user);
});

logoutBtn.addEventListener('click', () => {
  clearSession();
  showLogin();
});

recordForm.addEventListener('submit', submitRecord);
cancelEditBtn.addEventListener('click', resetForm);
filterNavieraInput.addEventListener('input', loadRecords);

recordsTableBody.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const id = target.dataset.id;
  const action = target.dataset.action;
  if (!id || !action) return;
  if (action === 'edit') startEdit(id);
  if (action === 'delete') deleteRecord(id);
});

importBtn.addEventListener('click', async () => {
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    alert('Selecciona un archivo CSV o XLSX.');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch('/api/import', {
    method: 'POST',
    body: formData,
  });

  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'No se pudo importar el archivo');
    return;
  }

  if (data.duplicates && data.duplicates.length > 0) {
    const preview = data.duplicates
      .slice(0, 5)
      .map((d) => `${d.referencia} | ${d.naviera} | ${d.bl}`)
      .join('\n');
    alert(
      `Importación completada.\nInsertados: ${data.inserted}\nDuplicados detectados: ${data.duplicates.length}\n\nEjemplos:\n${preview}`,
    );
  } else {
    alert(`Importación completada. Insertados: ${data.inserted}. Sin duplicados.`);
  }

  fileInput.value = '';
  loadRecords();
});

async function confirmPayment(recordId, concepto) {
  const res = await fetch('/api/payments/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id: recordId, concepto }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'No se pudo confirmar el pago');
    return;
  }
  alert('Pago confirmado manualmente.');
  loadRecords();
}

validatePaymentsBtn.addEventListener('click', async () => {
  const file = paymentsFileInput.files && paymentsFileInput.files[0];
  if (!file) {
    alert('Selecciona un archivo Excel (.xlsx) de ingresos.');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch('/api/payments/validate', {
    method: 'POST',
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'No se pudo validar el archivo de ingresos');
    return;
  }

  const suggestions = data.suggestions || [];
  if (!suggestions.length) {
    paymentSuggestions.innerHTML = '<p class="muted">No se encontraron coincidencias sugeridas.</p>';
    return;
  }

  paymentSuggestions.innerHTML = suggestions
    .map((s, idx) => {
      const items = s.matches
        .slice(0, 5)
        .map(
          (m) => `
            <div class="payment-match-row">
              <span>#${m.id} - ${m.referencia} | ${m.naviera} | BL: ${m.bl} | ${m.estatus}</span>
              <button type="button" data-action="confirm-payment" data-id="${m.id}" data-concept-index="${idx}">Confirmar pago</button>
            </div>
          `,
        )
        .join('');
      return `
        <div class="pending-item payment-suggestion" data-concept="${encodeURIComponent(s.concepto)}">
          <strong>Concepto:</strong> ${s.concepto}
          <div>${items}</div>
        </div>
      `;
    })
    .join('');
});

paymentSuggestions.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.dataset.action !== 'confirm-payment') return;
  const id = target.dataset.id;
  const wrapper = target.closest('.payment-suggestion');
  const concepto = wrapper ? decodeURIComponent(wrapper.dataset.concept || '') : '';
  if (!id) return;
  confirmPayment(id, concepto);
});

generateDocBtn.addEventListener('click', async () => {
  const recordId = docRecordSelect.value;
  const bank = bankSelect.value;
  const bankCoverFile = bankCoverInput.files && bankCoverInput.files[0];
  const fiscalFile = fiscalFileInput.files && fiscalFileInput.files[0];
  const emailFile = emailCaptureInput.files && emailCaptureInput.files[0];

  if (!recordId) {
    alert('Selecciona un registro para generar documento.');
    return;
  }
  if (!bank) {
    alert('Selecciona un banco.');
    return;
  }
  const formData = new FormData();
  formData.append('record_id', recordId);
  formData.append('bank', bank);
  if (bankCoverFile) formData.append('bank_cover_file', bankCoverFile);
  if (fiscalFile) formData.append('fiscal_file', fiscalFile);
  if (emailFile) formData.append('email_capture', emailFile);

  const res = await fetch('/api/documents/generate', {
    method: 'POST',
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'No se pudo generar el documento');
    return;
  }
  alert('PDF unificado generado correctamente.');
  loadRecords();
});

const existing = getSession();
if (existing) {
  showApp(existing);
}
loadDocumentConfig();
