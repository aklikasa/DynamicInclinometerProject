'use strict';
const $=id=>document.getElementById(id);
let token=null,latest=null,configured=false,busy=false,selectedRun=null,chartSeries=[],lastFrame=null,toastTimer=null,jobPoll=0;
let savedImuPort='', discoveredPorts=[], portScanDone=false, portScanBusy=false;
let traceSession=null, traceLastSeq=0, tracePoints=[], traceFetching=false, traceOnline=false;

const NAV={overview:'工作台总览',imu:'PCB / IMU 采集',plc:'PLC 温箱',wk:'WK 温补双轴转台',td:'2TD600 常温标定转台',thermal:'R7 温补方案',poses:'12 姿态 / 工况',models:'模型复算 / 报告',records:'采集文件',system:'功能与系统'};
function put(id,str){const node=$(id);if(node)node.textContent=str===undefined||str===null?'—':String(str)}
function fmt(x,d=2){const f=Number(x);return x===null||x===undefined||!Number.isFinite(f)?'—':f.toFixed(d)}
function safeText(v,fallback='—'){return v===null||v===undefined||v===''?fallback:String(v)}
function flash(message,error=false){const el=$('toast');el.textContent=String(message);el.className='visible'+(error?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.className='',6000)}
async function request(path,options){let res;try{res=await fetch(path,{cache:'no-store',...options})}catch{throw new Error('连接不到 Python 后端：检查启动窗口是否已退出。')}let obj;try{obj=await res.json()}catch{throw new Error('后端响应格式错误：'+res.status)}if(!res.ok||!obj.ok)throw new Error(obj.error||'请求失败 '+res.status);return obj.data}
const get=path=>request(path);
const post=(action,data={})=>request('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-WK-Token':token||''},body:JSON.stringify(data)});
function pill(id,reading,connected){const e=$(id);if(!e)return;e.className='pill '+(reading?'good':connected?'wait':'muted');e.textContent=reading?'数据在线':connected?'通讯已连接':'未连接'}
function route(page){if(!NAV[page])page='overview';document.querySelectorAll('.page').forEach(node=>node.classList.toggle('active',node.id==='page-'+page));document.querySelectorAll('.nav').forEach(node=>node.classList.toggle('active',node.dataset.page===page));put('breadcrumb',NAV[page]);window.location.hash=page;document.querySelector('.sidebar').classList.remove('open');if(page==='records')refreshRecords();if(page==='imu'&&portScanDone)refreshPorts();if(page==='models'){refreshRuns();refreshJob()}if(page==='poses')refreshPoses();if(page==='overview')drawChart();if(page==='imu')drawTraces();}
function loadConfig(s){if(configured)return;savedImuPort=String(s.port||'').toUpperCase();for(const [id,key] of Object.entries({cfgBaud:'baud',cfgSlave:'slave',cfgPoll:'poll_ms',cfgPlc:'plc_ip',cfgWkInner:'wk_inner',cfgWkOuter:'wk_outer'})){if($(id))$(id).value=s[key]??''}configured=true}
function render(s){latest=s;loadConfig(s.settings);const i=s.imu,p=s.plc,w=s.wk,td=s.td||{connected:false,reading:false};
for(const [target,x] of [['imuStatus',i],['plcStatus',p],['wkStatus',w],['tdStatus',td],['ovTdStatus',{connected:td.connected,reading:false}],['ovImuStatus',i],['ovPlcStatus',p],['ovWkStatus',w]])pill(target,x.reading,x.connected);
put('overallLabel',i.reading||p.reading||w.reading?'正在接收真实设备反馈':'等待设备连接');
put('ovImuVal',i.reading?fmt(i.values.temperature,2)+' °C':'—');put('ovImuSub',i.reading?'有效 '+fmt(i.comm_rate,1)+' 帧/秒':safeText(i.reason,'等待读数'));
put('ovPlcVal',p.reading?fmt(p.pv,2)+' °C':'—');put('ovPlcSub',p.reading?'目标 SP '+fmt(p.sp,1)+' °C':safeText(p.error,'等待 PLC 连接'));
put('ovWkVal',w.reading?fmt(w.inner.angle,3)+' °':'—');put('ovWkSub',w.reading?'外轴 '+fmt(w.outer.angle,3)+' °':safeText(w.error,'等待 WK 连接'));
put('imuConnectText',i.reason+(i.last_success?' · 最近有效 '+i.last_success:''));
const diag=$('imuDiagnostics');diag.textContent=`端口 ${i.port||s.settings.port} / ${i.baud||s.settings.baud} baud  · 采集线程 ${i.thread_running?'运行':'未运行'}  · 成功帧 ${i.success_count??0}/${i.total_count??0} · ${i.reason}`;diag.className='diagnostic '+(i.reading?'ok':i.open_error?'fail':'');
const av=i.reading?i.values.acc:null,gv=i.reading?i.values.gyro:null;
for(const [prefix,array] of [['a',av],['g',gv]])for(const [index,axis] of ['x','y','z'].entries())put(prefix+axis,array?fmt(array[index],5):'—');
put('imuTemp',i.reading?fmt(i.values.temperature,3)+' °C':'—');
put('imuSN',i.reading?safeText(i.serial_number,'未读取到'):'—');
put('imuUID',i.reading?safeText(i.device_uid_raw,'未读取到'):'—');
put('imuUIDHint',i.reading?(i.device_uid_raw?'已从 PCB 读取 MCU UID，并按原 R7 算法映射 DTS 编号。':i.uid_checked?'本次读取无有效返回；可点击重试。旧固件可能未实现寄存器3000。':'正在通过原采集线程查询 UID…'):'请先连接 PCB；UID 查询不占用第二个 COM 口。');
put('imuFrames',i.reading?i.values.frame_number:'—');put('imuRate',i.reading?fmt(i.comm_rate,1)+' 帧/秒':'—');
put('imuRange',i.reading?i.values.acc_fs+' g / '+i.values.gyro_fs+' °/s':'—');put('imuOdr',i.reading?i.values.odr+' Hz':'—');put('imuLast',i.reading?safeText(i.last_success):'—');
const r=$('recordState');r.textContent=i.recording?'正在记录':'未记录';r.className='pill '+(i.recording?'good':'muted');
put('recRows',i.record_rows??0);put('recDrops',i.record_drop??0);put('recFile',safeText(i.record_path,'尚未记录'));
put('plcPV',p.reading?fmt(p.pv,2):'—');put('plcSP',p.reading?fmt(p.sp,2):'—');put('plcAlarm',p.reading?p.alarm:'—');put('plcRun',p.reading?(p.running?'运行':'未运行'):'未连接或数据过期');put('plcRunning',p.reading?(p.running?'运行':'停止'):'—');put('plcFault',p.reading?(p.fault?'设备故障':'无故障标志'):'—');put('plcError',p.error||'设备未报告异常');
for(const [name,axis] of [['Inner',w.reading?w.inner:null],['Outer',w.reading?w.outer:null]]){put('wk'+name+'Angle',axis?fmt(axis.angle,4):'—');put('wk'+name+'State',axis?axis.state:'—');put('wk'+name+'Alarm',axis?axis.alarm:'—');put('wk'+name+'Run',axis?'状态 '+axis.state:'未知');}
put('wkError',w.error||'没有收到厂家错误代码。无运动指令接口。');
for(const id of ['tdStatus','ovTdStatus']){const e=$(id);if(e){e.className='pill '+(td.connected?'wait':'muted');e.textContent=td.reading?'数据在线':td.connected?'串口已打开':'未连接'}}
put('ovTdVal',td.reading&&td.inner?fmt(td.inner.angle,3)+' °':'—');
put('ovTdSub',td.connected?'实时反馈 · '+(td.port||''):'独立 2TD600 串口未连接');
for(const [key,axis] of [['Inner',td.reading?td.inner:null],['Outer',td.reading?td.outer:null]]){
 put('td'+key+'Angle',axis?fmt(axis.angle,4):'—');put('td'+key+'Speed',axis?fmt(axis.speed,4)+' °/s':'—');
 put('td'+key+'Mode',axis?safeText(axis.mode,'未知'):'—');put('td'+key+'Zero',axis?(axis.zero?'已找零':'未找零'):'—');
 put('td'+key+'Normal',axis?(axis.normal?'DLL 正常标志':'DLL 异常标志'):'—');}
for(const [key,axis] of [['Inner',td.reading?td.inner:null],['Outer',td.reading?td.outer:null]]){put('td'+key+'Enabled',axis?(axis.enabled?'已使能':'未使能'):'—');}
const motion=td.motion||{};
put('tdMotionState',({idle:'待命',moving:'运动中',complete:'已到位',stopping:'停车中',stopped:'已停车',fault:'故障'})[motion.state]||'待命');
put('tdInnerJogHint',td?.reading?(td.inner?.enabled?'已使能':'未使能'):'未连接');put('tdOuterJogHint',td?.reading?(td.outer?.enabled?'已使能':'未使能'):'未连接');
const travelInfo=Number.isFinite(motion.travelled_deg)&&Number.isFinite(motion.requested_step_deg)?` ｜ 已累计 ${fmt(motion.travelled_deg,2)}° / 目标 ${fmt(motion.requested_step_deg,2)}°（按实际反馈累计，多圈不取模）`:'';
put('tdMotionDetail',(motion.message||'所有运动命令均经过原 R7 故障与限位检查；软件停车不是硬件急停。')+travelInfo);
put('tdDiag',td.error?'转台反馈异常：'+td.error:td.connected?('2TD600 已连接 '+td.port+(td.reading?'；实时角度反馈正常':'；等待新鲜反馈')):'尚未连接。点击“自动扫描串口并连接”，或手动选择转台 COM 口。');
const tdTelem=$('tdTelemDot');if(tdTelem)tdTelem.className='td-telemetry-dot '+(td.reading?'online':td.connected?'wait':'');
put('tdTelemLink',td.reading?'实时反馈':td.connected?'等待反馈':'未连接');
put('tdTelemPort',td.connected?safeText(td.port):'—');
put('tdTelemAge',td.reading&&td.feedback_age_ms!==null?Math.round(td.feedback_age_ms)+' ms':'—');
put('tdTelemEnable',td.reading?(td.inner?.enabled&&td.outer?.enabled?'双轴已使能':td.inner?.enabled||td.outer?.enabled?'单轴使能':'双轴未使能'):'—');
put('tdTelemMotion',td.connected?(({idle:'待命',moving:'运动中',complete:'已到位',stopping:'停车中',stopped:'已停车',fault:'异常'})[motion.state]||'待命'):'—');
put('tdTelemMessage',td.error?'反馈异常：'+td.error:td.connected?(motion.message||'两轴状态来自厂家 DLL 实时回读'):'设备尚未连接');

const list=$('overviewEvents');list.replaceChildren();for(const item of (s.events||[]).slice(0,6)){const row=document.createElement('div');row.className='event';const b=document.createElement('i');b.className='event-bullet '+(item.level||'');const content=document.createElement('div');content.className='event-content';content.textContent=item.text||'';const tm=document.createElement('small');tm.textContent=item.time||'';content.append(tm);row.append(b,content);list.append(row)}
if(i.reading&&i.values.frame_number!==lastFrame){lastFrame=i.values.frame_number;chartSeries.push(i.values.temperature);if(chartSeries.length>120)chartSeries.shift();put('chartTime',new Date().toLocaleTimeString('zh-CN'));}drawChart();}
function drawChart(){const c=$('overviewChart');if(!c)return;const r=c.getBoundingClientRect();if(r.width<1||r.height<1)return;const dpr=window.devicePixelRatio||1,w=Math.round(r.width*dpr),h=Math.round(r.height*dpr);if(c.width!==w||c.height!==h){c.width=w;c.height=h}const ctx=c.getContext('2d');ctx.clearRect(0,0,w,h);const L=43*dpr,R=9*dpr,T=12*dpr,B=26*dpr;ctx.font=10*dpr+'px Segoe UI';ctx.textAlign='right';ctx.fillStyle='#9daac0';ctx.strokeStyle='#edf1f8';ctx.lineWidth=1*dpr;
if(!chartSeries.length){ctx.textAlign='center';ctx.fillStyle='#a8b4c9';ctx.fillText('等待真实 PCB 数据 · 不绘制模拟曲线',w/2,h/2);return}
let lo=Math.min(...chartSeries),hi=Math.max(...chartSeries);const span=Math.max(1,hi-lo);lo-=span*.25;hi+=span*.25;
for(let j=0;j<=4;j++){let y=T+(h-T-B)*j/4;ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(w-R,y);ctx.stroke();ctx.fillText((hi-(hi-lo)*j/4).toFixed(1),L-7*dpr,y+3*dpr)}
if(chartSeries.length===1){ctx.fillStyle='#4375e4';ctx.beginPath();ctx.arc(w/2,h/2,3*dpr,0,Math.PI*2);ctx.fill();return}
ctx.beginPath();chartSeries.forEach((v,j)=>{const x=L+(w-L-R)*j/(chartSeries.length-1),y=T+(h-T-B)*(hi-v)/(hi-lo);j?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle='#4875e7';ctx.lineWidth=2*dpr;ctx.stroke();ctx.lineTo(w-R,h-B);ctx.lineTo(L,h-B);ctx.closePath();const grad=ctx.createLinearGradient(0,T,0,h-B);grad.addColorStop(0,'rgba(76,117,231,.15)');grad.addColorStop(1,'rgba(76,117,231,0)');ctx.fillStyle=grad;ctx.fill()}
const TRACE_COLORS=['#3267e5','#10a38e','#e89a3d'];
function drawTrace(canvasId,field){
  const c=$(canvasId);if(!c)return;
  const r=c.getBoundingClientRect();if(r.width<1||r.height<1)return;
  const dpr=window.devicePixelRatio||1,w=Math.max(1,Math.round(r.width*dpr)),h=Math.max(1,Math.round(r.height*dpr));
  if(c.width!==w||c.height!==h){c.width=w;c.height=h}
  const ctx=c.getContext('2d');ctx.clearRect(0,0,w,h);
  const L=55*dpr,R=9*dpr,T=15*dpr,B=23*dpr,plotW=w-L-R,plotH=h-T-B;
  ctx.font=10*dpr+'px Segoe UI';ctx.textAlign='right';ctx.strokeStyle='#e8edf6';ctx.fillStyle='#8998ae';ctx.lineWidth=dpr;
  if(!traceOnline||!tracePoints.length){ctx.textAlign='center';ctx.fillStyle='#a5b2c4';ctx.fillText('等待真实 PCB 有效数据（无模拟曲线）',w/2,h/2);return}
  const points=tracePoints.slice(-360), all=points.flatMap(p=>p[field]);
  let lo=Math.min(...all),hi=Math.max(...all),scale=Math.max((hi-lo)*.15,field==='acc'?.005:.01);lo-=scale;hi+=scale;
  for(let j=0;j<=4;j++){const y=T+plotH*j/4;ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(w-R,y);ctx.stroke();ctx.fillText((hi-(hi-lo)*j/4).toFixed(field==='acc'?3:2),L-6*dpr,y+3*dpr)}
  if(points.length===1){for(let axis=0;axis<3;axis++){let y=T+plotH*(hi-points[0][field][axis])/(hi-lo);ctx.fillStyle=TRACE_COLORS[axis];ctx.beginPath();ctx.arc(L,y,3*dpr,0,Math.PI*2);ctx.fill()}return}
  for(let axis=0;axis<3;axis++){ctx.beginPath();points.forEach((p,j)=>{const x=L+plotW*j/(points.length-1),y=T+plotH*(hi-p[field][axis])/(hi-lo);j?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle=TRACE_COLORS[axis];ctx.lineWidth=1.7*dpr;ctx.stroke()}
}
function drawTraces(){drawTrace('accTrace','acc');drawTrace('gyroTrace','gyro')}
async function refreshTrace(){
  if(traceFetching)return;traceFetching=true;
  try{
    const result=await get('/api/imu/trace?since='+traceLastSeq);
    if(traceSession!==result.session){traceSession=result.session;traceLastSeq=0;tracePoints=[];}
    traceOnline=!!result.online;
    if(!traceOnline){tracePoints=[];traceLastSeq=0;}
    else if(Array.isArray(result.samples)){
      for(const row of result.samples){
        if(Number.isInteger(row.seq)&&row.seq>traceLastSeq&&Array.isArray(row.acc)&&row.acc.length===3&&Array.isArray(row.gyro)&&row.gyro.length===3){
          tracePoints.push(row);traceLastSeq=row.seq;
        }
      }
      if(tracePoints.length>360)tracePoints=tracePoints.slice(-360);
    }
    const label=traceOnline&&tracePoints.length?'已收到 '+tracePoints.length+' 个真实帧均值 · '+new Date().toLocaleTimeString('zh-CN'):'等待有效采样';
    put('accTraceLast',label);put('gyroTraceLast',label);
    drawTraces();
  }catch(err){traceOnline=false;drawTraces();put('accTraceLast','趋势接口不可用');put('gyroTraceLast','趋势接口不可用')}
  finally{traceFetching=false}
}
let lastOfflineToast=0;async function refreshStatus(){try{const data=await get('/api/status');render(data);$('backendDot').className='tiny-dot connected';put('backendText','Web 服务在线');}catch(err){$('backendDot').className='tiny-dot';put('backendText','服务离线');if(Date.now()-lastOfflineToast>15000){flash(err.message,true);lastOfflineToast=Date.now()}}}
function grabDevice(kind){
if(kind==='td'&&!($('cfgTdPort').value&&Array.from($('cfgTdPort').options).some(o=>o.value===$('cfgTdPort').value)))throw new Error('2TD600 必须选择 Windows 实时检测到的 COM 口。');
if(kind==='imu'){
  const port=$('cfgPort').value.trim();
  if(!portScanDone)throw new Error('正在扫描 Windows 串口，请等待扫描完成。');
  if(!port||!discoveredPorts.some(p=>p.device===port))throw new Error('请选择本机实际检测到的 COM 口；如未显示，请先点击“重新扫描”并检查设备管理器。');
}
const cfg={imu:{port:$('cfgPort').value.trim(),baud:Number($('cfgBaud').value),slave:Number($('cfgSlave').value),poll_ms:Number($('cfgPoll').value)},plc:{plc_ip:$('cfgPlc').value.trim()},wk:{wk_inner:$('cfgWkInner').value.trim(),wk_outer:$('cfgWkOuter').value.trim()},td:{td_port:$('cfgTdPort').value.trim()}};return cfg[kind]}
async function saveDevice(kind){return post('settings',grabDevice(kind))}
async function doAction(path){if(busy)return;busy=true;disableWrites(true);try{if(path==='imu/connect')await saveDevice('imu');if(path==='plc/connect')await saveDevice('plc');if(path==='wk/connect')await saveDevice('wk');if(path==='td/connect')await saveDevice('td');const resp=await post(path);flash(typeof resp==='string'?resp:'操作已执行',typeof resp==='string'&&resp.includes('未打开'));await refreshStatus()}catch(err){flash(err.message,true)}finally{busy=false;disableWrites(false)}}
function disableWrites(b){document.querySelectorAll('[data-act]').forEach(el=>el.disabled=b||!token)}
async function refreshPorts(){
  if(portScanBusy)return;
  portScanBusy=true;
  const select=$('cfgPort'),hint=$('portScanStatus'),details=$('portScanDetails'),button=$('reloadPorts');
  button.disabled=true;
  hint.className='port-scan-status';hint.textContent='正在读取这台 Windows 电脑的 COM 口…';
  try{
    const ports=await get('/api/ports');
    if(!Array.isArray(ports))throw new Error('后端串口扫描结果格式错误');
    const previous=select.value;
    const preferred=previous||(portScanDone?'':savedImuPort);
    discoveredPorts=ports.filter(p=>p&&/^COM[1-9][0-9]*$/i.test(String(p.device||'')))
      .map(p=>({device:String(p.device).toUpperCase(),description:String(p.description||'串口设备')}));
    const unique=new Map(discoveredPorts.map(p=>[p.device,p]));
    discoveredPorts=Array.from(unique.values()).sort((a,b)=>Number(a.device.slice(3))-Number(b.device.slice(3)));
    select.replaceChildren();
    const placeholder=document.createElement('option');placeholder.value='';
    placeholder.textContent=discoveredPorts.length?'— 请选择实际检测到的串口 —':'未检测到 COM 口（请检查设备管理器）';
    select.append(placeholder);
    for(const p of discoveredPorts){const opt=document.createElement('option');opt.value=p.device;opt.textContent=p.device+'  ·  '+p.description;select.append(opt)}
    select.value=discoveredPorts.some(p=>p.device===preferred)?preferred:'';
    portScanDone=true;
    details.replaceChildren();
    if(discoveredPorts.length){
      const title=document.createElement('div');title.textContent='Windows 实际检测到 '+discoveredPorts.length+' 个串口：';details.append(title);
      for(const p of discoveredPorts){const tag=document.createElement('span');tag.className='port-tag';const b=document.createElement('b');b.textContent=p.device;const d=document.createElement('span');d.textContent=p.description;tag.append(b,d);details.append(tag)}
      if(savedImuPort&&!discoveredPorts.some(p=>p.device===savedImuPort)){
        hint.className='port-scan-status warn';
        hint.textContent='原配置 '+savedImuPort+' 当前未被 Windows 检测到；请从列表中重新选择。';
      }else{
        hint.className='port-scan-status good';
        hint.textContent='扫描完成：'+discoveredPorts.length+' 个真实 COM 口。'+(select.value?'当前选择 '+select.value:'请选择 PCB 对应端口');
      }
    }else{
      hint.className='port-scan-status warn';
      hint.textContent='扫描结果为 0：Windows 当前没有检测到串口，请检查 USB 线、驱动和设备管理器。';
      details.textContent='当前没有可选的 COM 口；原配置 '+(savedImuPort||'未设置')+' 不是实时检测结果。';
    }
  }catch(err){
    discoveredPorts=[];portScanDone=false;
    select.replaceChildren();const opt=document.createElement('option');opt.value='';opt.textContent='串口扫描失败';select.append(opt);
    hint.className='port-scan-status warn';hint.textContent='扫描失败：'+err.message;
    details.textContent='请确认 Python 后端仍在运行，且已安装 pyserial。';
    flash('串口扫描失败：'+err.message,true);
  }finally{button.disabled=false;portScanBusy=false;}
}
async function refreshTdPorts(){
 const select=$('cfgTdPort');if(!select)return;
 const current=(latest?.td?.connected?latest.td.port:null)||select.value||latest?.settings?.td_port||'';
 try{
   const ports=await get('/api/ports');select.replaceChildren();
   const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='请选择真实 2TD600 USB 串口';select.append(placeholder);
   for(const port of ports){if(!/^COM[1-9][0-9]*$/i.test(String(port.device)))continue;
      const option=document.createElement('option');option.value=port.device.toUpperCase();option.textContent=port.device+' · '+(port.description||'串口设备')+(port.serial_number?' · USB SN':'');select.append(option)}
   select.value=Array.from(select.options).some(o=>o.value===current)?current:'';
 }catch(err){flash('2TD600 串口扫描失败：'+err.message,true)}
}
async function autoScanConnectTd(){
 if(busy)return;
 busy=true;disableWrites(true);
 try{
   await refreshTdPorts();
   const response=await post('td/scan-connect');
   flash(typeof response==='string'?response:'串口已连接');
   await refreshStatus();await refreshTdPorts();
 }catch(err){flash(err.message,true);put('tdDiag','自动扫描结果：'+err.message)}
 finally{busy=false;disableWrites(false)}
}
async function tdEnableAxes(){
 if(busy)return;
 if(!latest?.td?.reading){flash('转台当前没有有效反馈',true);return;}
 if(!$('tdSafetyAck').checked){flash('请先勾选现场硬件急停与机械安全确认',true);return;}
 if(!confirm('双轴使能会给转台驱动器和电机供电，可能改变保持力矩。请确认人员安全和硬件急停可用。继续吗？'))return;
 busy=true;
 try{const result=await post('td/enable',{safety_ack:'PHYSICAL_ESTOP_READY'});flash(result);await refreshStatus()}
 catch(err){flash(err.message,true)}finally{busy=false}
}
async function tdJog(axis,sign){
 if(busy)return;
 if(!latest?.td?.reading){flash('转台未连接或状态过期，禁止运动',true);return;}
 if(!$('tdSafetyAck').checked){flash('请先确认现场硬件急停、锁紧机构和机械安全',true);return;}
 if(!['inner','outer'].includes(axis))throw new Error('无效的轴');
 const stepBox=$(axis==='inner'?'tdInnerStep':'tdOuterStep');
 const speedBox=$(axis==='inner'?'tdInnerJogSpeed':'tdOuterJogSpeed');
 // Reject empty strings: Number('') would otherwise be 0.
 if(!stepBox.value.trim()||!speedBox.value.trim()){
   flash('请分别输入转角与速度',true);return;
 }
 const magnitude=Number(stepBox.value),speed=Number(speedBox.value);
 if(!Number.isFinite(magnitude)||magnitude<=0){flash('转角必须是大于 0 的有限数字；不再有 5° 单步限制',true);return;}
 if(!Number.isFinite(speed)||speed<0.01||speed>10){flash('原 R7 软件限速为 10°/s，厂家额定上限 60°/s；当前不绕过原软件保护',true);return;}
 const step=magnitude*sign;
 const name=axis==='inner'?'内轴':'外轴';
 if(!confirm(`准备执行真实转台动作：\n${name}：${step>0?'+':''}${step}°\n速度：${speed}°/s\n\n这是相对增量运动：例如 +720° 表示正转两整圈，不会把角度折算成 0°。
请核对线缆余量及载荷转动条件，另一个轴必须保持静止。确认现场无人、转台锁紧机构已松开、独立硬件急停可用。是否发送？`))return;
 busy=true;disableWrites(true);
 try{
   const result=await post('td/jog',{axis,step_deg:step,speed_dps:speed,safety_ack:'PHYSICAL_ESTOP_READY'});
   flash(result.message||'运动指令已发出，等待实际到位反馈');await refreshStatus();
 }catch(err){flash(err.message,true)}finally{busy=false;disableWrites(false)}
}
async function tdReturnZero(){
 if(busy)return;
 if(!latest?.td?.reading){flash('转台反馈未就绪，不能回到 0°',true);return;}
 if(!$('tdSafetyAck').checked){flash('请先确认转台现场安全和独立硬件急停',true);return;}
 const inner=Number($('tdInnerJogSpeed').value),outer=Number($('tdOuterJogSpeed').value);
 if(![inner,outer].every(v=>Number.isFinite(v)&&v>=0.01&&v<=10)){
  flash('请分别输入两轴回零速度，范围 0.01～10°/s（原 R7 软件限速）',true);return;
 }
 if(!confirm(`即将真实驱动 2TD600 双轴依次回到绝对位置 0°：\n1. 外轴 → 0°，速度 ${outer}°/s\n2. 外轴到位并停稳后，内轴 → 0°，速度 ${inner}°/s\n\n这不是机械找零。必须确认人员远离、工装/线缆空间和硬件急停可用。确定执行？`))return;
 busy=true;disableWrites(true);
 try{const result=await post('td/return-zero',{inner_speed_dps:inner,outer_speed_dps:outer,safety_ack:'PHYSICAL_ESTOP_READY'});
     flash(result.message||'双轴回到 0° 已提交，正在核对反馈');await refreshStatus();}
 catch(err){flash('双轴回到 0° 失败：'+err.message,true)}finally{busy=false;disableWrites(false)}
}
async function showTdAmbientPlan(mode){
 try{
  const p=await get('/api/td/calibration/plan?kind='+mode);
  put('tdPlanOverview',p.title+' · '+p.steps.length+' 个工况 · 工艺配置：'+p.profile_id+'（'+(p.approved_for_production?'已批准':'试运行/未批准生产')+'）'+(p.warnings?.length?'\n注意：'+p.warnings.join('；'):''));
  const area=$('tdPlanTable');area.replaceChildren();
  const tbl=document.createElement('table');const head=document.createElement('thead');
  const header=document.createElement('tr');
  for(const text of ['步骤','用途','模式','内轴 β (°)','外轴 α (°)','目标转速 (°/s)']){
    const th=document.createElement('th');th.textContent=text;header.appendChild(th);
  }
  head.appendChild(header);tbl.appendChild(head);
  const tbody=document.createElement('tbody');
  for(const step of p.steps){const row=document.createElement('tr');
   for(const value of [step.step_id,step.split==='fit'?'拟合':'独立验证',step.mode==='static'?'静态':'速率',step.inner_deg,step.outer_deg,step.target_rate_dps??'—']){
      const td=document.createElement('td');td.textContent=String(value);row.appendChild(td);
   }tbody.appendChild(row);
  }tbl.appendChild(tbody);area.appendChild(tbl);
 }catch(err){flash('读取原 R7 工况失败：'+err.message,true)}
}
let autoView=null;
async function autoStatus(){
 try{
  const d=await get('/api/ambient/auto/status');autoView=d;
  const label={idle:'未启动',starting:'预检查',running:'执行中',stopping:'停车确认中',completed:'工况完成',aborted:'已中止',fault:'停车未确认'};
  put('autoStatus',`状态：${label[d.state]||d.state}  ·  阶段：${d.phase||'—'}\n${d.message||'尚未启动自动标定'}${d.last_error?'\n最近故障：'+d.last_error:''}\n${d.notice}`);
  const pill=$('autoAccessPill');pill.textContent=d.hardware_commissioned?'已记录现场验收':'等待现场验收';
  pill.className='pill '+(d.hardware_commissioned?'good':'wait');
  for(const id of ['autoStartBoth','autoStartAcc','autoStartGyro'])$(id).disabled=!token||!d.hardware_commissioned||d.active||ambientView?.state==='ready'||ambientView?.state==='collecting';
  $('autoAbort').disabled=!token||!d.active;
  if((d.completed_run_ids||[]).length){
   const files=$('autoReportFiles');files.replaceChildren();
   try{const runs=await get('/api/ambient/reports');
    for(const run_id of d.completed_run_ids){const r=runs.find(x=>x.name===run_id);if(!r)continue;
      for(const name of r.files){if(!/^model_comparison_.*\.(xlsx|csv|json)$/.test(name))continue;
       const a=document.createElement('a');a.textContent='下载 '+run_id+' / '+name;
       a.href='/api/ambient/download?run='+encodeURIComponent(run_id)+'&name='+encodeURIComponent(name);files.appendChild(a);}
    }
   }catch(err){/* report loading is secondary to machine safety/status */}
  }
  for(const id of ['ambientStartAcc','ambientStartGyro','ambientBegin','ambientFinish','ambientCancel'])if(d.active)$(id).disabled=true;
 }catch(err){put('autoStatus','后台自动任务接口异常：'+err.message);}
}
async function autoStart(kind){
 if(!token||!autoView?.hardware_commissioned){flash('先完成实机验收，详见现场启用与验收文档',true);return}
 if(!$('tdSafetyAck').checked){flash('先核查硬件急停、夹具、电缆空间、两轴运动范围并勾选现场安全确认',true);return}
 const device_serial=$('ambientSn').value.trim();
 if(!device_serial){flash('请填写当前 PCB 的唯一编号',true);return}
 const message=`即将自动驱动真实 2TD600，依次执行 ${kind==='both'?'ACC 24 + GYRO 32':kind.toUpperCase()} 全套工况。\n\n请确认：现场一直有人监护、周边 3 米内无人、两轴已正确机械找零、实体急停已现场测试、工装与线缆无干涉。\n\n软件停车不能替代实体急停。是否确认开始真实自动运动？`;
 if(!confirm(message))return;
 try{await post('ambient/auto/start',{kind,device_serial,gravity_sign:Number($('ambientGravity').value),safety_ack:'PHYSICAL_ESTOP_READY',motion_ack:'SUPERVISED_AUTO_MOVEMENT'});await autoStatus();await ambientStatus();flash('自动标定任务已下发，必须持续现场监护')}
 catch(err){flash(err.message,true);await autoStatus()}
}
async function autoAbort(){
 if(!token)return;
 if(!confirm('请求自动任务中止并发送双轴软件停车；确认实际机台已经停止，如有异常立即使用实体硬件急停。继续？'))return;
 try{await post('ambient/auto/abort');await autoStatus();flash('已请求停车，务必观察实际转台与实体控制器')}
 catch(err){flash(err.message,true)}
}
let ambientView=null;
async function ambientStatus(){
 try{
  const d=await get('/api/ambient/status');ambientView=d;
  if(d.state==='idle'){put('ambientState','尚未创建采样会话。连接真实 PCB 和 2TD600、确认人员安全后创建任务。');$('ambientFiles').replaceChildren();}
  else{
    const step=d.current_step;
    const target=step ? `当前步骤：${step.step_id}（${step.split==='fit'?'拟合':'独立验证'} / ${step.mode==='static'?'静态':'动态'}）\n内轴目标 ${step.inner_deg}°，外轴目标 ${step.outer_deg}°${step.mode==='rate'?`，${step.rotation_axis==='inner'?'内轴':'外轴'}目标速度 ${step.target_rate_dps}°/s`:''}` : '全部工况已完成';
    put('ambientState',`任务 ${d.run_id}\n状态：${d.state} · 进度 ${d.index}/${d.total} · 已采纳 ${d.accepted} · 质量拒绝 ${d.rejected}\n${target}\n采集 ${d.sample_count} 帧${d.elapsed_seconds!==null?`，持续 ${d.elapsed_seconds}/${d.required_seconds} 秒`:''}${d.last_error?`\n最近问题：${d.last_error}`:''}\n${d.notice}`);
    if(['complete','analysis_failed'].includes(d.state) && d.run_id){
      try{const runs=await get('/api/ambient/reports'),found=runs.find(r=>r.name===d.run_id);
      const container=$('ambientFiles');container.replaceChildren();
      for(const f of (found?.files||[])){
        const a=document.createElement('a');a.textContent='下载 '+f;
        a.href='/api/ambient/download?run='+encodeURIComponent(d.run_id)+'&name='+encodeURIComponent(f);
        container.appendChild(a);
      }}catch(err){flash('报告列表读取失败：'+err.message,true)}
    }
  }
  $('ambientStartAcc').disabled=!token||autoView?.active||['ready','collecting','analyzing'].includes(d.state);
  $('ambientStartGyro').disabled=!token||autoView?.active||['ready','collecting','analyzing'].includes(d.state);
  $('ambientBegin').disabled=!token||autoView?.active||d.state!=='ready';
  $('ambientFinish').disabled=!token||autoView?.active||d.state!=='collecting';
  $('ambientCancel').disabled=!token||autoView?.active||!['ready','collecting'].includes(d.state);
 }catch(err){put('ambientState','常温标定后端不可用：'+err.message)}
}
async function ambientStart(kind){
 if(!token){flash('仅本机浏览器可以操作',true);return}
 if(!$('tdSafetyAck').checked){flash('请先勾选 2TD600 现场安全及硬件急停确认',true);return}
 const sn=$('ambientSn').value.trim();
 if(!sn){flash('先填写 PCB 唯一编号',true);return}
 if(!confirm(`将建立真实 PCB + 2TD600 ${kind.toUpperCase()} 逐工况引导采样任务。\n不会自动移动转台或开启速度运动。\n操作员负责每步位置/速度及现场安全。是否继续？`))return;
 try{await post('ambient/start',{kind,device_serial:sn,gravity_sign:Number($('ambientGravity').value),safety_ack:'PHYSICAL_ESTOP_READY'});await ambientStatus();flash('已创建真实采集会话（不会发出转台运动指令）')}
 catch(err){flash(err.message,true)}
}
async function ambientAction(action){
 if(!token)return;
 if(action==='cancel'&&!confirm('取消并保存已采集的进度？不会自动向转台发运动或停车指令。'))return;
 try{await post('ambient/'+action);await ambientStatus();if(action==='finish')flash('已执行真实采集质量检查，请查看进度/错误原因')}
 catch(err){flash(err.message,true)}
}
async function tdDisconnect(){
 if(busy)return;
 if(!latest?.td?.connected){flash('2TD600 当前没有连接');return;}
 if(['moving','stopping'].includes(latest.td.motion?.state) ||
    [latest.td.inner?.speed,latest.td.outer?.speed].some(v=>v!==undefined&&v!==null&&Math.abs(Number(v))>0.05)){
    flash('转台仍在运动或停车确认中。请先执行软件停车，并检查真实速度归零后再断开通讯。',true);return;
 }
 if(!latest.td.reading){flash('转台状态反馈过期，不能安全确认静止，已拒绝断开通讯',true);return;}
 if(!confirm('即将关闭 2TD600 的串口通讯。\n\n这不会使电机失能或让控制柜断电，也不属于停车指令。\n请确认双轴确已停止，并且现场控制器仍可监控。确定断开吗？'))return;
 busy=true;disableWrites(true);
 try{const message=await post('td/disconnect');flash(message);await refreshStatus();}
 catch(err){flash('断开通讯被拒绝：'+err.message,true)}
 finally{busy=false;disableWrites(false)}
}
async function tdStopAll(){
 try{const result=await post('td/stop-all');flash(result);await refreshStatus()}
 catch(err){flash('软件停车失败：'+err.message+'。请使用现场硬件急停！',true)}
}
async function refreshRecords(){try{const data=await get('/api/records');const tbody=$('recordsBody');tbody.replaceChildren();if(!data.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=4;td.className='empty-state';td.textContent='当前没有采集 CSV，连接真实 PCB 后开始记录即可生成';tr.append(td);tbody.append(tr);return}for(const f of data){const tr=document.createElement('tr');for(const val of [f.name,f.updated,fmt(f.bytes/1024,1)+' KB']){const td=document.createElement('td');td.textContent=val;tr.append(td)}const td=document.createElement('td'),a=document.createElement('a');a.textContent='下载 CSV';a.className='download';a.href='/api/record/download?name='+encodeURIComponent(f.name);td.append(a);tr.append(td);tbody.append(tr)}}catch(err){flash(err.message,true)}}
function draftValues(){const obj={};document.querySelectorAll('[data-th]').forEach(el=>{const value=el.dataset.num==='int'?Number.parseInt(el.value,10):el.dataset.num==='float'?Number.parseFloat(el.value):el.value.trim();obj[el.dataset.th]=value});return obj}
function setDraft(values){document.querySelectorAll('[data-th]').forEach(el=>{if(values[el.dataset.th]!==undefined)el.value=values[el.dataset.th]})}
async function loadDraft(){try{setDraft(await get('/api/r7/draft'))}catch(err){flash('实验方案未加载：'+err.message,true)}}
function previewShow(plan){const tags=$('planTags');tags.replaceChildren();const temp=plan.execution_order||[],roles=plan.temperature_split||{};
put('planNotice',plan.notice);put('planSummary',temp.length+' 个温度点 · 拟合 '+plan.fit_temperatures.length+' · 验证 '+plan.validation_temperatures.length+' · 拟合速率 '+plan.gyro_fit_rates.length);
for(const t of temp){const tag=document.createElement('span');tag.className='temp-tag'+(roles[String(t)]==='validate'?' validate':'');tag.textContent=fmt(t,1)+'°C · '+(roles[String(t)]==='validate'?'验证':'拟合');tags.append(tag)}}
async function validateDraft(save){try{const result=await post(save?'r7/draft':'r7/preview',draftValues());previewShow(save?result.preview:result);flash(save?'R7 草稿已保存（未向设备发送任何指令）':'R7 原版校验通过，已生成温度/速率计划')}catch(err){flash('方案校验失败：'+err.message,true);put('planNotice','方案校验失败：'+err.message);$('planTags').replaceChildren();put('planSummary','')}}
async function refreshPoses(){try{const obj=await get('/api/r7/poses');for(const [name,target] of [['fit','posesFit'],['verify','posesVerify']]){const area=$(target);area.replaceChildren();for(const row of obj[name]){const item=document.createElement('div');item.className='pose-item';const code=document.createElement('span');code.className='pose-no';code.textContent=row.step_id;const angle=document.createElement('span');angle.className='pose-angle';angle.textContent='β '+fmt(row.inner_deg,0)+'°  /  α '+fmt(row.outer_deg,0)+'°';item.append(code,angle);area.append(item)}}}catch(err){flash('姿态表读取失败：'+err.message,true)}}
async function refreshRuns(){try{const items=await get('/api/r7/runs'),list=$('runsList');list.replaceChildren();if(!items.length){const e=document.createElement('div');e.className='empty-state';e.textContent='暂无导入的 R7 实验目录。请按上方说明复制原 R7 实验文件夹。';list.append(e);return}for(const run of items){const item=document.createElement('button');item.className='run-item'+(run.name===selectedRun?' selected':'');const title=document.createElement('div'),label=document.createElement('strong'),meta=document.createElement('small'),state=document.createElement('span');label.textContent=run.name;meta.textContent=(run.device_sn||'未标注 SN')+' · '+run.updated;title.append(label,meta);state.textContent=run.status;item.append(title,state);item.addEventListener('click',()=>chooseRun(run.name));list.append(item)}}catch(err){flash(err.message,true)}}
async function chooseRun(name){selectedRun=name;document.querySelectorAll('.run-item').forEach(e=>e.classList.toggle('selected',e.querySelector('strong')?.textContent===name));$('reanalyzeBtn').disabled=!token;try{const d=await get('/api/r7/run?name='+encodeURIComponent(name));const box=$('runDetail');box.replaceChildren();for(const [k,v] of [['实验名称',d.name],['任务状态',d.status],['已接收逐工况',d.rows],['质量模式',d.config.quality_mode],['温度点',Array.isArray(d.config.temperatures)?d.config.temperatures.join(', '):'未知']]){const line=document.createElement('div');line.className='fileitem';const a=document.createElement('span');a.textContent=k;const b=document.createElement('strong');b.textContent=safeText(v);line.append(a,b);box.append(line)}const files=$('runFiles');files.replaceChildren();for(const f of d.files.slice(0,80)){const row=document.createElement('div'),label=document.createElement('span'),link=document.createElement('a');row.className='fileitem';label.textContent=f.name;link.className='download';link.textContent='下载';link.href='/api/r7/file?run='+encodeURIComponent(name)+'&name='+encodeURIComponent(f.name);row.append(label,link);files.append(row)}}catch(err){flash(err.message,true)}}
async function analyzeRun(){if(!selectedRun||!token)return;if(!confirm('仅对已导入并完成的 R7 实验进行离线研发分析。此操作不写 PLC/WK/MCU。确认运行？'))return;try{const resp=await post('r7/analyze',{name:selectedRun});put('analysisJob',resp.message);await refreshJob()}catch(err){flash(err.message,true)}}
async function refreshJob(){if(++jobPoll%2!==1)return;try{const obj=await get('/api/r7/job');put('analysisJob',obj.state==='running'?'正在处理：'+obj.message:obj.state==='error'?'分析失败：'+obj.message:obj.state==='complete'?'分析完成：'+obj.message:'尚无离线分析任务');if(obj.state==='complete'&&selectedRun===obj.run){/* refresh detail only on user selection to avoid noisy flashing */}}catch{/* status errors surfaced separately */}}
async function init(){const clock=()=>put('clock',new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}));clock();setInterval(clock,30000);
$('menuToggle').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>route(b.dataset.page)));
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>route(b.dataset.go)));
document.querySelectorAll('[data-act]').forEach(b=>b.addEventListener('click',()=>doAction(b.dataset.act)));
for(const kind of ['Imu','Plc','Wk','Td'])$('saveConfig'+kind).addEventListener('click',async()=>{try{await saveDevice(kind.toLowerCase());flash('连接参数已保存；修改已连接的端口前需要先断开')}catch(err){flash(err.message,true)}});
$('autoStartBoth').addEventListener('click',()=>autoStart('both'));$('autoStartAcc').addEventListener('click',()=>autoStart('acc'));$('autoStartGyro').addEventListener('click',()=>autoStart('gyro'));$('autoAbort').addEventListener('click',autoAbort);$('reloadPorts').addEventListener('click',refreshPorts);$('reloadTdPorts').addEventListener('click',refreshTdPorts);$('tdScanConnect').addEventListener('click',autoScanConnectTd);$('tdDisconnect').addEventListener('click',tdDisconnect);$('tdEnableAxes').addEventListener('click',tdEnableAxes);$('tdInnerMinus').addEventListener('click',()=>tdJog('inner',-1));$('tdInnerPlus').addEventListener('click',()=>tdJog('inner',1));$('tdOuterMinus').addEventListener('click',()=>tdJog('outer',-1));$('tdOuterPlus').addEventListener('click',()=>tdJog('outer',1));$('tdAccPlan').addEventListener('click',()=>showTdAmbientPlan('acc'));$('tdGyroPlan').addEventListener('click',()=>showTdAmbientPlan('gyro'));$('tdReturnZero').addEventListener('click',tdReturnZero);$('tdStopAll').addEventListener('click',tdStopAll);$('ambientStartAcc').addEventListener('click',()=>ambientStart('acc'));$('ambientStartGyro').addEventListener('click',()=>ambientStart('gyro'));$('ambientBegin').addEventListener('click',()=>ambientAction('begin'));$('ambientFinish').addEventListener('click',()=>ambientAction('finish'));$('ambientCancel').addEventListener('click',()=>ambientAction('cancel'));$('ambientReload').addEventListener('click',ambientStatus);$('cfgPort').addEventListener('change',()=>{const p=$('cfgPort').value;$('portScanStatus').textContent=p?'已选择 Windows 检测到的 '+p+'；保存参数后可连接 PCB。':'请先选择 PCB 对应的真实 COM 口。'});$('refreshRecords').addEventListener('click',refreshRecords);$('refreshRuns').addEventListener('click',refreshRuns);$('reanalyzeBtn').addEventListener('click',analyzeRun);
$('previewThermal').addEventListener('click',()=>validateDraft(false));$('saveThermal').addEventListener('click',()=>validateDraft(true));
window.addEventListener('resize',()=>{drawChart();drawTraces()});
try{const res=await get('/api/session');token=res.token;put('workMode','本机操作');}catch{token=null;put('workMode','仅查看');document.querySelectorAll('[data-act],#saveConfigImu,#saveConfigPlc,#saveConfigWk,#saveConfigTd,#tdScanConnect,#tdDisconnect,#tdEnableAxes,#tdInnerMinus,#tdInnerPlus,#tdOuterMinus,#tdOuterPlus,#tdStopAll,#tdReturnZero,#saveThermal,#previewThermal,#reanalyzeBtn').forEach(b=>b.disabled=true)}
await Promise.all([refreshStatus(),loadDraft(),ambientStatus(),autoStatus()]);await refreshPorts();await refreshTdPorts();try{const page=location.hash.slice(1);if(NAV[page])route(page);}catch{}setInterval(refreshStatus,1800);setInterval(()=>{if(location.hash==='#td'){ambientStatus();autoStatus()}},1800);setInterval(()=>{if(location.hash==='#td')refreshTdPorts()},8000);setInterval(refreshTrace,500);setInterval(refreshJob,3000);refreshTrace();
}
document.addEventListener('DOMContentLoaded',init);
