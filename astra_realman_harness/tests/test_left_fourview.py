import copy,json,sys,unittest,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json
import left_terminal as three
import left_terminal_fourview as four
from left_preview_fourview import Preview
from decision_backends import codex_command
class FourViews(unittest.TestCase):
 def setUp(self):
  self.config=read_json(ROOT/'config/left_terminal_fourview.json')
  self.source=read_json(ROOT/'logs/auto-pick-20261002T134809Z-ed07af0a/step-01/observation.json')
  self.obs=four.select_replay(self.source,self.config,'exact user task',None)
  self.schema=read_json(four.SCHEMA_PATH)
 def test_live_config(self):self.assertEqual(len(four.camera_config(self.config,live=True)),4)
 def test_model_four_left_only(self):
  c=four.model_input(self.obs,self.schema)
  self.assertEqual(len(c['images_in_attachment_order']),4)
  self.assertEqual(c['images_in_attachment_order'][-1]['serial'],'348522072063')
  self.assertEqual(set(c['robot_states']),{'left'})
 def test_same_input_except_extra_image(self):
  o=three.select_replay(self.source,read_json(ROOT/'config/left_terminal.json'),'exact user task',None)
  a=three.model_input(o,self.schema);b=four.model_input(self.obs,self.schema)
  b['images_in_attachment_order']=b['images_in_attachment_order'][:3]
  self.assertEqual(a,b)
 def test_missing_image_reject(self):
  self.obs['cameras'].pop()
  with self.assertRaises(ValueError):four.model_input(self.obs,self.schema)
 def test_four_cli_image_flags(self):
  c=four.model_input(self.obs,self.schema);cfg=read_json(ROOT/'config/decision_backend.json')
  command=codex_command(cfg['executable'],'gpt-6-astra',c['images_in_attachment_order'],ROOT/'logs/unused-offline-command-preview',cfg['provider'],schema=four.SCHEMA_PATH)
  self.assertEqual(command.count('--image'),4)
 def test_fourth_preview(self):
  with Preview(self.config['cameras'],0) as p:
   p.update(self.obs);url='http://127.0.0.1:'+str(p.server.server_port)
   self.assertTrue(urllib.request.urlopen(url+'/view/3').read().startswith(b'\x89PNG'))
 def test_shared_action_semantics(self):
  a=json.dumps(read_json(ROOT/'tests/left_opening_fixture.json'))
  self.assertEqual(three.parse(a),four.parse(a))
  state=self.obs['canonical_states']['left']
  self.assertEqual(three.command_plan(three.parse(a),state),four.command_plan(four.parse(a),state))
if __name__=='__main__':unittest.main()
