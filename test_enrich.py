import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import daily,enrich
class EnrichTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.data=self.root/'data';self.folder=self.root/'private';self.folder.mkdir();self.item='item_'+'a'*16;self.fp='b'*20
  self.packet={'item':{'id':self.item,'kind':'paper','title':'Public paper','url':'https://arxiv.org/abs/2611.07222'},'fingerprint':self.fp,'source_version':'v2','requested_version':'v2','required_sections':['Method'],'sources':[{'id':'s1','url':'https://arxiv.org/html/2611.07222v2','label':'Paper','sha256':'c'*64,'file':'s1.txt'}]}
  self.draft={'schema_version':1,'item_id':self.item,'fingerprint':self.fp,'status':'partial','model':'Codex test','verdict':'Read','overview':'Evidence based','sections':[{'title':'Method','paragraphs':['Explanation'],'refs':[{'source':'s1','locator':'S3'}]}],'limitations':['Not reproduced'],'checks':['Read text']}
  self.p=self.folder/'packet.json';daily.atomic_json(self.p,self.packet);self.d=self.folder/'draft.json';self.mock=patch.object(enrich,'ANALYSES',self.data/'analyses');self.mock.start()
 def tearDown(self):self.mock.stop();self.temp.cleanup()
 def accept(self,draft=None):daily.atomic_json(self.d,draft or self.draft);return enrich.accept(self.p,self.d)
 def test_accept_validates_public_record(self):
  self.accept();self.assertEqual(enrich.validate_public(self.data)['entries'],1)
 def test_invented_source_rejected(self):
  d=copy.deepcopy(self.draft);d['sections'][0]['refs'][0]['source']='imaginary'
  with self.assertRaises(ValueError):self.accept(d)
 def test_private_path_rejected(self):
  d=copy.deepcopy(self.draft);d['overview']='C:/Users/private/note'
  with self.assertRaises(ValueError):self.accept(d)
 def test_private_top_field_rejected(self):
  d=copy.deepcopy(self.draft);d['cookie']='private'
  with self.assertRaises(ValueError):self.accept(d)
 def test_changed_version_rejected(self):
  d=copy.deepcopy(self.draft);d['fingerprint']='d'*20
  with self.assertRaises(ValueError):self.accept(d)
 def test_https_public_text_allowed(self):
  self.assertEqual(enrich.plain('See https://arxiv.org/abs/2611.07222'),'See https://arxiv.org/abs/2611.07222')
 def test_index_cannot_export_local_path(self):
  self.accept();p=self.data/'analyses/index.json';d=enrich.read(p);next(iter(d['items'].values()))['message']='E:/private/data';daily.atomic_json(p,d)
  with self.assertRaises(ValueError):enrich.validate_public(self.data)
 def test_analysis_path_traversal_rejected(self):
  self.accept();p=self.data/'analyses/index.json';d=enrich.read(p);next(iter(d['items'].values()))['path']='data/analyses/../../private.json';daily.atomic_json(p,d)
  with self.assertRaises(ValueError):enrich.validate_public(self.data)
if __name__=='__main__': unittest.main()
