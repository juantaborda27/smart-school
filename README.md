# API Agua

API en FastAPI que recibe lecturas de sensores de flujo de agua (enviadas por un ESP32 vía HTTP POST) y las guarda en MongoDB.

## Endpoints

| Método | Ruta             | Autenticación      | Descripción                                   |
|--------|------------------|--------------------|-----------------------------------------------|
| POST   | `/api/lecturas`  | Header `x-api-key` | Guarda una lectura. Responde `201` con `{"id": "..."}` |
| GET    | `/api/lecturas`  | No                 | Lista lecturas (filtros: `sensor_id`, `bloque`, `es_anomalia`, `limite`) |
| GET    | `/health`        | No                 | Estado de la API y de la conexión con MongoDB |

La documentación interactiva queda disponible en `/docs`.

### Valores permitidos

- `estado`: `con_flujo` | `sin_flujo`
- `tipo_evento`: `uso` | `sin_uso` | `posible_fuga`
- `franja_horaria`: `clases` | `descanso` | `almuerzo` | `fuera_de_horario`
- `bloque`, `caudal_l_min`, `litros_consumidos_intervalo`, `litros_acumulados_dia`: no negativos
- `dato_sintetico`: opcional, por defecto `false`

## Variables de entorno

| Variable     | Obligatoria | Por defecto | Descripción                               |
|--------------|-------------|-------------|-------------------------------------------|
| `MONGO_URI`  | Sí          | —           | Cadena de conexión a MongoDB              |
| `API_KEY`    | Sí          | —           | Clave que debe enviar el ESP32 en `x-api-key` |
| `DB_NAME`    | No          | `agua`      | Nombre de la base de datos                |
| `COLLECTION` | No          | `lecturas`  | Nombre de la colección                    |

## Correr en local

Requisitos: Python 3.10+ y una instancia de MongoDB (local o Atlas).

```bash
cd api-agua
python -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Crear el archivo .env a partir del ejemplo y completar los valores
cp .env.example .env

uvicorn main:app --reload --port 8000
```

### Con Docker

```bash
docker build -t api-agua .
docker run --env-file .env -p 8000:8000 api-agua
```

## Ejemplos con curl

### Enviar una lectura (POST)

```bash
curl -X POST http://localhost:8000/api/lecturas \
  -H "Content-Type: application/json" \
  -H "x-api-key: <tu-api-key>" \
  -d '{
    "sensor_id": "SENSOR_01",
    "ubicacion": "Zona Polivalente",
    "bloque": 3,
    "fecha_hora": "2026-10-26T08:52:00-05:00",
    "caudal_l_min": 0.0,
    "litros_consumidos_intervalo": 0.0,
    "litros_acumulados_dia": 75.172,
    "estado": "sin_flujo",
    "tipo_evento": "sin_uso",
    "es_anomalia": false,
    "franja_horaria": "clases",
    "dato_sintetico": false
  }'
```

Respuesta (`201`):

```json
{"id": "6720a1b2c3d4e5f601234567"}
```

Si el header `x-api-key` falta o no coincide, la respuesta es `401`. Si el cuerpo no es válido, la respuesta es `422` con el detalle de los campos.

### Consultar lecturas con filtros (GET)

```bash
curl "http://localhost:8000/api/lecturas?sensor_id=SENSOR_01&bloque=3&es_anomalia=false&limite=20"
```

### Health check

```bash
curl http://localhost:8000/health
```

Respuesta (`200`):

```json
{"status": "ok", "mongo": "conectado"}
```

Si MongoDB no responde, devuelve `503` con `{"status": "error", "mongo": "desconectado"}`.

> **Nota:** las fechas se almacenan en MongoDB en UTC. Al consultarlas, `fecha_hora` se devuelve en UTC (por ejemplo, `2026-10-26T13:52:00Z` para `08:52-05:00`).

## Despliegue en Render / Railway

Ambas plataformas detectan el `Dockerfile` automáticamente. El contenedor arranca con:

```
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Render

1. Crear un **Web Service** conectado al repositorio (entorno **Docker**).
2. En **Environment**, agregar `MONGO_URI`, `API_KEY` y, si se desea, `DB_NAME` y `COLLECTION`.
3. En **Settings → Health Check Path**, poner `/health`.

### Railway

1. Crear un proyecto desde el repositorio; Railway usará el `Dockerfile`.
2. En **Variables**, agregar `MONGO_URI`, `API_KEY` y, opcionalmente, `DB_NAME` y `COLLECTION`.
3. En **Settings → Deploy → Healthcheck Path**, poner `/health`.
4. En **Settings → Networking**, generar un dominio público.

La variable `PORT` la inyecta la plataforma; no es necesario definirla.

## MongoDB Atlas

Si usas MongoDB Atlas, en **Network Access** debes permitir la IP del servidor donde corre la API. Render y Railway no garantizan IPs de salida fijas en los planes básicos, por lo que normalmente se agrega `0.0.0.0/0` (cualquier IP). En ese caso usa un usuario de base de datos con contraseña robusta y solo los permisos necesarios.

Si `/health` devuelve `503` tras el despliegue, lo más probable es que la IP no esté permitida o que la `MONGO_URI` sea incorrecta.
