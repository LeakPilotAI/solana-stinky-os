'use strict';
// Inactive private-stdin Next.js wrapper. Normal desktop startup does not use it.
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const readline = require('node:readline');
const {createRequire} = require('node:module');
function canonical(value) {
  if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
  if(value && typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}

class WebClosure {
  constructor({server, app, key, ownerJson, controller, generation, persist}) {
    if (!Buffer.isBuffer(key) || key.length !== 32 || !/^[a-f0-9]{64}$/.test(controller) ||
        !Number.isSafeInteger(generation) || generation < 1 || typeof persist !== 'function') throw Error('HOLD');
    this.server=server; this.app=app; this.key=key; this.ownerJson=ownerJson;
    this.controller=controller; this.generation=generation; this.persist=persist;
    this.boot=crypto.randomBytes(16).toString('hex'); this.used=false; this.phase='RUNNING';
    this.requests=new Set(); this.failed=false;
  }
  target() {
    return crypto.createHash('sha256').update(JSON.stringify({boot:this.boot,generation:this.generation,owner:this.ownerJson})).digest('hex');
  }
  track(request,response) {
    if (this.phase!=='RUNNING' || this.requests.size>=128) { response.writeHead(503); response.end('Admission fenced'); return false; }
    const token=Symbol();this.requests.add(token);
    let finished=false;
    response.once('finish',()=>{
      finished=true;this.requests.delete(token);
      // Once Node has finished its response bookkeeping, close only verified
      // idle keep-alive sockets. Never close active requests or all connections.
      if(this.phase==='DRAINING' && !this.requests.size && !this.failed)
        setImmediate(()=>this.server.closeIdleConnections?.());
    });
    response.once('close',()=>{if(!finished){this.failed=true;this.phase='HOLD';}this.requests.delete(token);});
    request.once('aborted',()=>{this.failed=true;this.phase='HOLD';});
    return true;
  }
  authenticate(envelope) {
    if (!envelope || Object.keys(envelope).sort().join(',')!=='body_json,mac' ||
        typeof envelope.body_json!=='string' || Buffer.byteLength(envelope.body_json)>16384 ||
        !/^[a-f0-9]{64}$/.test(envelope.mac)) throw Error('HOLD');
    const expected=crypto.createHmac('sha256',this.key).update(envelope.body_json).digest();
    if(!crypto.timingSafeEqual(expected,Buffer.from(envelope.mac,'hex'))) throw Error('HOLD');
    const body=JSON.parse(envelope.body_json);
    if(Object.keys(body).sort().join(',')!=='controller,expires_ns,generation,kind,request_id,target' ||
       body.kind!=='SHUTDOWN' || body.controller!==this.controller || body.target!==this.target() ||
       body.generation!==this.generation || !/^[a-f0-9]{32}$/.test(body.request_id)) throw Error('HOLD');
    // Verify exact authenticated decimal ns from raw canonical body; JSON Number
    // cannot represent native timestamps above2^53 without loss of identity.
    const exact=envelope.body_json.match(/"expires_ns":([0-9]+)(?:,|})/);
    if(!exact) throw Error('HOLD');
    const expires=BigInt(exact[1]);const remaining=expires-BigInt(Date.now())*1000000n;
    if(remaining<=0n || remaining>60000000000n) throw Error('HOLD');
    return {body,expires};
  }
  async receive(envelope) {
    const {body,expires}=this.authenticate(envelope);
    if(this.used || this.phase!=='RUNNING') throw Error('HOLD');
    this.used=true;this.phase='FENCING';
    let timer;let stage='intent';
    try {
      const intent=this.persist({stage:'WEB_STOP_INTENT',request_id:body.request_id,target:this.target()});
      if(!/^[a-f0-9]{64}$/.test(intent)) throw Error('HOLD');
      stage='http-drain';
      const closed=new Promise((resolve,reject)=>this.server.close(err=>err?reject(err):resolve()));
      this.phase='DRAINING';
      const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('HOLD')),
        Math.max(1,Number((expires-BigInt(Date.now())*1000000n)/1000000n)));});
      if(this.closeUpgraded){
        stage='hmr-drain';
        await Promise.race([this.closeUpgraded(),deadline]);
      }
      stage='http-drain';
      await Promise.race([closed,deadline]);
      if(this.requests.size || this.failed || this.phase==='HOLD') throw Error('HOLD');
      stage='application-close';
      await Promise.race([this.app.close(),deadline]);
      if(BigInt(Date.now())*1000000n>=expires) throw Error('HOLD');
      stage='processed-audit';
      const ack={phase:'QUIESCED',request_id:body.request_id,owner_json:this.ownerJson,
        completed_workers:['web-http'],scope:'HTTP_DRAIN_NOT_NATIVE_DESCENDANT_EXIT'};
      const head=this.persist({stage:'WEB_STOP_PROCESSED',request_id:body.request_id,ack});
      if(!/^[a-f0-9]{64}$/.test(head)) throw Error('HOLD');
      this.phase='QUIESCED';
      const reply=canonical({kind:'PROCESSED',controller:body.controller,target:body.target,
        generation:body.generation,request_id:body.request_id,phase:this.phase,ack,delivery_head:head});
      return {body_json:reply,mac:crypto.createHmac('sha256',this.key).update(reply).digest('hex')};
    } catch (_) {this.phase='HOLD';throw Error('HOLD:'+stage);}
    finally {clearTimeout(timer);}
  }
}

// Explicit compatibility with the locally certified development-server version.
// This private wrapper is never used by ordinary startup while integration is off.
function captureOwnedNextWatchers(ownedRequire) {
  if(ownedRequire('next/package.json').version!=='15.5.23')throw Error('HOLD:unsupported-next-lifecycle');
  const watchPath=ownedRequire.resolve('next/dist/compiled/watchpack');
  const OriginalWatch=ownedRequire(watchPath);const watches=new Set();let fenced=false;
  if(typeof OriginalWatch!=='function' || typeof OriginalWatch.prototype.close!=='function')throw Error('HOLD:watcher-custody');
  class OwnedWatch extends OriginalWatch {
    constructor(...args){
      if(fenced || watches.size>=128)throw Error('HOLD:watcher-admission');
      super(...args);watches.add(this);
    }
    close(){super.close();watches.delete(this);}
  }
  require.cache[watchPath].exports=OwnedWatch;
  let upgradedClosed=false;let closeStarted=false;
  return {
    async closeUpgraded(app){
      if(fenced || upgradedClosed || typeof app.init?.closeUpgraded!=='function')
        throw Error('HOLD:bundler-closure');
      fenced=true;
      await app.init.closeUpgraded();
      upgradedClosed=true;
    },
    async close(app,closeApplication){
      if(closeStarted)throw Error('HOLD:duplicate-watcher-closure');
      closeStarted=true;
      if(!upgradedClosed)await this.closeUpgraded(app);
      if(!fenced)throw Error('HOLD:bundler-closure');
      for(const watch of [...watches])watch.close();
      if(watches.size)throw Error('HOLD:watcher-drain');
      await closeApplication();
    }
  };
}

async function main() {
  const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
  let state=null;
  for await(const line of lines) {
    if(Buffer.byteLength(line)>65536) throw Error('HOLD');
    const message=JSON.parse(line);
    if(state===null) {
      const mode=Object.hasOwn(message,'mode')?message.mode:'development';
      if(!['development','production'].includes(mode))throw Error('HOLD:unsupported-mode');
      const allowed=['controller','generation','key_hex','owner_json','port','root','directory','journal'];
      if(Object.hasOwn(message,'mode'))allowed.push('mode');
      if(Object.keys(message).sort().join(',')!==allowed.sort().join(',') ||
         !/^[a-f0-9]{64}$/.test(message.key_hex) || !Number.isSafeInteger(message.port) || message.port<1024 || message.port>65535) throw Error('HOLD');
      const owner=JSON.parse(message.owner_json);
      if(owner.pid!==process.pid || owner.service!=='web') throw Error('HOLD');
      const root=path.resolve(message.root);const directory=path.resolve(message.directory);
      if(root!==path.resolve(__dirname,'..')) throw Error('HOLD');
      const ownedDirectory=path.relative(root,fs.realpathSync(directory));
      if(ownedDirectory.startsWith('..') || path.isAbsolute(ownedDirectory)) throw Error('HOLD');
      const journal=path.resolve(message.journal);const relative=path.relative(path.join(root,'logs'),journal);
      if(relative.startsWith('..') || path.isAbsolute(relative)) throw Error('HOLD');
      const journalParent=path.relative(path.join(root,'logs'),fs.realpathSync(path.dirname(journal)));
      if(journalParent.startsWith('..') || path.isAbsolute(journalParent)) throw Error('HOLD');
      const fd=fs.openSync(journal,'ax');let previous='0'.repeat(64);let sequence=0;let bytes=0;
      const persist=record=>{
        const raw=JSON.stringify({sequence:++sequence,previous_sha256:previous,record});
        const chunk=Buffer.from(raw+'\n');if((bytes+=chunk.length)>1048576) throw Error('HOLD');
        if(fs.writeSync(fd,chunk)!==chunk.length) throw Error('HOLD');fs.fsyncSync(fd);
        previous=crypto.createHash('sha256').update(raw).digest('hex');return previous;
      };
      const next=createRequire(path.join(root,'apps/web/package.json'))('next');
      const ownedRequire=createRequire(path.join(root,'apps/web/package.json'));
      // Production uses only the documented Next custom-server lifecycle.
      // Existing development research remains preserved and inactive.
      const resources=mode==='development'?captureOwnedNextWatchers(ownedRequire):null;
      const app=next({dev:mode==='development',dir:directory,hostname:'127.0.0.1',port:message.port});
      await app.prepare();
      if(resources){
        const originalClose=app.close.bind(app);
        app.close=()=>resources.close(app,originalClose);
      }
      const handler=app.getRequestHandler();
      const server=http.createServer((request,response)=>{
        if(state.track(request,response)) Promise.resolve(handler(request,response)).catch(()=>{state.failed=true;state.phase='HOLD';response.end();});
      });
      state=new WebClosure({server,app,key:Buffer.from(message.key_hex,'hex'),ownerJson:message.owner_json,
        controller:message.controller,generation:message.generation,persist});
      if(resources)state.closeUpgraded=()=>resources.closeUpgraded(app);
      server.on('upgrade',(request,socket)=>{
        const permitted=mode==='development' &&
          state.phase==='RUNNING' &&
          !state.failed &&
          request.url==='/_next/webpack-hmr' &&
          request.method==='GET' &&
          request.headers.upgrade?.toLowerCase()==='websocket' &&
          request.headers.connection?.toLowerCase().split(',').map(s=>s.trim()).includes('upgrade') &&
          request.headers['sec-websocket-version']==='13' &&
          typeof request.headers['sec-websocket-key']==='string';
        if(!permitted){
          if(state.phase==='RUNNING'){
            state.failed=true;
            state.phase='HOLD';
          }
          socket.destroy();
        }
      });
      await new Promise(resolve=>server.listen(message.port,'127.0.0.1',resolve));
      process.stdout.write(JSON.stringify({phase:'READY',target:state.target()})+'\n');
    } else {
      const before=process.getActiveResourcesInfo();
      const reply=await state.receive(message);
      process.stdout.write(JSON.stringify(reply)+'\n');
      try {
        process.stderr.write(JSON.stringify({diagnostic:'owned-web-resources',before,after:process.getActiveResourcesInfo()})+'\n');
      } catch (_) {
        process.stderr.write('Genesis resource diagnostic unavailable\n');
      }
      if(state.phase==='QUIESCED'){lines.close();return;}
    }
  }
  throw Error('HOLD');
}

module.exports={WebClosure,captureOwnedNextWatchers};
if(require.main===module) main().catch(()=>{process.stderr.write('Genesis web lifecycle HOLD; no forced cleanup\n');process.exitCode=1;});
