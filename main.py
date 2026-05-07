from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# Inicializar Firebase
firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')
if firebase_credentials:
    cred_dict = json.loads(firebase_credentials)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate('serviceAccountKey.json')

firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI(title="Monitor Hipertensión API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modelos ──────────────────────────────────────────────

class SesionModel(BaseModel):
    pacienteId:  str
    nombre:      str
    grupo:       str

class LecturaModel(BaseModel):
    sesionId:   str
    bpm:        int
    spo2:       int
    ecg:        int

class CerrarSesionModel(BaseModel):
    sesionId:        str
    duracionHoras:   float
    falsosPositivos: int
    falsosNegativos: int

# ── Endpoints ────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "API Monitor Hipertensión funcionando"}

@app.post("/sesiones")
async def crear_sesion(sesion: SesionModel):
    try:
        ref = db.collection('sesiones').document()
        data = {
            'sesionId':    ref.id,
            'pacienteId':  sesion.pacienteId,
            'nombre':      sesion.nombre,
            'grupo':       sesion.grupo,
            'fechaInicio': datetime.now().isoformat(),
            'fechaFin':    None,
            'estado':      'activa',
            'indicadores': {}
        }
        ref.set(data)
        return {'sesionId': ref.id, 'status': 'creada'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/lecturas")
async def guardar_lectura(lectura: LecturaModel):
    try:
        es_hipertension = lectura.bpm > 100 or lectura.spo2 < 94
        db.collection('sesiones') \
          .document(lectura.sesionId) \
          .collection('lecturas') \
          .add({
              'bpm':            lectura.bpm,
              'spo2':           lectura.spo2,
              'ecg':            lectura.ecg,
              'esHipertension': es_hipertension,
              'timestamp':      datetime.now().isoformat(),
          })
        return {'status': 'guardado'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sesiones/cerrar")
async def cerrar_sesion(datos: CerrarSesionModel):
    try:
        lecturas = db.collection('sesiones') \
                     .document(datos.sesionId) \
                     .collection('lecturas') \
                     .stream()

        total     = 0
        episodios = 0
        suma_bpm  = 0
        suma_spo2 = 0
        perdidas  = 0

        for doc in lecturas:
            d = doc.to_dict()
            total     += 1
            suma_bpm  += d['bpm']
            suma_spo2 += d['spo2']
            if d['esHipertension']:
                episodios += 1
            if d['bpm'] == 0 and d['spo2'] == 0:
                perdidas += 1

        bpm_promedio  = round(suma_bpm  / total, 2) if total > 0 else 0
        spo2_promedio = round(suma_spo2 / total, 2) if total > 0 else 0
        peh = round((episodios / total * 100), 2) if total > 0 else 0
        tpd = round((perdidas  / total * 100), 2) if total > 0 else 0
        fpn = datos.falsosPositivos + datos.falsosNegativos

        indicadores = {
            'DB':             datos.duracionHoras,
            'TPD':            tpd,
            'PEH':            peh,
            'FPN':            fpn,
            'falsosPositivos': datos.falsosPositivos,
            'falsosNegativos': datos.falsosNegativos,
            'bpmPromedio':    bpm_promedio,
            'spo2Promedio':   spo2_promedio,
            'totalLecturas':  total,
        }

        db.collection('sesiones') \
          .document(datos.sesionId) \
          .update({
              'fechaFin':    datetime.now().isoformat(),
              'estado':      'cerrada',
              'indicadores': indicadores
          })

        return indicadores

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sesiones")
async def obtener_sesiones():
    try:
        docs = db.collection('sesiones').stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sesiones/{sesionId}")
async def obtener_sesion(sesionId: str):
    try:
        doc = db.collection('sesiones') \
                .document(sesionId) \
                .get()
        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail='Sesión no encontrada'
            )
        return doc.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sesiones/{sesionId}/lecturas")
async def obtener_lecturas(sesionId: str):
    try:
        docs = db.collection('sesiones') \
                 .document(sesionId) \
                 .collection('lecturas') \
                 .order_by('timestamp') \
                 .stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))