'use strict';
// Explicit inactive entry. Read exact bootstrap lines only; leave CP77 stdin intact.
const fs=require('node:fs'),crypto=require('node:crypto'),cp=require('node:child_process'),path=require('node:path');
function canonical(v){if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';return JSON.stringify(v);}
function hash(v){return crypto.createHash('sha256').update(v).digest('hex');}
function mac(key,raw){return crypto.createHmac('sha256',key).update(raw).digest('hex');}
function line(){const b=Buffer.alloc(1),out=[];for(let n=0;n<16384;n++){if(fs.readSync(0,b,0,1,null)!==1)throw Error('HOLD');if(b[0]===10)return Buffer.from(out).toString('utf8');out.push(b[0]);}throw Error('HOLD');}
function send(raw){fs.writeSync(1,raw+'\n');}
function sign(key,body){const raw=canonical(body);return '{"body":'+raw+',"mac":'+JSON.stringify(mac(key,raw))+'}';}
function auth(key,raw){const p=JSON.parse(raw);if(Object.keys(p).sort().join(',')!=='body,mac'||typeof p.mac!=='string'||!/^[a-f0-9]{64}$/.test(p.mac))throw Error('HOLD');const expected=Buffer.from(mac(key,canonical(p.body)),'hex');if(!crypto.timingSafeEqual(expected,Buffer.from(p.mac,'hex')))throw Error('HOLD');return p.body;}
function native(pid){
 if(!Number.isSafeInteger(pid)||pid<1||pid>=2**32||process.platform!=='win32')throw Error('HOLD');
 const script="$ErrorActionPreference='Stop';$rows=@(1..2|ForEach-Object {$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+pid+"' -OperationTimeoutSec 3;if(!$p){throw 'Missing owner'};@{pid=[int]$p.ProcessId;parent_pid=[int]$p.ParentProcessId;created=$p.CreationDate.ToUniversalTime().ToString('o');executable=[string]$p.ExecutablePath;command=[string]$p.CommandLine}});ConvertTo-Json -InputObject $rows -Compress";
 const raw=cp.execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{timeout:10000,maxBuffer:131072,windowsHide:true});
 const rows=JSON.parse(raw.toString('utf8').replace(/^\uFEFF/,''));if(!Array.isArray(rows)||rows.length!==2)throw Error('HOLD');
 for(const r of rows){if(r.pid!==pid||!r.command||typeof r.command!=='string'||r.command.length>32768)throw Error('HOLD');r.command_sha256=hash(r.command);delete r.command;}
 if(canonical(rows[0])!==canonical(rows[1]))throw Error('HOLD');return rows[1];
}
function current(body){
 const owner=native(process.pid),parent=native(body.launch.owner.pid);
 if(canonical(owner)!==canonical(body.owner)||canonical(parent)!==canonical(body.launch.owner))throw Error('HOLD');
 const chain=body.lineage||[body.owner];if(!Array.isArray(chain)||chain.length<1||chain.length>4||canonical(chain.at(-1))!==canonical(body.owner))throw Error('HOLD');
 let previous=parent;const seen=new Set([parent.pid]);
 for(const row of chain){if(seen.has(row.pid)||row.parent_pid!==previous.pid||Date.parse(row.created)<Date.parse(previous.created)||canonical(native(row.pid))!==canonical(row))throw Error('HOLD');seen.add(row.pid);previous=row;}
}
function main(){
 if(process.argv.length<3||!path.isAbsolute(process.argv[2]))throw Error('HOLD');
 const target=process.argv[2],args=process.argv.slice(3);
 send(canonical({kind:'genesis-private-child-ready-v1',pid:process.pid}));
 const initial=JSON.parse(line());if(Object.keys(initial).sort().join(',')!=='frame,launch'||typeof initial.frame!=='string'||!/^(?:[a-f0-9]{2})+$/.test(initial.frame))throw Error('HOLD');
 const frame=Buffer.from(initial.frame,'hex').toString('utf8'),marker=frame.lastIndexOf(',"key":"');
 if(!frame.startsWith('{"challenge":')||marker<0||!frame.endsWith('"}'))throw Error('HOLD');
 const bodyRaw=frame.slice(13,marker),keyHex=frame.slice(marker+8,-2);
 if(!/^[a-f0-9]{64}$/.test(keyHex))throw Error('HOLD');
 const body=JSON.parse(bodyRaw),key=Buffer.from(keyHex,'hex');
 const fields=Object.keys(body).sort().join(',');if(!['expires_ns,generation,kind,launch,nonce,owner,service','expires_ns,generation,kind,launch,lineage,nonce,owner,service'].includes(fields)||body.kind!=='genesis-private-child-v1'||body.service!=='web'||body.launch.service!=='web'||!Number.isSafeInteger(body.generation)||body.generation!==body.launch.generation||canonical(body.launch)!==canonical(initial.launch))throw Error('HOLD');
 // Keep Python's exact canonical ns bytes for HMAC. Never reserialize unsafe ints.
 const match=bodyRaw.match(/^\{"expires_ns":([1-9][0-9]*),/);if(!match)throw Error('HOLD');const expiry=BigInt(match[1]);
 // Ceil the local millisecond clock; never extend an exact ns deadline by rounding down.
 function deadline(){const left=expiry-(BigInt(Date.now())+1n)*1000000n;if(left<=0n||left>30000000000n)throw Error('HOLD');}
 deadline();current(body);
 const proof='{"body":'+bodyRaw+',"mac":'+JSON.stringify(mac(key,bodyRaw))+'}';send(proof);
 const processed=auth(key,line()),expected={kind:'genesis-child-processed-v1',target:hash(proof),lifecycle_authorized:false,write_authorized:false};
 if(canonical(processed)!==canonical(expected))throw Error('HOLD');deadline();current(body);
 const completion=sign(key,{kind:'genesis-child-installed-v1',target:hash(proof),lifecycle_authorized:false,write_authorized:false});send(completion);
 if(canonical(auth(key,line()))!==canonical({kind:'genesis-child-confirmed-v1',target:hash(completion)}))throw Error('HOLD');
 deadline();current(body);send(sign(key,{kind:'genesis-child-dispatch-ready-v1',target:hash(completion)}));
 if(canonical(auth(key,line()))!==canonical({kind:'genesis-child-observation-complete-v1',target:hash(completion),lifecycle_authorized:false,write_authorized:false}))throw Error('HOLD');
 deadline();key.fill(0);
 process.argv=[process.execPath,target,...args];require('node:module').runMain(target);
}
module.exports={canonical,auth,native};
if(require.main===module){try{main();}catch{process.stderr.write('Private Node bootstrap/application failed; HOLD\n');process.exitCode=1;}}
