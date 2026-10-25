'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const http=require('node:http');
const {WebClosure}=require('../scripts/genesis_web_lifecycle.cjs');

function fixture(server={close:fn=>fn()},app={close:async()=>{}},persist=()=> 'a'.repeat(64)) {
  return new WebClosure({server,app,key:crypto.randomBytes(32),ownerJson:'{"service":"web"}',
    controller:'b'.repeat(64),generation:1,persist});
}
function request(gate,changes={},ttl=2000) {
  const body={controller:gate.controller,expires_ns:String(BigInt(Date.now()+ttl)*1000000n),
    generation:1,kind:'SHUTDOWN',request_id:'c'.repeat(32),target:gate.target(),...changes};
  const raw='{'+Object.keys(body).sort().map(k=>JSON.stringify(k)+':'+
    (k==='expires_ns'?body[k]:JSON.stringify(body[k]))).join(',')+'}';
  return {body_json:raw,mac:crypto.createHmac('sha256',gate.key).update(raw).digest('hex')};
}

test('real HTTP request completes before processed acknowledgment',async()=>{
  let release,entered;const ready=new Promise(resolve=>entered=resolve);
  let closeCalls=0;let gate;
  const server=http.createServer((req,res)=>{if(gate.track(req,res)){entered();release=()=>res.end('done');}});
  gate=fixture(server,{close:async()=>{closeCalls++;}});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const response=new Promise((resolve,reject)=>http.get({host:'127.0.0.1',port:server.address().port},res=>{
    res.resume();res.on('end',()=>resolve(res.statusCode));}).on('error',reject));
  response.catch(()=>{}); // Preserve rejection for assertions; avoid a premature unhandled event.
  await ready;let completed=false;let error;
  const envelope=request(gate);const shutdown=gate.receive(envelope).then(reply=>{completed=true;return reply;},err=>{console.error(err.stack);error=err;return null;});
  try {
    await new Promise(resolve=>setTimeout(resolve,30));assert.ifError(error);assert.equal(completed,false);assert.equal(closeCalls,0);
    release();assert.equal(await response,200);const reply=await shutdown;assert.ifError(error);
    assert.equal(gate.requests.size,0);assert.equal(closeCalls,1);
    assert.equal(JSON.parse(reply.body_json).phase,'QUIESCED');
    assert.equal(reply.mac,crypto.createHmac('sha256',gate.key).update(reply.body_json).digest('hex'));
    await assert.rejects(gate.receive(envelope),/HOLD/);
  } finally {
    release();await response.catch(()=>{});await shutdown;
    await new Promise(resolve=>server.close(()=>resolve()));
  }
});

for(const failure of ['mac','target','generation','expiry','controller','unknown']) {
  test('unauthorized '+failure+' cannot close server',async()=>{
    let calls=0;const gate=fixture({close:fn=>{calls++;fn();}});
    const changes={target:{target:'e'.repeat(64)},generation:{generation:2},
      expiry:{expires_ns:'1'},controller:{controller:'f'.repeat(64)},unknown:{extra:true}}[failure]||{};
    const envelope=request(gate,changes);if(failure==='mac')envelope.mac='0'.repeat(64);
    await assert.rejects(gate.receive(envelope),/HOLD/);assert.equal(calls,0);
    assert.equal(gate.used,false);
  });
}

for(const failure of ['intent','processed','application','timeout','unaccounted']) {
  test('incomplete '+failure+' evidence retains HOLD',async()=>{
    let records=0;
    const gate=fixture({close:fn=>{if(failure!=='timeout')fn();}},
      {close:async()=>{if(failure==='application')throw Error('fail');}},
      ()=>{records++;return failure==='intent'||(failure==='processed'&&records===2)?null:'a'.repeat(64);});
    if(failure==='unaccounted')gate.requests.add(Symbol());
    await assert.rejects(gate.receive(request(gate,{},200)),/HOLD/);
    assert.equal(gate.phase,'HOLD');assert.equal(gate.used,true);
  });
}

test('new receiver cannot accept old boot-scoped request',async()=>{
  const old=fixture();const envelope=request(old);const fresh=fixture();fresh.key=old.key;
  await assert.rejects(fresh.receive(envelope),/HOLD/);assert.equal(fresh.used,false);
});
const {captureOwnedNextWatchers}=require('../scripts/genesis_web_lifecycle.cjs');
function watchedFixture({version='15.5.23',failClose=false}={}){
  const id='genesis-owned-watch-fixture-'+crypto.randomBytes(8).toString('hex');
  const closed=[];class Watch{constructor(name){this.name=name;}close(){if(failClose)throw Error('watch-close');closed.push(this.name);}}
  require.cache[id]={exports:Watch};
  const owned=name=>name==='next/package.json'?{version}:require.cache[id].exports;
  owned.resolve=()=>id;
  return {resources:()=>captureOwnedNextWatchers(owned),create:name=>new (require.cache[id].exports)(name),closed,id};
}
test('owned Next watchers close before application settlement and new watchers are fenced',async()=>{
  const fixture=watchedFixture();const resources=fixture.resources();fixture.create('source');fixture.create('compiler');
  const order=[];await resources.close({init:{closeUpgraded:()=>order.push('middleware')}},async()=>{assert.deepEqual(fixture.closed,['source','compiler']);order.push('application');});
  assert.deepEqual(order,['middleware','application']);assert.throws(()=>fixture.create('after-boundary'),/HOLD/);
  await assert.rejects(resources.close({init:{closeUpgraded:()=>{}}},async()=>{}),/HOLD/);
});
test('unsupported Next version cannot capture or close watchers',()=>{
  const fixture=watchedFixture({version:'99.0.0'});const before=require.cache[fixture.id].exports;
  assert.throws(()=>fixture.resources(),/HOLD/);assert.equal(require.cache[fixture.id].exports,before);
});
test('watcher closure error prevents application settlement',async()=>{
  const fixture=watchedFixture({failClose:true});const resources=fixture.resources();fixture.create('source');let settled=false;
  await assert.rejects(resources.close({init:{closeUpgraded:()=>{}}},async()=>{settled=true;}),/watch-close/);
  assert.equal(settled,false);assert.throws(()=>fixture.create('after-failure'),/HOLD/);
});
test('unknown development bundler closure remains HOLD',async()=>{
  const fixture=watchedFixture();const resources=fixture.resources();fixture.create('source');
  await assert.rejects(resources.close({init:{}},async()=>{}),/HOLD/);assert.deepEqual(fixture.closed,[]);
});
test('watcher custody is bounded before constructing another watcher',()=>{
  const fixture=watchedFixture();fixture.resources();for(let i=0;i<128;i++)fixture.create(i);
  assert.throws(()=>fixture.create('overflow'),/HOLD/);
});
