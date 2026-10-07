// Pure display selection tests. No browser/server/robot calls.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../gui/app.js'),'utf8');
const fn=source.slice(source.indexOf('function activeStep()'),source.indexOf('function renderCameras('));
const old={step:'step-001',arms:{},dispatch_started:true,status:'COMPLETED'};
const pending={step:'step-002',arms:{},dispatch_started:false,status:'PREFLIGHT',executed_command:{left:{},right:{}}};
const ctx={state:{steps:[old,pending],latest:pending},selectedStep:'latest'};vm.createContext(ctx);vm.runInContext(fn,ctx);
assert.equal(ctx.activeStep().step,'step-001');
pending.dispatch_started=true;assert.equal(ctx.activeStep().step,'step-002');
pending.dispatch_started=false;pending.status='REJECTED_IK';assert.equal(ctx.activeStep().step,'step-002');
ctx.selectedStep='step-001';assert.equal(ctx.activeStep().step,'step-001');
console.log('4 decision retention assertions passed');
