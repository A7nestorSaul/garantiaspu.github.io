const authUser = JSON.parse(localStorage.getItem('authUser') || 'null');
if (!authUser) {
  window.location.href = '/login.html';
}

document.getElementById('welcome-user').textContent = ` | Usuario: ${authUser.username}`;

document.getElementById('logout-btn').addEventListener('click', () => {
  localStorage.removeItem('authUser');
  window.location.href = '/login.html';
});

const form = document.getElementById('record-form');
const body = document.getElementById('records-body');
const message = document.getElementById('records-message');
const pendingList = document.getElementById('pending-list');
const paymentsUpload = document.getElementById('payments-upload');
const paymentSuggestions = document.getElementById('payment-suggestions');
const templateForm = document.getElementById('template-form');
const templateName = document.getElementById('template-name');
const templateContent = document.getElementById('template-content');
const docRecordSelect = document.getElementById('doc-record-select');
const docTemplateSelect = document.getElementById('doc-template-select');
const generateDocBtn = document.getElementById('generate-doc-btn');
const documentsList = document.getElementById('documents-list');
const reminderBar = document.getElementById('reminder-bar');
const filterInput = document.getElementById('filter-naviera');
const uploadInput = document.getElementById('file-upload');
const cancelBtn = document.getElementById('cancel-edit');

const fields = {
  id: document.getElementById('record-id'),
  referencia: document.getElementById('referencia'),
  naviera: document.getElementById('naviera'),
  bl: document.getElementById('bl'),
  total: document.getElementById('total'),
  fecha_recuperacion: document.getElementById('fecha_recuperacion'),
  estatus: document.getElementById('estatus')
};

function statusClass(estatus) {
  if (estatus === 'Pagado') return 'status-paid';
  if (estatus === 'Recuperado') return 'status-recovered';
  if (estatus === 'En proceso') return 'status-progress';
  return 'status-pending';
}

function resetForm() {
  form.reset();
  fields.id.value = '';
  document.getElementById('save-btn').textContent = 'Guardar registro';
}

function setMessage(text) {
  message.textContent = text;
  setTimeout(() => {
    message.textContent = '';
  }, 2500);
}

function renderRows(records) {
  if (!records.length) {
    body.innerHTML = '<tr><td colspan="7">No hay registros.</td></tr>';
    return;
  }

  body.innerHTML = records.map((record) => `
    <tr class="${record.is_overdue_pending ? 'row-overdue' : ''}">
      <td>${record.referencia}</td>
      <td>${record.naviera}</td>
      <td>${record.bl}</td>
      <td>$${Number(record.total).toFixed(2)}</td>
      <td>${record.fecha_recuperacion}</td>
      <td>
        <span class="status ${statusClass(record.estatus)}">${record.estatus}</span>
        ${record.is_overdue_pending ? '<span class="overdue-pill">Vencido</span>' : ''}
      </td>
      <td>
        <button data-action="edit" data-id="${record.id}">Editar</button>
        <button data-action="delete" data-id="${record.id}" class="btn-danger">Eliminar</button>
      </td>
    </tr>
  `).join('');
}

async function loadRecords() {
  try {
    const naviera = filterInput.value.trim();
    const query = naviera ? `?naviera=${encodeURIComponent(naviera)}` : '';

    const [tableResponse, fullResponse] = await Promise.all([
      fetch(`/api/records${query}`),
      fetch('/api/records')
    ]);
    const tableData = await tableResponse.json();
    const allData = await fullResponse.json();
    renderRows(tableData);
    renderPendingSection(allData);
    renderDocRecords(allData);
  } catch (_error) {
    setMessage('No se pudieron cargar los registros.');
  }
}

function renderPendingSection(records) {
  const pendingRecords = records.filter((record) => record.is_overdue_pending);

  if (!pendingRecords.length) {
    pendingList.innerHTML = '<p class="message">No hay registros pendientes por vencimiento.</p>';
    return;
  }

  pendingList.innerHTML = `
    <ul class="pending-items">
      ${pendingRecords.map((record) => `
        <li>
          <strong>${record.referencia}</strong> — ${record.naviera} / ${record.bl}
          <span class="pending-date">Fecha: ${record.fecha_recuperacion}</span>
        </li>
      `).join('')}
    </ul>
  `;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = {
    referencia: fields.referencia.value.trim(),
    naviera: fields.naviera.value.trim(),
    bl: fields.bl.value.trim(),
    total: Number(fields.total.value),
    fecha_recuperacion: fields.fecha_recuperacion.value,
    estatus: fields.estatus.value
  };

  const id = fields.id.value;
  const method = id ? 'PUT' : 'POST';
  const endpoint = id ? `/api/records/${id}` : '/api/records';

  const response = await fetch(endpoint, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    setMessage(data.message || 'No se pudo guardar el registro.');
    return;
  }

  resetForm();
  await loadRecords();
  setMessage(id ? 'Registro actualizado.' : 'Registro creado.');
});

cancelBtn.addEventListener('click', resetForm);

filterInput.addEventListener('input', loadRecords);
uploadInput.addEventListener('change', async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;

  try {
    const parsedRows = await parseFile(file);
    if (!parsedRows.length) {
      setMessage('El archivo no contiene filas válidas para importar.');
      uploadInput.value = '';
      return;
    }

    const response = await fetch('/api/records/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ records: parsedRows })
    });
    const result = await response.json();

    if (!response.ok) {
      setMessage(result.message || 'No se pudo procesar la carga del archivo.');
      uploadInput.value = '';
      return;
    }

    await loadRecords();
    const { inserted, duplicates, errors } = result.summary;
    setMessage(`Importación completada: ${inserted} insertados.`);

    if (duplicates > 0) {
      window.alert(`Se detectaron ${duplicates} duplicados por BL/Naviera/Referencia y no se importaron.`);
    }
    if (errors > 0) {
      window.alert(`Se detectaron ${errors} filas con formato inválido.`);
    }
  } catch (_error) {
    setMessage('No se pudo leer el archivo seleccionado.');
  } finally {
    uploadInput.value = '';
  }
});

paymentsUpload.addEventListener('change', async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;

  try {
    const concepts = await parseIncomeFile(file);
    if (!concepts.length) {
      setMessage('No se encontró la columna "concepto" o no tiene datos.');
      paymentsUpload.value = '';
      return;
    }

    const response = await fetch('/api/payments/suggestions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concepts })
    });
    const data = await response.json();

    if (!response.ok) {
      setMessage(data.message || 'No se pudo procesar sugerencias de pago.');
      paymentsUpload.value = '';
      return;
    }

    await renderPaymentSuggestions(data.suggestions || []);
  } catch (_error) {
    setMessage('No se pudo leer el archivo de ingresos.');
  } finally {
    paymentsUpload.value = '';
  }
});

templateForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = templateName.value.trim();
  const content = templateContent.value.trim();
  if (!name || !content) return;

  const response = await fetch('/api/documents/templates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content })
  });
  const data = await response.json();
  if (!response.ok) {
    setMessage(data.message || 'No se pudo guardar la plantilla.');
    return;
  }

  templateForm.reset();
  setMessage('Plantilla guardada.');
  await loadDocumentTemplates();
});

generateDocBtn.addEventListener('click', async () => {
  const recordId = Number(docRecordSelect.value);
  const templateId = Number(docTemplateSelect.value);
  if (!recordId || !templateId) {
    window.alert('Selecciona registro y plantilla.');
    return;
  }

  const response = await fetch('/api/documents/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id: recordId, template_id: templateId })
  });
  const data = await response.json();
  if (!response.ok) {
    setMessage(data.message || 'No se pudo generar el documento.');
    return;
  }

  setMessage('PDF generado y guardado.');
  await loadGeneratedDocuments();
});

body.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;

  const { action, id } = button.dataset;
  if (action === 'edit') {
    const row = button.closest('tr');
    fields.id.value = id;
    fields.referencia.value = row.children[0].textContent;
    fields.naviera.value = row.children[1].textContent;
    fields.bl.value = row.children[2].textContent;
    fields.total.value = Number(row.children[3].textContent.replace('$', '')).toFixed(2);
    fields.fecha_recuperacion.value = row.children[4].textContent;
    const statusText = row.querySelector('.status')?.textContent?.trim() || 'Pendiente';
    fields.estatus.value = statusText;
    document.getElementById('save-btn').textContent = 'Actualizar registro';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (action === 'delete') {
    const confirmed = window.confirm('¿Seguro que deseas eliminar este registro?');
    if (!confirmed) return;

    const response = await fetch(`/api/records/${id}`, { method: 'DELETE' });
    if (!response.ok) {
      setMessage('No se pudo eliminar el registro.');
      return;
    }

    await loadRecords();
    setMessage('Registro eliminado.');
  }
});

loadRecords();
loadDocumentTemplates();
loadGeneratedDocuments();
loadReminders();
setInterval(loadReminders, 60000);
paymentSuggestions.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-confirm-payment]');
  if (!button) return;

  const row = button.closest('.payment-row');
  const select = row.querySelector('select');
  const concepto = row.querySelector('[data-concepto]').textContent;
  const recordId = Number(select.value);

  if (!recordId) {
    window.alert('Selecciona un registro para confirmar.');
    return;
  }

  const response = await fetch('/api/payments/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id: recordId, concepto })
  });
  const data = await response.json();

  if (!response.ok) {
    setMessage(data.message || 'No se pudo confirmar el pago.');
    return;
  }

  setMessage('Pago confirmado y registro actualizado a Pagado.');
  row.remove();
  await loadRecords();
});

function normalizeRecord(raw) {
  const lowered = {};
  Object.keys(raw || {}).forEach((key) => {
    lowered[key.trim().toLowerCase()] = raw[key];
  });

  const referencia = String(lowered.referencia ?? lowered.reference ?? '').trim();
  const naviera = String(lowered.naviera ?? lowered.shipping ?? '').trim();
  const bl = String(lowered.bl ?? lowered['b/l'] ?? '').trim();
  const total = Number(lowered.total ?? lowered.monto ?? 0);
  const fecha_recuperacion = String(
    lowered.fecha_recuperacion ??
    lowered['fecha de recuperación'] ??
    lowered.fecha ??
    ''
  ).trim();
  const estatus = String(lowered.estatus ?? 'Pendiente').trim() || 'Pendiente';

  if (!referencia || !naviera || !bl || !fecha_recuperacion || Number.isNaN(total)) {
    return null;
  }

  return {
    referencia,
    naviera,
    bl,
    total,
    fecha_recuperacion,
    estatus
  };
}

function renderDocRecords(records) {
  if (!records.length) {
    docRecordSelect.innerHTML = '<option value="">Sin registros</option>';
    return;
  }

  docRecordSelect.innerHTML = `
    <option value="">Selecciona registro</option>
    ${records.map((record) => `<option value="${record.id}">${record.referencia} | ${record.bl} | ${record.naviera}</option>`).join('')}
  `;
}

async function loadDocumentTemplates() {
  try {
    const response = await fetch('/api/documents/templates');
    const templates = await response.json();
    if (!templates.length) {
      docTemplateSelect.innerHTML = '<option value="">Sin plantillas</option>';
      return;
    }

    docTemplateSelect.innerHTML = `
      <option value="">Selecciona plantilla</option>
      ${templates.map((template) => `<option value="${template.id}">${template.name}</option>`).join('')}
    `;
  } catch (_error) {
    docTemplateSelect.innerHTML = '<option value="">Error cargando plantillas</option>';
  }
}

async function loadGeneratedDocuments() {
  try {
    const response = await fetch('/api/documents');
    const docs = await response.json();

    if (!docs.length) {
      documentsList.innerHTML = '<p class="message">Aún no hay documentos generados.</p>';
      return;
    }

    documentsList.innerHTML = `
      <ul class="doc-items">
        ${docs.map((doc) => `
          <li>
            ${doc.template_name} — ${doc.referencia} (${doc.bl})
            <a href="/files/${doc.filename}" target="_blank" rel="noopener">Ver PDF</a>
          </li>
        `).join('')}
      </ul>
    `;
  } catch (_error) {
    documentsList.innerHTML = '<p class="message">No se pudo cargar la lista de documentos.</p>';
  }
}

async function loadReminders() {
  try {
    const response = await fetch('/api/reminders');
    const reminders = await response.json();
    const overdue = reminders.overdue_pending_count || 0;
    const dueSoon = reminders.due_soon_count || 0;

    if (!overdue && !dueSoon) {
      reminderBar.textContent = 'Sin recordatorios pendientes por ahora.';
      reminderBar.className = 'reminder-bar ok';
      return;
    }

    reminderBar.textContent = `Recordatorios: ${overdue} vencidos pendientes y ${dueSoon} próximos a vencer.`;
    reminderBar.className = 'reminder-bar warning';
  } catch (_error) {
    reminderBar.textContent = 'No se pudieron cargar los recordatorios.';
    reminderBar.className = 'reminder-bar error';
  }
}

function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) return [];

  const delimiter = lines[0].includes(';') ? ';' : ',';
  const headers = lines[0].split(delimiter).map((header) => header.trim());
  const rows = [];

  for (let i = 1; i < lines.length; i += 1) {
    const values = lines[i].split(delimiter);
    const row = {};
    headers.forEach((header, idx) => {
      row[header] = values[idx] ?? '';
    });
    rows.push(row);
  }

  return rows;
}

async function parseFile(file) {
  const extension = file.name.split('.').pop().toLowerCase();
  const isExcel = extension === 'xlsx' || extension === 'xls';

  if (isExcel) {
    const buffer = await file.arrayBuffer();
    const workbook = XLSX.read(buffer, { type: 'array' });
    const firstSheetName = workbook.SheetNames[0];
    const worksheet = workbook.Sheets[firstSheetName];
    const rawRows = XLSX.utils.sheet_to_json(worksheet, { defval: '' });
    return rawRows.map(normalizeRecord).filter(Boolean);
  }

  const text = await file.text();
  const rawRows = parseCsv(text);
  return rawRows.map(normalizeRecord).filter(Boolean);
}

async function parseIncomeFile(file) {
  const buffer = await file.arrayBuffer();
  const workbook = XLSX.read(buffer, { type: 'array' });
  const firstSheetName = workbook.SheetNames[0];
  const worksheet = workbook.Sheets[firstSheetName];
  const rawRows = XLSX.utils.sheet_to_json(worksheet, { defval: '' });

  const concepts = rawRows
    .map((row) => {
      const lowered = {};
      Object.keys(row || {}).forEach((key) => {
        lowered[key.trim().toLowerCase()] = row[key];
      });
      return String(lowered.concepto ?? '').trim();
    })
    .filter(Boolean);

  return [...new Set(concepts)];
}

async function renderPaymentSuggestions(suggestions) {
  const recordsResponse = await fetch('/api/records');
  const allRecords = await recordsResponse.json();

  if (!suggestions.length) {
    paymentSuggestions.innerHTML = '<p class="message">No hay conceptos para validar.</p>';
    return;
  }

  paymentSuggestions.innerHTML = suggestions.map((item) => {
    const options = item.matches.length
      ? item.matches.map((match) => (
        `<option value="${match.record_id}">${match.bl} | ${match.naviera} | ${match.referencia}</option>`
      )).join('')
      : '';

    const manualOptions = allRecords.map((record) => (
      `<option value="${record.id}">${record.bl} | ${record.naviera} | ${record.referencia}</option>`
    )).join('');

    return `
      <div class="payment-row">
        <div><strong>Concepto:</strong> <span data-concepto>${item.concepto}</span></div>
        <div class="message">
          ${item.matches.length ? `Sugerencias encontradas: ${item.matches.length}` : 'Sin sugerencias automáticas, selecciona manualmente.'}
        </div>
        <select>
          <option value="">Selecciona una coincidencia</option>
          ${options}
          <option value="">──────────</option>
          ${manualOptions}
        </select>
        <button type="button" data-confirm-payment="1">Confirmar pago</button>
      </div>
    `;
  }).join('');
}
