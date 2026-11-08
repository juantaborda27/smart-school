"""
API de lecturas de sensores de flujo de agua.

Recibe lecturas enviadas por dispositivos ESP32 mediante HTTP POST
y las almacena en MongoDB.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import PyMongoError

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "agua")
COLLECTION = os.getenv("COLLECTION", "lecturas")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api-agua")


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------

class LecturaSensor(BaseModel):
    """Lectura enviada por un sensor de flujo de agua."""

    sensor_id: str = Field(..., min_length=1, examples=["SENSOR_01"])
    ubicacion: str = Field(..., min_length=1, examples=["Zona Polivalente"])
    bloque: int = Field(..., ge=0, examples=[3])
    fecha_hora: datetime = Field(..., examples=["2026-10-26T08:52:00-05:00"])
    caudal_l_min: float = Field(..., ge=0, examples=[0.0])
    litros_consumidos_intervalo: float = Field(..., ge=0, examples=[0.0])
    litros_acumulados_dia: float = Field(..., ge=0, examples=[75.172])
    estado: Literal["con_flujo", "sin_flujo"]
    tipo_evento: Literal["uso", "sin_uso", "posible_fuga"]
    es_anomalia: bool
    franja_horaria: Literal["clases", "descanso", "almuerzo", "fuera_de_horario"]
    dato_sintetico: bool = False


class RespuestaCreacion(BaseModel):
    id: str


# ---------------------------------------------------------------------------
# Ciclo de vida de la aplicación
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not MONGO_URI:
        raise RuntimeError("La variable de entorno MONGO_URI no está configurada")

    # tz_aware=True para que las fechas leídas de Mongo incluyan zona horaria (UTC)
    cliente = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
    app.state.cliente = cliente
    app.state.coleccion = cliente[DB_NAME][COLLECTION]

    try:
        await app.state.coleccion.create_index(
            [("sensor_id", ASCENDING), ("fecha_hora", DESCENDING)],
            name="sensor_fecha_idx",
        )
        logger.info("Índice (sensor_id, fecha_hora) verificado en %s.%s", DB_NAME, COLLECTION)
    except PyMongoError as exc:
        # No se detiene la API: /health reportará el problema de conexión
        logger.error("No se pudo crear el índice en MongoDB: %s", exc)

    yield

    cliente.close()
    logger.info("Conexión con MongoDB cerrada")


app = FastAPI(
    title="API Agua",
    description="Recepción y consulta de lecturas de sensores de flujo de agua.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS básico: permite cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Manejo de errores
# ---------------------------------------------------------------------------

def jsonable_errores(exc: RequestValidationError) -> list[dict]:
    """Simplifica los errores de validación para la respuesta."""
    return [
        {"campo": ".".join(str(p) for p in err.get("loc", [])), "mensaje": err.get("msg")}
        for err in exc.errors()
    ]


@app.exception_handler(RequestValidationError)
async def manejar_error_validacion(request: Request, exc: RequestValidationError):
    logger.warning("Datos inválidos en %s %s: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": "Datos inválidos", "errores": jsonable_errores(exc)},
    )


@app.exception_handler(PyMongoError)
async def manejar_error_mongo(request: Request, exc: PyMongoError):
    logger.error("Error de MongoDB en %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Base de datos no disponible"},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/api/lecturas",
    status_code=status.HTTP_201_CREATED,
    response_model=RespuestaCreacion,
)
async def crear_lectura(lectura: LecturaSensor, request: Request):
    """Guarda una nueva lectura de sensor."""
    resultado = await request.app.state.coleccion.insert_one(lectura.model_dump())
    logger.info("Lectura guardada: sensor=%s id=%s", lectura.sensor_id, resultado.inserted_id)
    return {"id": str(resultado.inserted_id)}


@app.get("/api/lecturas", response_model=list[LecturaSensor])
async def listar_lecturas(
    request: Request,
    sensor_id: Optional[str] = Query(default=None, description="Filtrar por sensor"),
    bloque: Optional[int] = Query(default=None, ge=0, description="Filtrar por bloque"),
    es_anomalia: Optional[bool] = Query(default=None, description="Filtrar por anomalía"),
    limite: int = Query(default=50, ge=1, le=500, description="Cantidad máxima de resultados"),
):
    """Lista las últimas lecturas ordenadas por fecha_hora descendente."""
    filtro: dict = {}
    if sensor_id is not None:
        filtro["sensor_id"] = sensor_id
    if bloque is not None:
        filtro["bloque"] = bloque
    if es_anomalia is not None:
        filtro["es_anomalia"] = es_anomalia

    cursor = (
        request.app.state.coleccion.find(filtro, {"_id": 0})
        .sort("fecha_hora", DESCENDING)
        .limit(limite)
    )
    return await cursor.to_list(length=limite)


@app.get("/health")
async def health(request: Request):
    """Verifica que la API esté viva y que MongoDB responda."""
    try:
        await request.app.state.cliente.admin.command("ping")
    except Exception as exc:  # cualquier fallo de conexión se reporta como 503
        logger.error("Health check fallido: MongoDB no responde (%s)", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "mongo": "desconectado"},
        )
    return {"status": "ok", "mongo": "conectado"}