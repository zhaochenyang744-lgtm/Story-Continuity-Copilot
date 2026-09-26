import os,sys,pathlib,socket,ipaddress,smtplib,unittest,json,hashlib
os.environ['SCC_DISABLE_DEFAULT_APP']='1'
sys.dont_write_bytecode=True
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'backend'))
def deny(*a,**kw):raise AssertionError('No external network or SMTP during independent acceptance')
connect=socket.socket.connect
def guard(sock,address):
    if isinstance(address,tuple) and ipaddress.ip_address(address[0]).is_loopback:return connect(sock,address)
    return deny(sock,address)
socket.socket.connect=guard
socket.create_connection=deny
smtplib.SMTP=deny
suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_legacy_dispatch_quota','tests.test_v130_character_alias_change_impact'])
with (HERE/'regression-log.txt').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
summary={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'external_provider_http':0,'smtp_requests':0}
manifest={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['backend/app/provider.py','backend/app/stage13.py','backend/app/v2_database.py','backend/app/engine.py','backend/tests/test_legacy_dispatch_quota.py']}
(HERE/'regression-summary.json').write_text(json.dumps({'summary':summary,'reviewed_files_sha256':manifest},indent=2),encoding='utf-8')
print(json.dumps(summary))
sys.exit(0 if result.wasSuccessful() else 1)
