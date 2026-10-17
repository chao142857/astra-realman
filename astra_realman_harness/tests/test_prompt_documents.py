import sys,unittest,copy,json,shlex,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prompt_documents import validate_documents,snapshot_documents,attach_documents
from experiment_launch import validate,runner_args
from launch_provenance import equivalent_command
from parallel_history import ParallelHistory
class PromptDocuments(unittest.TestCase):
 def docs(self):return [{'name':'任务.md','content':'# 约束\n保持原始文本\n'}, {'name':'scene.json','content':'{ "value": 2, "note": "原样" }'}]
 def test_full_text_survives_history_rollover(self):
  frozen=snapshot_documents(self.docs());h=ParallelHistory()
  for i in range(12):
   c=attach_documents({'history':h.context()},frozen)
   self.assertEqual([d['content'] for d in c['user_prompt_documents']],[d['content'] for d in self.docs()])
   self.assertEqual(c['user_prompt_documents'][0]['sha256'],hashlib.sha256(self.docs()[0]['content'].encode()).hexdigest())
   c['user_prompt_documents'][0]['content']='mutated';h.append({'step':i})
  self.assertEqual(frozen[0]['content'],self.docs()[0]['content'])
 def test_empty_preserves_old_input(self):
  self.assertEqual(attach_documents({'task':'x'},[]),{'task':'x'})
 def test_launch_preserves_docs_and_command_is_shell_quoted(self):
  docs=self.docs();docs[0]['content']+='$(touch /tmp/never) `echo never`'
  s=validate({'profile':'parallel','task':'test','prompt_documents':docs})
  args=runner_args(s);self.assertEqual(json.loads(args[args.index('--prompt-documents-json')+1]),docs)
  args=shlex.split(equivalent_command(s));self.assertEqual(json.loads(args[args.index('--prompt-documents-json')+1]),docs)
 def test_reject_not_silent_ignore(self):
  with self.assertRaises(ValueError):validate({'task':'test','profile':'legacy1','prompt_documents':self.docs()})
 def test_bad_content(self):
  for d in [[{'name':'x.json','content':'{'}],[{'name':'x.json','content':'NaN'}],[{'name':'../x.md','content':'x'}],[{'name':'x.pdf','content':'x'}],[{'name':'x.txt','content':'\x00'}],[{'name':'x.txt','content':'x'*32769}],self.docs()*2,[{'name':str(i)+'.md','content':'x'*10000} for i in range(7)]]:
   with self.subTest(d=str(d)[:30]):
    with self.assertRaises(ValueError):validate_documents(d)
 def test_runner_attaches_before_serialization_and_call(self):
  s=(Path(__file__).resolve().parents[1]/'scripts/run_parallel_arms.py').read_text()
  self.assertLess(s.index('attach_documents(context_json,documents)'),s.index("write_json(step/'model_input.json'"))
  self.assertLess(s.index('attach_documents(context_json,documents)'),s.index('raw=call_astra('))
