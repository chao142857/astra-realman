const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../gui/app.js'),'utf8');
const ctx={TextEncoder};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('function validatePromptDocuments('),source.indexOf('function renderPromptDocuments(')),ctx);
const files=[{name:'任务.md',content:'# 条件\n<svg onload=alert(1)>'},{name:'x.json',content:'{ "x": 1 }'}];
assert.equal(JSON.stringify(ctx.validatePromptDocuments(files)),JSON.stringify(files));
for(const docs of [[{name:'x.json',content:'{'}],[{name:'a.pdf',content:'x'}],[{name:'x.md',content:'x'.repeat(32769)}],[...files,...files]])assert.throws(()=>ctx.validatePromptDocuments(docs));
assert(source.includes('pre.textContent=d.content'));
console.log('6 prompt file UI assertions passed');
