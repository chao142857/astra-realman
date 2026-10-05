import copy, json, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from history5_context import History5ContextBuilder
from io_utils import ROOT,read_json
from left_terminal import select_replay,model_input,SCHEMA_PATH

class HistoryTests(unittest.TestCase):
    def make(self):
        return History5ContextBuilder(lambda obs,schema:copy.deepcopy(obs))
    def obs(self,n):
        return {"observation_id":str(n),"task":"unchanged",
                "previous":None if n==1 else {"last_action":{"value":n-1},
                "last_result":{"status":"REJECTED_IK" if n==3 else "EXECUTED","original_target":[n-1,0,0]}}}
    def test_first_empty(self):
        self.assertEqual(self.make()(self.obs(1),{})["history"],[])
    def test_five_order_and_eviction(self):
        b=self.make()
        for n in range(1,9):c=b(self.obs(n),{})
        self.assertEqual([x["last_action"]["value"] for x in c["history"]],[3,4,5,6,7])
    def test_rejection_retained(self):
        b=self.make()
        for n in range(1,5):c=b(self.obs(n),{})
        self.assertEqual(c["history"][1]["last_result"]["status"],"REJECTED_IK")
        self.assertEqual(c["history"][1]["last_result"]["original_target"],[2,0,0])
    def test_input_and_existing_fields_unchanged(self):
        b=self.make();o=self.obs(2);saved=copy.deepcopy(o);c=b(o,{})
        self.assertEqual(o,saved)
        self.assertEqual({k:v for k,v in c.items() if k!="history"},saved)
        o["previous"]["last_action"]["value"]=999
        c["history"][0]["last_action"]["value"]=777
        self.assertEqual(b(self.obs(3),{})["history"][0]["last_action"]["value"],1)
    def test_same_observation_not_duplicated(self):
        b=self.make();o=self.obs(2);b(o,{})
        self.assertEqual(len(b(o,{})["history"]),1)
    def test_new_episode_empty(self):
        b=self.make();b(self.obs(2),{})
        self.assertEqual(self.make()(self.obs(1),{})["history"],[])
    def test_repeated_equal_actions_not_deduplicated(self):
        b=self.make()
        for n in range(1,8):
            o=self.obs(n)
            if o["previous"]:o["previous"]["last_action"]={"value":1}
            c=b(o,{})
        self.assertEqual(len(c["history"]),5)
    def test_actual_threeview_context(self):
        src=read_json(ROOT/"logs/left-fourview-20261005T115659Z-8c246671/step-01/input/observation.json")
        obs=select_replay(src,read_json(ROOT/"config/left_terminal.json"),"unchanged task",None)
        schema=read_json(SCHEMA_PATH);base=model_input(obs,schema)
        b=History5ContextBuilder(model_input);got=b(obs,schema)
        self.assertEqual({k:v for k,v in got.items() if k!="history"},base)
        self.assertEqual(len(got["images_in_attachment_order"]),3)
        for n in range(2,8):
            obs=copy.deepcopy(obs);obs["observation_id"]=str(n)
            obs["previous"]=self.obs(n)["previous"]
            got=b(obs,schema)
        self.assertEqual(len(got["history"]),5)
        self.assertEqual(len(got["images_in_attachment_order"]),3)
        self.assertEqual(got["action_schema"],schema)
        self.assertEqual(got["task"],"unchanged task")

if __name__=="__main__":unittest.main()
