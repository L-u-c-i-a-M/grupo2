import json
import logging
import os
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import pymysql
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
APP_NAME = os.getenv('APP_NAME', 'OpsCenter')
TEAM_NAME = os.getenv('TEAM_NAME', 'Equipo LAB')
APP_ENV = os.getenv('APP_ENV', 'LAB')
APP_VERSION = os.getenv('APP_VERSION', '1.0.0')
APP_PORT = int(os.getenv('APP_PORT', '8101'))
DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_NAME = os.getenv('DB_NAME', 'opscenter')
DB_USER = os.getenv('DB_USER', 'opscenter')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
STARTED_AT = datetime.now(timezone.utc)

logger = logging.getLogger('opscenter')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
logger.handlers.clear(); logger.addHandler(handler); logger.propagate = False

METRICS = {'requests_total': 0, 'errors_total': 0, 'duration_ms_total': 0.0, 'by_status': {}}

CREATE_SQL = [
'''CREATE TABLE IF NOT EXISTS managed_services (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(120) NOT NULL,
 service_type VARCHAR(80) NOT NULL,
 description VARCHAR(255) NULL,
 operational_status VARCHAR(20) NOT NULL DEFAULT 'ONLINE',
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS incidents (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 title VARCHAR(160) NOT NULL,
 severity VARCHAR(20) NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
 description TEXT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 closed_at TIMESTAMP NULL DEFAULT NULL
)''',
'''CREATE TABLE IF NOT EXISTS operational_events (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 level VARCHAR(20) NOT NULL DEFAULT 'INFO',
 message VARCHAR(255) NOT NULL,
 source VARCHAR(80) NOT NULL DEFAULT 'system',
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)'''
]
SEED_SERVICES = [
 ('API Principal','API','Servicio HTTP principal de OpsCenter','ONLINE'),
 ('Base de Datos','DATABASE','Persistencia MySQL/MariaDB','ONLINE'),
 ('Health Endpoint','MONITORING','Verificación de estado del servicio','ONLINE')
]

def now_iso(): return datetime.now(timezone.utc).isoformat()
def log_event(level, event, **fields):
    payload = {'timestamp': now_iso(), 'level': level.upper(), 'service': APP_NAME, 'environment': APP_ENV, 'event': event, **fields}
    msg = json.dumps(payload, ensure_ascii=False, default=str)
    getattr(logger, 'error' if level.upper()=='ERROR' else 'warning' if level.upper() in {'WARN','WARNING'} else 'info')(msg)

def db_connection():
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME,
        connect_timeout=3, read_timeout=3, write_timeout=3, autocommit=True, cursorclass=pymysql.cursors.DictCursor)

def database_ok():
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 AS ok'); cur.fetchone()
        return True
    except Exception:
        return False

def initialize_database():
    with db_connection() as conn:
        with conn.cursor() as cur:
            for st in CREATE_SQL: cur.execute(st)
            cur.execute('SELECT COUNT(*) AS count FROM managed_services')
            if cur.fetchone()['count']==0:
                cur.executemany('INSERT INTO managed_services(name,service_type,description,operational_status) VALUES (%s,%s,%s,%s)', SEED_SERVICES)
            cur.execute('SELECT COUNT(*) AS count FROM operational_events')
            if cur.fetchone()['count']==0:
                cur.execute("INSERT INTO operational_events(level,message,source) VALUES ('INFO','OpsCenter inicializado correctamente','application')")

def try_initialize_database():
    for attempt in range(1,6):
        try:
            initialize_database(); log_event('INFO','database_initialized',attempt=attempt); return True
        except Exception as exc:
            log_event('WARNING','database_init_retry',attempt=attempt,error_type=type(exc).__name__)
            if attempt<5: time.sleep(1)
    log_event('ERROR','database_init_failed'); return False

def git_commit():
    try:
        return subprocess.check_output(['git','rev-parse','--short','HEAD'], cwd=PROJECT_ROOT, stderr=subprocess.DEVNULL, text=True, timeout=2).strip()
    except Exception: return 'unknown'

def query_all(sql, params=None):
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ()); return cur.fetchall()

def execute(sql, params=None):
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ()); return cur.lastrowid

def uptime_seconds(): return int((datetime.now(timezone.utc)-STARTED_AT).total_seconds())

@asynccontextmanager
async def lifespan(app):
    log_event('INFO','application_starting',port=APP_PORT,team=TEAM_NAME); try_initialize_database(); yield; log_event('INFO','application_stopping')

app = FastAPI(title='OpsCenter API', version=APP_VERSION, description='Centro de operaciones de laboratorio - Práctica Profesionalizante I', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=BASE_DIR/'static'), name='static')
templates = Jinja2Templates(directory=BASE_DIR/'templates')

@app.middleware('http')
async def observability_middleware(request, call_next):
    request_id=request.headers.get('X-Request-ID') or uuid.uuid4().hex[:12]; started=time.perf_counter(); METRICS['requests_total']+=1
    log_event('INFO','request_started',request_id=request_id,method=request.method,path=request.url.path)
    try:
        response=await call_next(request); status=response.status_code
    except Exception as exc:
        status=500; METRICS['errors_total']+=1; duration=round((time.perf_counter()-started)*1000,2); METRICS['duration_ms_total']+=duration
        METRICS['by_status'][str(status)]=METRICS['by_status'].get(str(status),0)+1
        log_event('ERROR','request_failed',request_id=request_id,method=request.method,path=request.url.path,status=status,duration_ms=duration,error_type=type(exc).__name__); raise
    duration=round((time.perf_counter()-started)*1000,2); METRICS['duration_ms_total']+=duration; METRICS['by_status'][str(status)]=METRICS['by_status'].get(str(status),0)+1
    if status>=500: METRICS['errors_total']+=1
    response.headers['X-Request-ID']=request_id
    log_event('INFO' if status<500 else 'ERROR','request_completed',request_id=request_id,method=request.method,path=request.url.path,status=status,duration_ms=duration)
    return response

@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request):
    db_ok=database_ok(); services=[]; incidents=[]; events=[]; open_incidents=0
    if db_ok:
        try:
            services=query_all('SELECT id,name,service_type,description,operational_status,created_at FROM managed_services ORDER BY id ASC')
            incidents=query_all('SELECT id,title,severity,status,description,created_at,closed_at FROM incidents ORDER BY created_at DESC LIMIT 8')
            events=query_all('SELECT id,level,message,source,created_at FROM operational_events ORDER BY created_at DESC LIMIT 10')
            open_incidents=sum(1 for x in incidents if x['status']=='OPEN')
        except Exception: db_ok=False
    return templates.TemplateResponse(request=request, name='index.html', context={
        'app_name':APP_NAME,'team_name':TEAM_NAME,'app_env':APP_ENV,'app_version':APP_VERSION,'git_commit':git_commit(),
        'database_ok':db_ok,'system_status':'HEALTHY' if db_ok else 'DEGRADED','services':services,'incidents':incidents,
        'events':events,'open_incidents':open_incidents,'uptime_seconds':uptime_seconds(),'app_port':APP_PORT})

@app.get('/live')
def live(): return {'status':'alive','service':APP_NAME,'environment':APP_ENV,'uptime_seconds':uptime_seconds()}
@app.get('/ready')
def ready():
    if database_ok(): return {'status':'ready','database':'connected','environment':APP_ENV}
    log_event('WARNING','readiness_failed',dependency='database'); return JSONResponse(status_code=503, content={'status':'not_ready','database':'unavailable','environment':APP_ENV})
@app.get('/health')
def health():
    ok=database_ok(); return JSONResponse(status_code=200 if ok else 503, content={'status':'ok' if ok else 'degraded','service':APP_NAME,'database':'connected' if ok else 'unavailable','environment':APP_ENV})
@app.get('/version')
def version(): return {'service':APP_NAME,'version':APP_VERSION,'commit':git_commit(),'environment':APP_ENV,'team':TEAM_NAME}
@app.get('/metrics-lite')
def metrics_lite():
    req=METRICS['requests_total']; avg=round(METRICS['duration_ms_total']/req,2) if req else 0.0
    return {'requests_total':req,'errors_total':METRICS['errors_total'],'average_duration_ms':avg,'by_status':METRICS['by_status'],'note':'Métricas didácticas en memoria; se reinician con el proceso.'}
@app.get('/api/status')
def api_status():
    ok=database_ok(); return {'system':'HEALTHY' if ok else 'DEGRADED','api':'ONLINE','database':'CONNECTED' if ok else 'UNAVAILABLE','environment':APP_ENV,'version':APP_VERSION,'commit':git_commit(),'uptime_seconds':uptime_seconds(),'timestamp':now_iso()}
@app.get('/api/services')
def api_services():
    if not database_ok(): raise HTTPException(status_code=503,detail='database_unavailable')
    return query_all('SELECT id,name,service_type,description,operational_status,created_at FROM managed_services ORDER BY id ASC')
@app.post('/api/services')
def create_service(name:str=Form(...), service_type:str=Form(...), description:str=Form('')):
    if not database_ok(): raise HTTPException(status_code=503,detail='database_unavailable')
    execute("INSERT INTO managed_services(name,service_type,description,operational_status) VALUES (%s,%s,%s,'ONLINE')",(name[:120],service_type[:80],description[:255]))
    execute("INSERT INTO operational_events(level,message,source) VALUES ('INFO',%s,'operator')",(f'Servicio registrado: {name[:120]}',)); return RedirectResponse('/',status_code=303)
@app.post('/api/incidents')
def create_incident(title:str=Form(...), severity:str=Form(...), description:str=Form('')):
    if not database_ok(): raise HTTPException(status_code=503,detail='database_unavailable')
    sev=severity.upper(); sev=sev if sev in {'LOW','MEDIUM','HIGH','CRITICAL'} else 'MEDIUM'
    iid=execute("INSERT INTO incidents(title,severity,status,description) VALUES (%s,%s,'OPEN',%s)",(title[:160],sev,description[:2000]))
    execute("INSERT INTO operational_events(level,message,source) VALUES ('WARNING',%s,'incident')",(f'INC-{iid:03d} abierto: {title[:120]}',)); return RedirectResponse('/',status_code=303)
@app.post('/api/incidents/{incident_id}/close')
def close_incident(incident_id:int):
    if not database_ok(): raise HTTPException(status_code=503,detail='database_unavailable')
    execute("UPDATE incidents SET status='CLOSED',closed_at=CURRENT_TIMESTAMP WHERE id=%s",(incident_id,))
    execute("INSERT INTO operational_events(level,message,source) VALUES ('INFO',%s,'incident')",(f'INC-{incident_id:03d} cerrado',)); return RedirectResponse('/',status_code=303)
@app.post('/api/events')
def create_event(message:str=Form(...), level:str=Form('INFO')):
    if not database_ok(): raise HTTPException(status_code=503,detail='database_unavailable')
    lvl=level.upper(); lvl=lvl if lvl in {'INFO','WARNING','ERROR'} else 'INFO'
    execute("INSERT INTO operational_events(level,message,source) VALUES (%s,%s,'operator')",(lvl,message[:255])); return RedirectResponse('/',status_code=303)
@app.get('/slow')
async def slow(seconds:float=Query(default=3.0,ge=0,le=10)):
    import asyncio; await asyncio.sleep(seconds); return {'status':'ok','delay_seconds':seconds}
@app.get('/fail')
def fail(): raise RuntimeError('simulated_failure')
