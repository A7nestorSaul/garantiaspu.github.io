# Sistema de Garantías — Fase 1

Aplicación web funcional (base del sistema) con:

- Login básico simulado.
- Dashboard principal con barra superior y navegación por pestañas.
- Tabla de registros con columnas: Referencia, Naviera, BL, Total, Fecha de recuperación, Estatus.
- CRUD completo: agregar, editar y eliminar registros.
- Filtro por naviera.
- Colores por estatus.
- Carga de archivos Excel/CSV para importar registros a la tabla existente.
- Detección de duplicados por BL, Naviera o Referencia durante la importación.
- Lógica de seguimiento: si la fecha de recuperación ya pasó y no está en estado **Pagado**, el registro se marca como **Pendiente**.
- Sección visual de **Pendientes** para registros vencidos y no pagados.
- Módulo de validación de pagos:
  - Subida de archivo de ingresos (Excel).
  - Lectura de columna `concepto`.
  - Coincidencias flexibles (parciales) entre `concepto` y `BL`.
  - Sugerencias y confirmación manual de pago.
- Generación de documentos:
  - Plantillas con formato `{{campo}}`.
  - Autollenado desde datos del registro.
  - Generación de PDF.
  - Guardado de documentos dentro del sistema.
- Barra de recordatorios (vencidos y próximos a vencer) con actualización automática.
- Backend en Python (sin frameworks externos).
- Base de datos SQLite.

## Estructura de carpetas

```bash
.
├── app.py
├── data/
│   └── garantias.db          # Se crea automáticamente
├── public/
│   ├── app.html
│   ├── app.js
│   ├── login.html
│   ├── login.js
│   └── styles.css
└── README.md
```

## Requisitos

- Python 3.10+ recomendado.

## Cómo ejecutar

1. Inicia el servidor:

```bash
python3 app.py
```

2. Abre en el navegador:

- `http://localhost:3000`

## Uso básico

1. Inicia sesión con cualquier usuario/contraseña (simulado).
2. En dashboard:
   - Llena el formulario y guarda registro.
   - Usa **Editar** para actualizar.
   - Usa **Eliminar** para borrar.
   - Escribe en el filtro de naviera para filtrar la tabla.
   - Carga un archivo `.csv`, `.xlsx` o `.xls` para importar registros.
   - Si hay duplicados por **BL**, **Naviera** o **Referencia**, se muestran alertas y esos registros se omiten.
   - En el módulo **Validación de pagos**, carga Excel de ingresos con columna `concepto`, revisa sugerencias y confirma manualmente el pago.
   - En **Generación de documentos**, guarda plantillas con `{{campo}}`, selecciona registro + plantilla y genera PDF.
   - Revisa la barra de recordatorios para ver vencidos pendientes y próximos a vencer.
3. Estatus disponibles:
   - Pendiente (rojo claro)
   - En proceso (amarillo)
   - Recuperado (verde)
   - Pagado (azul)

---

Esta entrega corresponde únicamente a la **FASE 1: Base del sistema**.
