# -*- coding: utf-8 -*-
"""WK IMU R7 native Web backend. Original R7 drivers, zero Qt UI imports."""
import argparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit,parse_qs,quote

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)  # R7 driver config.xml + manufacturer DLL are relative to project.
from native_web.device_service import DeviceService  # noqa:E402
from native_web.r7_features import R7Workspace  # noqa:E402
from native_web.ambient_capture import AmbientGuided  # noqa:E402
from native_web.ambient_auto import AmbientAuto  # noqa:E402

SERVICE=DeviceService()
WORKSPACE=R7Workspace()
AMBIENT=AmbientGuided(SERVICE)
SERVICE.ambient_capture=AMBIENT
AUTO=AmbientAuto(SERVICE,AMBIENT)
SERVICE.ambient_auto=AUTO
TOKEN=secrets.token_urlsafe(32)
MAX_BODY=32768

class Handler(BaseHTTPRequestHandler):
    server_version='WK-R7-Web/0.1'
    def log_message(self,fmt,*args):
        print('[WEB]',self.address_string(),fmt%args,flush=True)

    def _headers(self,status,mime='application/json; charset=utf-8',length=None,extra=None):
        self.send_response(status)
        for key,val in {'Content-Type':mime,'Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
            'Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items():
            self.send_header(key,val)
        if length is not None:self.send_header('Content-Length',str(length))
        for key,val in (extra or {}).items():self.send_header(key,val)
        self.end_headers()

    def _json(self,status,value):
        data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self._headers(status,length=len(data))
        self.wfile.write(data)
    def _error(self,status,reason):
        self._json(status,{'ok':False,'error':str(reason)[:500]})
    def _local(self):
        return self.client_address[0] in ('127.0.0.1','::1','::ffff:127.0.0.1')
    def _safe_host(self):
        return self.headers.get('Host','') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def _authorize_write(self):
        if not self._local() or not self._safe_host():
            self._error(403,'只有工控机本机浏览器有操作权限');return False
        origin=self.headers.get('Origin','')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            self._error(403,'拒绝跨站操作');return False
        if self.headers.get('X-WK-Token','')!=TOKEN:
            self._error(403,'操作令牌不正确');return False
        n=self.headers.get('Content-Length','0')
        if not n.isascii() or not n.isdecimal() or int(n)>MAX_BODY:
            self._error(413,'请求体长度无效或超过上限');return False
        return True

    def _download(self,filepath):
        f=Path(filepath)
        mime=mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
        self._headers(200,mime,length=f.stat().st_size,
            extra={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(f.name)})
        with f.open('rb') as handle:
            while True:
                chunk=handle.read(128*1024)
                if not chunk:break
                self.wfile.write(chunk)

    def do_GET(self):
        url=urlsplit(self.path)
        path=url.path
        args=parse_qs(url.query)
        try:
            if path=='/api/health':self._json(200,{'ok':True,'data':{'version':'R7','mode':'physical','desktop_ui':False}});return
            if path=='/api/session':
                if not self._local() or not self._safe_host():self._error(403,'仅本机浏览器可操作')
                else:self._json(200,{'ok':True,'data':{'token':TOKEN}})
                return
            reads={
                '/api/status':SERVICE.status,
                '/api/ports':SERVICE.serial_ports,
                '/api/records':SERVICE.records,
                '/api/r7/draft':WORKSPACE.draft,
                '/api/r7/poses':WORKSPACE.poses,
                '/api/r7/runs':WORKSPACE.list_runs,
                '/api/r7/job':WORKSPACE.job_state,
                '/api/ambient/status':AMBIENT.status,
                '/api/ambient/auto/status':AUTO.status,
                '/api/ambient/reports':AMBIENT.list_reports,
            }
            if path in reads:self._json(200,{'ok':True,'data':reads[path]()});return
            if path=='/api/td/calibration/plan':
                from native_web.ambient_plans import ambient_plan
                self._json(200,{'ok':True,'data':ambient_plan(args.get('kind',['acc'])[0])});return
            if path=='/api/imu/trace':
                since_text=args.get('since',['0'])[0]
                if not since_text.isdecimal() or len(since_text)>16:
                    raise ValueError('since 参数不合法')
                self._json(200,{'ok':True,'data':SERVICE.imu_trace(int(since_text))});return
            if path=='/api/ambient/download':
                self._download(AMBIENT.report_file(args.get('run',[''])[0],args.get('name',[''])[0]));return
            if path=='/api/r7/run':
                self._json(200,{'ok':True,'data':WORKSPACE.detail(args.get('name',[''])[0])});return
            if path=='/api/r7/file':
                self._download(WORKSPACE.file(args.get('run',[''])[0],args.get('name',[''])[0]));return
            if path=='/api/record/download':
                self._download(SERVICE.record_file(args.get('name',[''])[0]));return
            static={'/':'index.html','/index.html':'index.html','/app.css':'app.css','/app.js':'app.js'}
            name=static.get(path)
            if name is None:self._error(404,'页面或接口不存在');return
            f=BASE/name
            if not f.is_file():self._error(404,'网页资源缺失');return
            content=f.read_bytes()
            mime=mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
            self._headers(200,mime+'; charset=utf-8',len(content))
            self.wfile.write(content)
        except (FileNotFoundError,ValueError,TypeError,KeyError) as exc:self._error(404,exc)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as exc:
            SERVICE.log('GET failed: '+str(exc),'error')
            self._error(500,str(exc))

    def do_POST(self):
        url=urlsplit(self.path)
        handlers={
            '/api/settings':SERVICE.update_settings,
            '/api/imu/connect':lambda _:SERVICE.imu_connect(),
            '/api/imu/disconnect':lambda _:SERVICE.imu_disconnect(),
            '/api/imu/record/start':lambda _:SERVICE.imu_record_start(),
            '/api/imu/record/stop':lambda _:SERVICE.imu_record_stop(),
            '/api/imu/uid/retry':lambda _:SERVICE.imu_uid_retry(),
            '/api/plc/connect':lambda _:SERVICE.plc_connect(),
            '/api/plc/disconnect':lambda _:SERVICE.plc_disconnect(),
            '/api/td/connect':lambda _:SERVICE.td_connect(),
            '/api/td/disconnect':lambda _:SERVICE.td_manual_disconnect(),
            '/api/td/scan-connect':lambda _:SERVICE.td_scan_connect(),
            '/api/td/enable':SERVICE.td_enable_axes,
            '/api/td/jog':SERVICE.td_jog,
            '/api/td/return-zero':SERVICE.td_return_zero,
            '/api/td/stop-all':lambda _:SERVICE.td_stop_all(),
            '/api/wk/connect':lambda _:SERVICE.wk_connect(),
            '/api/wk/disconnect':lambda _:SERVICE.wk_disconnect(),
            '/api/r7/draft':WORKSPACE.save_draft,
            '/api/ambient/start':lambda b:AMBIENT.start(b) if not AUTO.is_active() else (_ for _ in ()).throw(RuntimeError('正在执行自动标定')) ,
            '/api/ambient/auto/start':AUTO.start,
            '/api/ambient/auto/abort':lambda _:AUTO.request_abort(),
            '/api/ambient/begin':lambda b:AMBIENT.begin(b) if not AUTO.is_active() else (_ for _ in ()).throw(RuntimeError('自动模式中不能人工采集')),
            '/api/ambient/finish':lambda b:AMBIENT.finish(b) if not AUTO.is_active() else (_ for _ in ()).throw(RuntimeError('自动模式中不能人工结束采样')),
            '/api/ambient/cancel':lambda b:AMBIENT.cancel(b) if not AUTO.is_active() else (_ for _ in ()).throw(RuntimeError('自动模式中请点停止自动任务')),
            '/api/r7/preview':WORKSPACE.preview,
            '/api/r7/analyze':lambda body:WORKSPACE.analyze(body.get('name',''),
                not SERVICE.status()['imu']['recording']),
        }
        callback=handlers.get(url.path)
        if callback is None:self._error(404,'未实现此设备操作。Web 尚未迁移温箱写SP、WK运动和R7自动温补。');return
        if not self._authorize_write():return
        try:
            n=int(self.headers.get('Content-Length','0'))
            body=json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
            if not isinstance(body,dict):raise ValueError('请求必须是JSON对象')
            result=callback(body)
            self._json(200,{'ok':True,'data':result})
        except (ValueError,RuntimeError,FileNotFoundError) as exc:
            SERVICE.log(str(exc),'warning');self._error(409,exc)
        except Exception as exc:
            SERVICE.log(type(exc).__name__+': '+str(exc),'error');self._error(500,str(exc))


def main(argv=None):
    parser=argparse.ArgumentParser(description='WK R7 Web, no PySide6')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--open-browser',action='store_true')
    parser.add_argument('--lan-readonly',action='store_true')
    args=parser.parse_args(argv)
    bind='0.0.0.0' if args.lan_readonly else '127.0.0.1'
    httpd=ThreadingHTTPServer((bind,args.port),Handler)
    if args.open_browser:
        import threading,webbrowser
        threading.Timer(.8,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}/')).start()
    print('='*67)
    print(' WK IMU R7 / Web workbench / REAL HARDWARE / NO PySide6')
    print(f' Browser: http://127.0.0.1:{args.port}/')
    print(' All COM ports remain closed until user clicks Connect. 2TD600 click-to-scan is read-only until local deliberate jog.')
    print(' 2TD600 motion + R7 auto calibration controller. Auto motor commands LOCKED until documented site commissioning.')
    print(' Physical emergency stop must remain available. Old R7 UI must be closed.')
    print('='*67,flush=True)
    try:httpd.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:print('Stopping Web service...',flush=True)
    finally:
        httpd.server_close()
        SERVICE.shutdown()

if __name__=='__main__':main()
