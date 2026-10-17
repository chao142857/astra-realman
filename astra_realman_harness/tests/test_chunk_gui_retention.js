// Same state polling must retain expanded operation receipts.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const s=fs.readFileSync(path.join(__dirname,'../gui/app.js'),'utf8');
const code=s.slice(s.indexOf('function renderChunk('),s.indexOf("$('chunk-run').addEventListener"));
let replaced=0;const root={dataset:{},replaceChildren(){replaced++;},append(){}};
const document={createElement(){return {append(){}};}};
const ctx={document,$:()=>root};vm.createContext(ctx);vm.runInContext(code,ctx);
const state={step:'step-1',operations:[{operation_id:'s00-o00-left',mode:'sequential',status:'FAKE_EXECUTED'}]};
ctx.renderChunk(state);assert.equal(replaced,1);
ctx.renderChunk(JSON.parse(JSON.stringify(state)));assert.equal(replaced,1);
state.operations[0].status='STOPPED';ctx.renderChunk(state);assert.equal(replaced,2);
console.log('3 chunk DOM retention assertions passed');
