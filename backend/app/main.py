from __future__ import annotations

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import asyncio
import os
import threading
import uuid
from typing import Literal
from urllib.parse import urlparse
import sqlite3

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .config import AppPaths, PATHS, ProtectedPathError
from .database import DomainError
from .engine import ContinuityEngine, MemoryDeltaEngine, MemoryInitializationEngine
from .provider import DeepSeekProvider, ProviderPort
from .stage13 import (
    MailerPort,
    SmtpMailer,
    Stage13Service,
    Stage13Settings,
    UnavailableMailer,
    UsageGuardProvider,
    masked_email,
    normalize_email,
    provider_usage,
)
from .v2_database import V2Database

COOKIE = "scc_local_session"
MEMORY_INITIALIZATION_FAILURE_PHASES = {"provider_preflight","batch_planning","provider_request","post_response_decode","post_response_budget","post_response_validation","post_aggregation"}
MEMORY_INITIALIZATION_FIELDS = {"memory_type","subject","predicate","value","chapter_id","source_span_id"}
MEMORY_REPAIR_CODES = {"top_level_shape_invalid","candidate_collection_invalid","candidate_count_invalid","empty_candidates","candidate_fields_invalid","memory_type_invalid","required_field_type_invalid","required_field_blank","candidate_length_invalid","evidence_unresolvable"}
MEMORY_NORMALIZATION_KINDS = {"trimmed_string","memory_type_format","extra_fields_removed"}

def safe_repair_events(value:object)->list[dict]:
    if not isinstance(value,list):return []
    cleaned=[]
    for event in value:
        if not isinstance(event,dict):continue
        batch=event.get("batch_ordinal"); attempt=event.get("attempt"); reason=event.get("reason_code"); result=event.get("result")
        if not (isinstance(batch,int) and not isinstance(batch,bool) and batch>=1 and isinstance(attempt,int) and not isinstance(attempt,bool) and attempt>=1 and reason in MEMORY_REPAIR_CODES and result in {"pending","succeeded","failed","provider_failed"}):continue
        item={"batch_ordinal":batch,"attempt":attempt,"reason_code":reason,"result":result}
        batch_attempt=event.get("batch_attempt")
        if isinstance(batch_attempt,int) and not isinstance(batch_attempt,bool) and 1<=batch_attempt<=2:item["batch_attempt"]=batch_attempt
        if event.get("field") in MEMORY_INITIALIZATION_FIELDS:item["field"]=event["field"]
        ordinal=event.get("candidate_ordinal")
        if isinstance(ordinal,int) and not isinstance(ordinal,bool) and ordinal>=1:item["candidate_ordinal"]=ordinal
        if event.get("final_reason_code") in MEMORY_REPAIR_CODES:item["final_reason_code"]=event["final_reason_code"]
        cleaned.append(item)
    return cleaned

def safe_memory_initialization_failure_details(result:dict)->dict:
    """Allow only operational scalars; never expose request or Provider payload data."""
    details={}
    phase=result.get("failure_phase")
    if phase in MEMORY_INITIALIZATION_FAILURE_PHASES:details["failure_phase"]=phase
    ordinal=result.get("failed_batch_ordinal")
    if ordinal is None or (isinstance(ordinal,int) and not isinstance(ordinal,bool) and ordinal>=1):details["failed_batch_ordinal"]=ordinal
    total=result.get("total_batches")
    if isinstance(total,int) and not isinstance(total,bool) and total>=0:details["total_batches"]=total
    for field in ("input_tokens","output_tokens","latency_ms","schema_repair_attempts","validated_batches","staged_candidate_count","normalization_count"):
        value=result.get(field)
        if isinstance(value,int) and not isinstance(value,bool) and value>=0:details[field]=value
    if result.get("invalid_field") in MEMORY_INITIALIZATION_FIELDS:details["invalid_field"]=result["invalid_field"]
    invalid_ordinal=result.get("invalid_candidate_ordinal")
    if isinstance(invalid_ordinal,int) and not isinstance(invalid_ordinal,bool) and invalid_ordinal>=1:details["invalid_candidate_ordinal"]=invalid_ordinal
    details["repair_events"]=safe_repair_events(result.get("repair_events"))
    kinds=result.get("normalization_kinds")
    if isinstance(kinds,dict):details["normalization_kinds"]={key:value for key,value in kinds.items() if key in MEMORY_NORMALIZATION_KINDS and isinstance(value,int) and not isinstance(value,bool) and value>=1}
    details["cost_available"]=isinstance(result.get("cost_cny"),(int,float)) and not isinstance(result.get("cost_cny"),bool)
    return details

class Strict(BaseModel): model_config = ConfigDict(extra="forbid")
class Register(Strict): account_name:str; display_name:str; password:str; recovery_email:str|None=None
class Login(Strict): account_name:str; password:str
class RecoveryEmail(Strict): recovery_email:str
class RecoveryToken(Strict): token:str=Field(min_length=32,max_length=512)
class PasswordResetRequest(Strict): recovery_email:str
class PasswordResetConfirm(Strict): token:str=Field(min_length=32,max_length=512); password:str
class ProjectCreate(Strict): title:str; genre:str|None=None; summary:str|None=None
class ProjectPatch(Strict): base_metadata_revision:int=Field(ge=1); title:str|None=None; genre:str|None=None; summary:str|None=None; status:Literal['active','paused','completed','archived']|None=None; confirm_archive:bool|None=None
class EditContext(Strict): source_run_id:str; source_revision:int=Field(ge=1); issue_id:str
class DraftPatch(Strict): base_revision:int=Field(ge=1); body:str; title:str|None=None; edit_context:EditContext|None=None
class Check(Strict): draft_id:str; draft_revision:int=Field(ge=1); client_request_id:str|None=None
class RunAction(Strict): client_request_id:str|None=None
class Decision(Strict): run_id:str; source_revision:int=Field(ge=1); decision:Literal['accept_and_edit','keep_intentional','false_positive']; note:str|None=None; resulting_revision:int|None=None
class ChangeSet(Strict): run_id:str; source_run_revision:int=Field(ge=1); resolved_revision:int=Field(ge=1)
class EditedMemoryItem(Strict): item_id:str; memory_type:Literal['static_canon','dynamic_state','event_timeline','character_knowledge','open_thread']; subject:str; predicate:str; value:str
class Commit(Strict): confirm:bool|None=None; accepted_item_ids:list[str]; rejected_item_ids:list[str]; edited_items:list[EditedMemoryItem]=Field(default_factory=list); note:str|None=None
class Reset(Strict): confirm:bool|None=None; reason:Literal['fresh_start','demo_recovery']|None=None
class ImportCommit(Strict): confirm:bool|None=None; title:str; genre:str|None=None; summary:str|None=None; chapter_preview_ids:list[str]
class MemoryInitialization(Strict): source_revision:int=Field(ge=1)
class EditedMemoryCandidate(Strict): memory_type:Literal['static_canon','dynamic_state','event_timeline','character_knowledge','open_thread']; subject:str; predicate:str; value:str
class MemoryCandidateDecision(Strict): decision:Literal['accepted','rejected','edited']; after:EditedMemoryCandidate|None=None; evidence_span_id:str|None=None
class MemoryInitializationCommit(Strict): confirm:bool|None=None
class SourceChangePreview(Strict):
    mode:Literal['append']
    input_method:Literal['draft_complete','paste','file']
    base_source_revision:int=Field(ge=1)
    draft_id:str|None=None
    content:str|None=None
    title:str|None=None
    filename:str|None=None
class SourceChangeCommit(Strict): confirm:bool|None=None; content_sha256:str
class IncrementalReview(Strict): source_revision:int=Field(ge=2)
class MemoryDeltaCommit(Strict): confirm:bool|None=None
class OnboardingAction(Strict): confirm:bool
class TutorialProgressEvent(Strict):
    tutorial_version:Literal['1.2.0']
    project_id:str
    event:Literal['memory_source_opened','continuity_issue_located','evidence_opened','author_decision_recorded']

def create_app(paths:AppPaths=PATHS, provider:ProviderPort|None=None, executor=None, settings:Stage13Settings|None=None, mailer:MailerPort|None=None)->FastAPI:
    settings=settings or Stage13Settings.from_env()
    db=V2Database(paths)
    # Initialize eagerly too: ASGI unit clients do not necessarily enter the
    # lifespan context, while normal servers retain the same idempotent check.
    db.initialize()
    if mailer is None:
        mailer=SmtpMailer(settings) if settings.public_app_mode else UnavailableMailer()
    stage13=Stage13Service(db,settings,mailer)
    recovery_executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix="stage13-recovery")
    registration_lock=threading.Lock()
    guarded_provider=UsageGuardProvider(provider or DeepSeekProvider(),stage13)
    engine=ContinuityEngine(guarded_provider); memory_engine=MemoryInitializationEngine(engine.provider); delta_engine=MemoryDeltaEngine(engine.provider)
    @asynccontextmanager
    async def lifespan(_:FastAPI):
        db.initialize(); stage13.initialize(); stage13.cleanup_expired_visitors()
        async def periodic_cleanup():
            while True:
                await asyncio.sleep(settings.cleanup_interval_seconds)
                stage13.cleanup_expired_visitors()
        task=asyncio.create_task(periodic_cleanup())
        try: yield
        finally:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
            recovery_executor.shutdown(wait=True,cancel_futures=False)
    app=FastAPI(title='Story Continuity Copilot Web Demo',version='1.2.0',lifespan=lifespan)
    app.state.database=db; app.state.engine=engine; app.state.stage13=stage13; app.state.stage13_settings=settings; app.state.recovery_executor=recovery_executor
    def trusted_host(value:str)->bool:
        folded=value.casefold()
        if folded in settings.trusted_hosts:return True
        if settings.public_app_mode or settings.test_mode:return False
        try:return urlparse(f'http://{folded}').hostname in {'127.0.0.1','localhost'}
        except ValueError:return False
    def execute(project_id:str,run_id:str,user_id:str,reservation_id:str):
        try:
            if db.session_budget_exhausted(project_id): db.finish_run(project_id,run_id,{'status':'failed','error_code':'budget_guard_exceeded','retryable':True}); return
            if not db.advance_run(project_id,run_id,'preparing_draft'):return
            if not db.advance_run(project_id,run_id,'retrieving_confirmed_facts'):return
            data=db.run_input(project_id,run_id)
            if not db.advance_run(project_id,run_id,'comparing_evidence'):return
            with provider_usage(user_id,reservation_id): result=engine.execute(data)
            if result['status']=='completed' and not db.advance_run(project_id,run_id,'assembling_reviewable_results'):return
            db.finish_run(project_id,run_id,result)
        except Exception: db.finish_run(project_id,run_id,{'status':'failed','error_code':'internal_run_error','retryable':True})
    def execute_incremental(project_id:str,batch_id:str,user_id:str,reservation_id:str):
        try:
            if not db.advance_incremental_runs(project_id,batch_id,'running_continuity'):return
            continuity_input,delta_input=db.incremental_inputs(project_id,batch_id)
            with provider_usage(user_id,reservation_id): continuity=engine.execute(continuity_input)
            if continuity['status']!='completed':
                db.finish_incremental_runs(project_id,batch_id,continuity,{'status':'failed','error_code':'incremental_sibling_failed','retryable':True}); return
            if not db.advance_incremental_runs(project_id,batch_id,'running_memory_delta'):return
            with provider_usage(user_id,reservation_id): delta=delta_engine.execute(delta_input)
            db.finish_incremental_runs(project_id,batch_id,continuity,delta)
        except Exception:
            db.finish_incremental_runs(project_id,batch_id,{"status":"failed","error_code":"internal_run_error","retryable":True},{"status":"failed","error_code":"internal_run_error","retryable":True})
    @app.middleware('http')
    async def ids(request:Request,call_next):
        request.state.request_id='req_'+uuid.uuid4().hex
        host=request.headers.get('host','').casefold()
        if not trusted_host(host):
            response=JSONResponse(status_code=403,content={'error':{'code':'cross_site_request_rejected','message':'请求无法完成','retryable':False},'request_id':request.state.request_id})
        else:
            response=await call_next(request)
        response.headers['X-Request-Id']=request.state.request_id
        response.headers['Content-Security-Policy']="default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        if settings.public_app_mode: response.headers['Strict-Transport-Security']='max-age=63072000; includeSubDomains'
        return response
    def failure(request:Request,status:int,code:str,retryable:bool=False,details:dict|None=None):
        error={'code':code,'message':'请求无法完成','retryable':retryable}
        if details:error['details']=details
        return JSONResponse(status_code=status,content={'error':error,'request_id':getattr(request.state,'request_id',None)})
    @app.exception_handler(DomainError)
    async def domain(request:Request,exc:DomainError): return failure(request,exc.status,exc.code,exc.retryable,exc.details)
    @app.exception_handler(HTTPException)
    async def http(request:Request,exc:HTTPException): return failure(request,exc.status_code,str(exc.detail),exc.status_code in {429,502,503,504})
    @app.exception_handler(RequestValidationError)
    async def validation(request:Request,exc:RequestValidationError): return failure(request,400,'confirmation_required' if any('confirm' in x.get('loc',()) for x in exc.errors()) else 'invalid_request')
    @app.exception_handler(ProtectedPathError)
    async def protected(request:Request,exc:ProtectedPathError): return failure(request,503,'demo_state_unavailable',True)
    @app.exception_handler(sqlite3.Error)
    async def database_error(request:Request,exc:sqlite3.Error): return failure(request,503,getattr(request.state,'failure_code','state_unavailable'),True)
    def ok(request:Request,data:dict,status:int=200): return JSONResponse(status_code=status,content={'data':data,'request_id':request.state.request_id})
    def key(value:str|None):
        if not value: raise HTTPException(400,'missing_idempotency_key')
        try:return str(uuid.UUID(value))
        except (ValueError,TypeError):raise HTTPException(400,'invalid_idempotency_key') from None
    def parse_include(value:str|None):
        if value is None:return set()
        parts=value.split(','); result=set(parts)
        if len(parts)!=len(result) or not result<={'issues','evidence','metrics'} or ('evidence' in result and 'issues' not in result):raise HTTPException(400,'invalid_include')
        return result
    def operation(request:Request, code:str)->None: request.state.failure_code=code
    def csrf(request:Request):
        host=request.headers.get('host','').casefold()
        if not trusted_host(host): raise HTTPException(403,'cross_site_request_rejected')
        origin=request.headers.get('origin')
        if origin:
            if origin not in settings.trusted_origins:raise HTTPException(403,'cross_site_request_rejected')
        elif settings.public_app_mode: raise HTTPException(403,'cross_site_request_rejected')
    def client_ip(request:Request)->str:
        return request.client.host if request.client else 'unknown'
    def user(request:Request):return db.session_user(request.cookies.get(COOKIE))
    def session_response(request:Request,data:dict,status:int):
        token=data.get('session',{}).pop('_token',None); response=ok(request,data,status)
        if token:
            account=data.get('user',{})
            max_age=settings.visitor_ttl_hours*3600 if account.get('account_type')=='visitor' else 43200
            response.set_cookie(COOKIE,token,httponly=True,samesite='lax',secure=settings.cookie_secure,max_age=max_age,path='/')
        return response
    @app.get('/health')
    def health():return {'status':'ok','service':'story-continuity-app'}
    @app.get('/readiness')
    def ready():
        try: database_ready=db.readiness_probe()
        except sqlite3.Error: database_ready=False
        capabilities={'database':database_ready,'provider_configured':bool(engine.provider.available),'mailer_configured':not isinstance(mailer,UnavailableMailer),'public_mode':settings.public_app_mode}
        required_ready=database_ready and (not settings.public_app_mode or (capabilities['provider_configured'] and capabilities['mailer_configured']))
        return JSONResponse(status_code=200 if required_ready else 503,content={'status':'ready' if required_ready else 'not_ready','capabilities':capabilities,'security_error_code':None if required_ready else 'required_capability_unavailable'})
    @app.post('/api/auth/visitor',status_code=201)
    def visitor(request:Request):
        csrf(request); data=stage13.create_visitor(request.cookies.get(COOKIE)); return session_response(request,data,201)
    @app.post('/api/auth/register',status_code=201)
    def register(payload:Register,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'registration_failed'); replay_key=key(idempotency_key)
        with registration_lock:
            if settings.require_recovery_email and not payload.recovery_email: raise HTTPException(400,'recovery_email_required')
            registration=payload.model_dump(exclude={'recovery_email'})
            if payload.recovery_email:
                normalized=normalize_email(payload.recovery_email)
                registration['recovery_email_hash']=stage13.email_hash(normalized)
                registration['recovery_email_masked']=masked_email(normalized)
            data,status=db.register(registration,replay_key)
            created=bool(data.pop('_registration_created',False))
            if created:
                delivery='not_requested'
                if payload.recovery_email:
                    try:
                        stage13.resend_verification(data['user']['id'],payload.recovery_email,client_ip(request)); delivery='sent'
                    except DomainError as error:
                        if error.code!='recovery_delivery_failed': raise
                        delivery='failed'
                data['user']=stage13.safe_user(data['user']['id']); data['recovery_email_delivery']=delivery
                db.finalize_registration_replay(payload.account_name,replay_key,data,status)
            else:
                data['user']=stage13.safe_user(data['user']['id'])
                data.setdefault('recovery_email_delivery','failed' if payload.recovery_email else 'not_requested')
            return session_response(request,data,status)
    @app.post('/api/auth/login')
    def login(payload:Login,request:Request):
        csrf(request); operation(request,'login_failed'); data=db.login(payload.model_dump()); data['user']=stage13.safe_user(data['user']['id']); return session_response(request,data,200)
    @app.post('/api/auth/logout',status_code=204)
    def logout(request:Request):csrf(request); db.logout(request.cookies.get(COOKIE)); response=Response(status_code=204); response.delete_cookie(COOKIE,path='/',secure=settings.cookie_secure,samesite='lax'); return response
    @app.get('/api/auth/session')
    def session(request:Request,optional:bool=False):
        try: active=user(request)
        except DomainError as error:
            if optional and error.code=='authentication_required':return ok(request,{'user':None,'session':None})
            raise
        return ok(request,{'user':stage13.safe_user(active['id']),'session':{'expires_at':active['expires_at']}})
    @app.get('/api/auth/recovery-email')
    def recovery_email_status(request:Request): return ok(request,stage13.safe_user(user(request)['id'])['recovery_email'])
    @app.post('/api/auth/recovery-email')
    def recovery_email_bind(payload:RecoveryEmail,request:Request):
        csrf(request); return ok(request,stage13.bind_recovery_email(user(request)['id'],payload.recovery_email,client_ip(request)))
    @app.post('/api/auth/recovery-email/resend',status_code=202)
    def recovery_email_resend(payload:RecoveryEmail,request:Request):
        csrf(request); return ok(request,stage13.resend_verification(user(request)['id'],payload.recovery_email,client_ip(request)),202)
    @app.post('/api/auth/recovery-email/verify')
    def recovery_email_verify(payload:RecoveryToken,request:Request):
        csrf(request); return ok(request,stage13.verify_email(payload.token,client_ip(request)))
    @app.post('/api/auth/password-reset/request',status_code=202)
    def password_reset_request(payload:PasswordResetRequest,request:Request):
        csrf(request); stage13.request_password_reset(payload.recovery_email,client_ip(request),recovery_executor.submit); return ok(request,{'accepted':True},202)
    @app.post('/api/auth/password-reset/confirm')
    def password_reset_confirm(payload:PasswordResetConfirm,request:Request):
        csrf(request); return ok(request,stage13.confirm_password_reset(payload.token,payload.password,client_ip(request)))
    @app.get('/api/home')
    def home(request:Request):return ok(request,db.home(user(request)['id']))
    @app.get('/api/onboarding')
    def onboarding(request:Request):return ok(request,db.onboarding(user(request)['id']))
    @app.post('/api/onboarding/progress')
    def onboarding_progress(payload:TutorialProgressEvent,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'onboarding_progress_failed');data,status=db.record_tutorial_event(user(request)['id'],payload.model_dump(),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/onboarding/complete')
    def onboarding_complete(payload:OnboardingAction,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'onboarding_update_failed');data,status=db.finish_onboarding(user(request)['id'],'completed',payload.model_dump(),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/onboarding/skip')
    def onboarding_skip(payload:OnboardingAction,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'onboarding_update_failed');data,status=db.finish_onboarding(user(request)['id'],'skipped',payload.model_dump(),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/onboarding/reopen')
    def onboarding_reopen(payload:OnboardingAction,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'onboarding_update_failed');data,status=db.reopen_onboarding(user(request)['id'],payload.model_dump(),key(idempotency_key));return ok(request,data,status)
    @app.get('/api/projects')
    def projects(request:Request,q:str|None=None,status:str|None=None,has_open_issues:bool|None=None,sort:str|None=None):return ok(request,db.list_projects(user(request)['id'],q,status,has_open_issues,sort))
    @app.post('/api/projects',status_code=201)
    def create_project(payload:ProjectCreate,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'create_failed');data,status=db.create_project(user(request)['id'],payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    @app.get('/api/projects/{project_id}')
    def project(project_id:str,request:Request):return ok(request,db.project(user(request)['id'],project_id))
    @app.patch('/api/projects/{project_id}')
    def project_patch(project_id:str,payload:ProjectPatch,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'update_failed');data,status=db.update_project(user(request)['id'],project_id,payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    @app.get('/api/projects/{project_id}/outline')
    def outline(project_id:str,request:Request,volume:str|None=None,status:str|None=None):
        if volume not in {None,'1'} or status not in {None,'planned','complete'}:raise HTTPException(400,'invalid_filter')
        data=db.outline(user(request)['id'],project_id)
        if status:data['chapter_nodes']=[item for item in data['chapter_nodes'] if item['status']==status]
        return ok(request,data)
    @app.get('/api/projects/{project_id}/characters')
    def characters(project_id:str,request:Request,q:str|None=None,role_type:str|None=None,character_id:str|None=None):
        if role_type not in {None,'protagonist','ally','antagonist','supporting'}:raise HTTPException(400,'invalid_filter')
        data=db.characters(user(request)['id'],project_id); rows=data['characters']
        if character_id:
            rows=[item for item in rows if item['id']==character_id]
            if not rows:raise HTTPException(404,'resource_not_found')
        if q:rows=[item for item in rows if q in item['name'] or q in item['identity']]
        if role_type:rows=[item for item in rows if item['role_type']==role_type]
        data['characters']=rows;return ok(request,data)
    @app.get('/api/projects/{project_id}/world')
    def world(project_id:str,request:Request,q:str|None=None,entry_type:str|None=None,entry_id:str|None=None):
        if entry_type not in {None,'location','organization','rule','object','term'}:raise HTTPException(400,'invalid_filter')
        data=db.world(user(request)['id'],project_id); rows=data['entries']
        if entry_id:
            rows=[item for item in rows if item['id']==entry_id]
            if not rows:raise HTTPException(404,'resource_not_found')
        if q:rows=[item for item in rows if q in item['name'] or q in item['summary']]
        if entry_type:rows=[item for item in rows if item['entry_type']==entry_type]
        data['entries']=rows;return ok(request,data)
    @app.get('/api/projects/{project_id}/chapters')
    def chapters(project_id:str,request:Request,include:str|None=None,chapter_id:str|None=None):
        if include not in {None,'excerpt'}:raise HTTPException(400,'invalid_query')
        data=db.chapters(user(request)['id'],project_id,include=='excerpt')
        if chapter_id:
            rows=[item for item in data['chapters'] if item['id']==chapter_id]
            if not rows:raise HTTPException(404,'resource_not_found')
            data['chapters']=rows
        return ok(request,data)
    @app.get('/api/projects/{project_id}/memory')
    def memory(project_id:str,request:Request,version:int|None=None,entity:str|None=None,memory_type:str|None=None,chapter:str|None=None):
        if memory_type not in {None,'static_canon','dynamic_state','event_timeline','character_knowledge','open_thread'}:raise HTTPException(400,'invalid_filter')
        data=db.memory(user(request)['id'],project_id,version); data['records']=[r for r in data['records'] if(not entity or entity in r['subject'] or entity in r['value'])and(not memory_type or r['memory_type']==memory_type)and(not chapter or(r['source']and r['source']['chapter_id']==chapter))];return ok(request,data)
    @app.get('/api/projects/{project_id}/memory/initialization')
    def memory_initialization(project_id:str,request:Request):return ok(request,db.memory_initialization(user(request)['id'],project_id))
    @app.get('/api/projects/{project_id}/memory/coverage')
    def memory_coverage(project_id:str,request:Request):return ok(request,db.memory_coverage(user(request)['id'],project_id))
    @app.get('/api/projects/{project_id}/memory/delta')
    def memory_delta(project_id:str,request:Request):return ok(request,db.memory_delta(user(request)['id'],project_id))
    @app.get('/api/projects/{project_id}/source-coverage-audits/{audit_id}')
    def source_coverage_audit(project_id:str,audit_id:str,request:Request):return ok(request,db.source_coverage_audit(user(request)['id'],project_id,audit_id))
    @app.post('/api/projects/{project_id}/memory/initializations',status_code=201)
    def start_memory_initialization(project_id:str,payload:MemoryInitialization,request:Request,view:Literal['full','compact']='full',idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'memory_initialization_failed')
        actor=user(request); input_data=db.memory_initialization_input(actor['id'],project_id,payload.source_revision)
        if input_data is None:
            current=db.memory_initialization(actor['id'],project_id)
            initialization=current if view=='full' else {field:current.get(field) for field in ('id','project_id','status','source_revision','created_at','completed_at')}
            return ok(request,{"initialization":initialization})
        reservation_id=stage13.reserve_workflow(actor['id'],project_id,'memory_initialization')
        with provider_usage(actor['id'],reservation_id): result=memory_engine.execute(input_data)
        if result['status']!='completed':
            status=429 if result.get('error_code') in {'provider_attempt_quota_exceeded','workflow_quota_exceeded','server_budget_exceeded'} else 503
            raise DomainError(result['error_code'],status,result.get('retryable') is True,safe_memory_initialization_failure_details(result))
        data,status=db.complete_memory_initialization(actor['id'],project_id,input_data,result,memory_engine.provenance(),key(idempotency_key))
        data['initialization_metrics']={key:result[key] for key in ('total_batches','schema_repair_attempts','validated_batches','staged_candidate_count','normalization_count','input_tokens','output_tokens','latency_ms') if isinstance(result.get(key),int) and not isinstance(result.get(key),bool)}
        data['initialization_metrics']['repair_events']=safe_repair_events(result.get('repair_events'))
        kinds=result.get('normalization_kinds')
        data['initialization_metrics']['normalization_kinds']={key:value for key,value in kinds.items() if key in MEMORY_NORMALIZATION_KINDS and isinstance(value,int) and not isinstance(value,bool) and value>=1} if isinstance(kinds,dict) else {}
        data['initialization_metrics']['cost_available']=isinstance(result.get('cost_cny'),(int,float)) and not isinstance(result.get('cost_cny'),bool)
        data['initialization_provenance']=memory_engine.provenance()
        if view=='full':data['initialization']=db.memory_initialization(actor['id'],project_id)
        return ok(request,data,status)
    @app.post('/api/projects/{project_id}/memory/initializations/{initialization_id}/candidates/{candidate_id}/decision')
    def memory_candidate_decision(project_id:str,initialization_id:str,candidate_id:str,payload:MemoryCandidateDecision,request:Request,view:Literal['full','compact']='full',idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'memory_candidate_decision_failed');actor=user(request);data,status=db.decide_memory_candidate(actor['id'],project_id,initialization_id,candidate_id,payload.model_dump(exclude_none=True),key(idempotency_key))
        if view=='full':data['initialization']=db.memory_initialization(actor['id'],project_id)
        return ok(request,data,status)
    @app.post('/api/projects/{project_id}/memory/initializations/{initialization_id}/commit')
    def commit_memory_initialization(project_id:str,initialization_id:str,payload:MemoryInitializationCommit,request:Request,view:Literal['full','compact']='full',idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'memory_initialization_commit_failed');actor=user(request);data,status=db.commit_memory_initialization(actor['id'],project_id,initialization_id,payload.model_dump(exclude_none=True),key(idempotency_key))
        if view=='full':data['initialization']=db.memory_initialization(actor['id'],project_id)
        return ok(request,data,status)
    @app.post('/api/projects/{project_id}/incremental-reviews',status_code=202)
    def incremental_review(project_id:str,payload:IncrementalReview,request:Request,background_tasks:BackgroundTasks,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'incremental_review_failed'); actor=user(request)
        if not engine.provider.available: raise HTTPException(503,'provider_unavailable')
        data,status,created=db.create_incremental_runs(actor['id'],project_id,payload.model_dump(),key(idempotency_key),engine.provenance(),delta_engine.provenance())
        if created:
            try: reservation_id=stage13.reserve_workflow(actor['id'],project_id,'incremental_review',data['continuity_run_id'])
            except DomainError as error:
                failed={'status':'failed','error_code':error.code,'retryable':True}
                db.finish_incremental_runs(project_id,data['batch_id'],failed,failed); raise
            if executor: executor(execute_incremental,project_id,data['batch_id'],actor['id'],reservation_id)
            else: background_tasks.add_task(execute_incremental,project_id,data['batch_id'],actor['id'],reservation_id)
        return ok(request,data,status)
    @app.post('/api/projects/{project_id}/memory/deltas/{batch_id}/candidates/{candidate_id}/decision')
    def memory_delta_candidate_decision(project_id:str,batch_id:str,candidate_id:str,payload:MemoryCandidateDecision,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'memory_delta_decision_failed'); data,status=db.decide_memory_delta_candidate(user(request)['id'],project_id,batch_id,candidate_id,payload.model_dump(exclude_none=True),key(idempotency_key)); return ok(request,data,status)
    @app.post('/api/projects/{project_id}/memory/deltas/{batch_id}/commit')
    def commit_memory_delta(project_id:str,batch_id:str,payload:MemoryDeltaCommit,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'memory_delta_commit_failed'); data,status=db.commit_memory_delta(user(request)['id'],project_id,batch_id,payload.model_dump(exclude_none=True),key(idempotency_key)); return ok(request,data,status)
    @app.post('/api/projects/{project_id}/source-change-sets/preview',status_code=201)
    def source_change_preview(project_id:str,payload:SourceChangePreview,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'source_change_preview_failed'); actor=user(request)
        if payload.input_method in {'paste','file'}:
            content=payload.content or ''
            chapters,_,_=db._parse_import(content)
            if any(len(chapter['body'])>stage13.text_limits(actor['id'])['draft_chars'] for chapter in chapters): raise HTTPException(413,'source_too_large')
        data,status=db.preview_source_change_set(actor['id'],project_id,payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/projects/{project_id}/source-change-sets/{change_set_id}/commit')
    def source_change_commit(project_id:str,change_set_id:str,payload:SourceChangeCommit,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'source_change_commit_failed');data,status=db.commit_source_change_set(user(request)['id'],project_id,change_set_id,payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    @app.get('/api/projects/{project_id}/source-revisions/{source_revision}/spans')
    def source_revision_spans(project_id:str,source_revision:int,request:Request):return ok(request,db.source_revision_spans(user(request)['id'],project_id,source_revision))
    @app.get('/api/projects/{project_id}/drafts/{draft_id}')
    def draft(project_id:str,draft_id:str,request:Request):return ok(request,db.draft(user(request)['id'],project_id,draft_id))
    @app.patch('/api/projects/{project_id}/drafts/{draft_id}')
    def draft_patch(project_id:str,draft_id:str,payload:DraftPatch,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'draft_save_failed'); actor=user(request)
        if len(payload.body)>stage13.text_limits(actor['id'])['draft_chars']: raise HTTPException(413,'draft_too_large')
        data,status=db.patch_draft(actor['id'],project_id,draft_id,payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/projects/{project_id}/checks',status_code=202)
    def checks(project_id:str,payload:Check,request:Request,background_tasks:BackgroundTasks,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request); operation(request,'check_create_failed')
        actor=user(request); db.check_preflight(actor['id'],project_id,payload.draft_id,payload.draft_revision)
        if not engine.provider.available:raise HTTPException(503,'provider_unavailable')
        data,status,created=db.create_run(actor['id'],project_id,payload.model_dump(exclude_none=True),key(idempotency_key),engine.provenance())
        if created:
            try: reservation_id=stage13.reserve_workflow(actor['id'],project_id,'continuity',data['run_id'])
            except DomainError as error:
                db.finish_run(project_id,data['run_id'],{'status':'failed','error_code':error.code,'retryable':True}); raise
            if executor:executor(execute,project_id,data['run_id'],actor['id'],reservation_id)
            else:background_tasks.add_task(execute,project_id,data['run_id'],actor['id'],reservation_id)
        return ok(request,data,status)
    @app.get('/api/projects/{project_id}/checks/{run_id}')
    def check(project_id:str,run_id:str,request:Request,include:str|None=None):return ok(request,db.run_view(user(request)['id'],project_id,run_id,parse_include(include)))
    @app.post('/api/projects/{project_id}/checks/{run_id}/cancel')
    def cancel_check(project_id:str,run_id:str,payload:RunAction,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'run_cancel_failed');data,status=db.cancel_run(user(request)['id'],project_id,run_id,payload.model_dump(),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/projects/{project_id}/checks/{run_id}/retry',status_code=202)
    def retry_check(project_id:str,run_id:str,payload:RunAction,request:Request,background_tasks:BackgroundTasks,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'run_retry_failed'); actor=user(request);data,status,created=db.retry_run(actor['id'],project_id,run_id,payload.model_dump(),key(idempotency_key))
        if created:
            target_run_id=data['continuity_run_id'] if data['paired'] else data['run']['run_id']
            try: reservation_id=stage13.reserve_workflow(actor['id'],project_id,'retry',target_run_id)
            except DomainError as error:
                failed={'status':'failed','error_code':error.code,'retryable':True}
                if data['paired']: db.finish_incremental_runs(project_id,data['batch_id'],failed,failed)
                else: db.finish_run(project_id,target_run_id,failed)
                raise
            if data['paired']:
                if executor:executor(execute_incremental,project_id,data['batch_id'],actor['id'],reservation_id)
                else:background_tasks.add_task(execute_incremental,project_id,data['batch_id'],actor['id'],reservation_id)
            else:
                if executor:executor(execute,project_id,data['run']['run_id'],actor['id'],reservation_id)
                else:background_tasks.add_task(execute,project_id,data['run']['run_id'],actor['id'],reservation_id)
        return ok(request,data,status)
    @app.post('/api/projects/{project_id}/issues/{issue_id}/decision')
    def decision(project_id:str,issue_id:str,payload:Decision,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'decision_failed');data,status=db.decide(user(request)['id'],project_id,issue_id,payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/projects/{project_id}/memory/change-sets',status_code=201)
    def changeset(project_id:str,payload:ChangeSet,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'change_set_failed');data,status=db.create_changeset(user(request)['id'],project_id,payload.model_dump(),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/projects/{project_id}/memory/change-sets/{change_set_id}/commit')
    def commit(project_id:str,change_set_id:str,payload:Commit,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'commit_failed');data,status=db.commit_changeset(user(request)['id'],project_id,change_set_id,payload.model_dump(),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/projects/{project_id}/reset')
    def reset(project_id:str,payload:Reset,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'reset_failed');data,status=db.reset(user(request)['id'],project_id,payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    @app.post('/api/imports/preview',status_code=201)
    async def preview(request:Request,file:UploadFile=File(...),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'preview_failed'); actor=user(request); limits=stage13.text_limits(actor['id'])
        content=await file.read(limits['import_bytes']+1)
        if len(content)>limits['import_bytes']: raise HTTPException(413,'import_too_large')
        try: decoded=content.decode('utf-8')
        except UnicodeDecodeError: raise HTTPException(415,'unsupported_encoding') from None
        if len(decoded)>limits['import_chars']: raise HTTPException(413,'import_too_large')
        data,status=db.preview_import(actor['id'],file.filename or '',content,key(idempotency_key));return ok(request,data,status)
    @app.post('/api/imports/{import_id}/commit',status_code=201)
    def import_commit(import_id:str,payload:ImportCommit,request:Request,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        csrf(request);operation(request,'import_failed');data,status=db.commit_import(user(request)['id'],import_id,payload.model_dump(exclude_none=True),key(idempotency_key));return ok(request,data,status)
    return app

if os.environ.get("SCC_DISABLE_DEFAULT_APP") == "1":
    app = None
else:
    try:
        app = create_app()
    except RuntimeError as configuration_error:
        failure_code = str(configuration_error)

        @asynccontextmanager
        async def failed_configuration_lifespan(_:FastAPI):
            raise RuntimeError(failure_code)
            yield

        app = FastAPI(title="Story Continuity Copilot configuration failure", lifespan=failed_configuration_lifespan)
