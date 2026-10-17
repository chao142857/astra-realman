const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../gui/app.js'),'utf8');
const handlers={},nodes={};const node=id=>nodes[id]??=( {value:'',disabled:false,textContent:'',children:[],replaceChildren(){this.children=[];},append(...x){this.children.push(...x);},addEventListener(type,fn){handlers[id+':'+type]=fn;}} );
const ctx={TextEncoder,TextDecoder,state:{active:false},pending:false,promptDocuments:[],importingDocuments:false,$:node,text:(id,t)=>node(id).textContent=t,toast:()=>{},document:{createElement:()=>({append(){}})}};
vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('function validatePromptDocuments(')),ctx);
(async()=>{
 const input=node('prompt-files');input.value='C:/fakepath/banana_handoff_v1.md';
 const content='# Task\n原始文件内容';input.files=[{name:'banana_handoff_v1.md',size:new TextEncoder().encode(content).length,arrayBuffer:async()=>new TextEncoder().encode(content).buffer}];
 await handlers['prompt-files:change']({target:input});
 assert(input.value.endsWith('banana_handoff_v1.md'));assert.equal(ctx.promptDocuments[0].content,content);assert(node('prompt-files-status').textContent.includes('已导入 1'));
 input.files=[{name:'bad.json',size:1,arrayBuffer:async()=>new TextEncoder().encode('{').buffer}];await handlers['prompt-files:change']({target:input});
 assert.equal(ctx.promptDocuments.length,1);assert(node('prompt-files-status').textContent.includes('导入失败'));
 handlers['clear-prompt-files:click']();assert.equal(input.value,'');assert.equal(ctx.promptDocuments.length,0);
 console.log('7 file-selection success/failure/clear assertions passed; no model or hardware');
})().catch(e=>{console.error(e);process.exitCode=1;});
