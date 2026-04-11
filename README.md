# Sistema de Garantías - Fase 1

Aplicación web full-stack base construida por módulos (fase 1).

## Stack usado
- **Backend:** Python (servidor HTTP nativo) + API REST simple
- **Base de datos:** SQLite (`app.db`)
- **Frontend:** HTML + CSS + JavaScript (sin frameworks)

## Funcionalidades implementadas (Fase 1)
- Login básico simulado.
- Dashboard con barra superior y navegación por pestañas.
- Tabla principal de registros con:
  - Referencia
  - Naviera
  - BL
  - Total
  - Fecha de recuperación
  - Estatus (con colores)
- CRUD completo de registros:
  - Agregar
  - Editar
  - Eliminar
- Filtro por naviera.
- Carga de archivo **CSV/XLSX** para importar registros.
- Detección de duplicados por combinación: **BL + Naviera + Referencia**.
- Seguimiento automático: si la fecha de recuperación ya pasó y no está en **Pagado**, se marca como **Pendiente**.
- Sección visual de **Pendientes** + indicador en tabla.
- Módulo de validación de pagos: carga de Excel de ingresos, lectura de columna `concepto`, sugerencias por coincidencia flexible con BL y confirmación manual.
- Módulo de generación documental: plantillas dinámicas por naviera, autollenado por registro, generación de PDF unificado y descarga posterior.
  - Nota: para unión PDF real se requiere la librería `pypdf` instalada en el entorno.
  - Control de vigencias: cada documento guarda fecha de carga y expiración (3 meses), bloqueando generación si está vencido.

## Estructura

```text
/workspace/garantias
├── server.py
├── app.db                 # se crea automáticamente al ejecutar
├── public
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── README.md
```

## Ejecutar

1. Ve al directorio del proyecto:
   ```bash
   cd /workspace/garantias
   ```
2. Inicia el servidor:
   ```bash
   python3 server.py
   ```
3. Abre en navegador:
   ```
   http://localhost:8000
   ```

## Notas
- El login es simulado: cualquier usuario/contraseña no vacíos permite entrar.
- Los datos se persisten en SQLite (`app.db`).
