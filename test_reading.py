import copy,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
import daily,reading,enrich
NOW=datetime(2026,11,23,8,tzinfo=timezone.utc)
class ReadingTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'data';self.config=json.loads((daily.ROOT/'config.json').read_text(encoding='utf-8'));self.state=daily.empty_state();self.index={'schema_version':1,'updated_at':daily.stamp(NOW),'items':{}}
 def tearDown(self):self.temp.cleanup()
 def add(self,name='one',version='v1',kind='paper',stars=200,note=True,substantial=False,updated=None,code=True):
  url='https://github.com/test/'+name if kind=='repo' else 'https://arxiv.org/abs/2611.'+str(sum(map(ord,name))).zfill(5)
  raw={'kind':kind,'url':url,'title':'Memory poisoning '+name,'summary':'Memory poisoning research','source':'GitHub' if kind=='repo' else 'arXiv','updated_at':updated or daily.stamp(NOW-timedelta(days=1)),'published_at':daily.stamp(NOW-timedelta(days=2)),'stars':stars}
  if kind=='paper':raw['version']=version
  item=daily.public_item(raw);self.state['items'][item['id']]=item
  reports=self.data/'reports';reports.mkdir(parents=True,exist_ok=True);rp=reports/'2026-11-22.json';r=reading.read(rp,{'date':'2026-11-22','items':{'paper':[],'repo':[],'news':[]}});r['items'][kind].append(item);daily.atomic_json(rp,r)
  if note:
   fp=__import__('hashlib').sha256((name+version+str(updated)).encode()).hexdigest()[:20];path='data/analyses/'+item['id']+'-'+fp+'.json'
   recommendation={'headline':'中文标题','why_read':'解释记忆如何获得权限','read_next':'方法与表 1','update_summary':'新增了独立评测' if substantial else '', 'substantive_update':substantial}
   value={'schema_version':1,'item_id':item['id'],'kind':kind,'title':item['title'],'url':item['url'],'fingerprint':fp,'version':('a'*40 if kind=='repo' else version),'status':'partial','model':'Codex','generated_at':daily.stamp(NOW),'verdict':'值得读','overview':'具体内容','sections':[],'limitations':[],'checks':[],'recommendation':recommendation,'sources':[{'id':'s1','url':('https://github.com/test/'+name+'/blob/'+'a'*40+'/src/guard.py') if kind=='repo' and code else url,'label':'source','sha256':'a'*64}]}
   daily.atomic_json(self.data/'analyses'/Path(path).name,value);self.index['items'][item['id']+':'+fp]={'item_id':item['id'],'kind':kind,'title':item['title'],'fingerprint':fp,'version':value['version'],'requested_version':reading.version(item),'status':'partial','updated_at':daily.stamp(NOW),'path':path,'message':'值得读'}
  daily.atomic_json(self.data/'analyses/index.json',self.index);daily.atomic_json(self.data/'state.json',self.state);return item
 def sync(self,day=0):return reading.sync(self.data,NOW+timedelta(days=day),self.config)
 def test_same_version_never_becomes_daily_new_again(self):
  r=self.add();first=self.sync();self.sync();second=self.sync(1)
  self.assertEqual(first['editions']['2026-11-23']['items']['paper'],[reading.key(r)])
  self.assertEqual(second['editions']['2026-11-24']['items']['paper'],[])
 def test_repeated_sync_with_no_changes_does_not_rewrite_index(self):
  self.add();self.sync();p=self.data/'library.json';before=p.read_bytes();reading.sync(self.data,NOW+timedelta(minutes=5),self.config);self.assertEqual(p.read_bytes(),before)
 def test_unknown_new_version_is_an_update_not_automatically_featured(self):
  self.add();self.sync();self.add(version='v2');v=self.sync(1);self.assertEqual(v['editions']['2026-11-24']['items']['paper'],[])
 def test_reviewed_minor_update_does_not_starve_the_next_batch(self):
  self.add();self.sync();r=self.add(version='v2');self.sync(1)
  self.assertEqual(reading.candidates(self.config,self.state,[r['id']],self.data,NOW+timedelta(days=1))['paper'],[])
 def test_verified_substantive_update_can_feature_again(self):
  self.add();self.sync();r=self.add(version='v2',substantial=True);v=self.sync(1);self.assertEqual(v['editions']['2026-11-24']['items']['paper'],[reading.key(r)])
 def test_recently_discovered_old_paper_is_library_only(self):
  self.add(updated=daily.stamp(NOW-timedelta(days=60)));v=self.sync();self.assertEqual(len(v['items']),1);self.assertEqual(v['editions']['2026-11-23']['items']['paper'],[])
 def test_metadata_only_does_not_become_featured(self):
  self.add(note=False);self.assertEqual(self.sync()['editions']['2026-11-23']['items']['paper'],[])
 def test_no_more_than_three_papers_and_one_project(self):
  for n in range(5):self.add(str(n));self.add('repo'+str(n),kind='repo')
  v=self.sync();self.assertEqual(len(v['editions']['2026-11-23']['items']['paper']),3);self.assertEqual(len(v['editions']['2026-11-23']['items']['repo']),1)
 def test_stars_alone_do_not_create_a_new_project_edition(self):
  self.add(kind='repo');self.sync();self.add(kind='repo',stars=5000);self.assertEqual(self.sync(1)['editions']['2026-11-24']['items']['repo'],[])
 def test_readme_only_or_low_star_project_stays_out_of_picks(self):
  self.add(kind='repo',code=False);self.add('low',kind='repo',stars=0);self.assertEqual(self.sync()['editions']['2026-11-23']['items']['repo'],[])
 def test_verified_paper_code_exception_is_explicit(self):
  r=self.add(kind='repo',stars=0);self.config['verified_paper_repos']={'test/one':'https://arxiv.org/abs/2611.12345'};v=self.sync();self.assertEqual(v['editions']['2026-11-23']['items']['repo'],[reading.key(r)])
 def test_private_extra_fields_and_paths_are_rejected(self):
  self.add();v=self.sync();v['items'][0]['private_note']='secret'
  with self.assertRaises(ValueError):reading.validate_catalog(v)
  v=self.sync();v['items'][0]['analysis']['recommendation']['why_read']='E:/private/notes'
  with self.assertRaises(ValueError):reading.validate_catalog(v)
 def test_original_report_is_never_rewritten(self):
  self.add();p=self.data/'reports/2026-11-22.json';before=p.read_bytes();self.sync();self.assertEqual(p.read_bytes(),before)
 def test_featured_version_survives_report_replacement_and_new_snapshot(self):
  old=self.add(kind='repo');first=self.sync();new=self.add(kind='repo',updated=daily.stamp(NOW))
  p=self.data/'reports/2026-11-22.json';report=reading.read(p);report['items']['repo']=[new];daily.atomic_json(p,report)
  second=self.sync(1);known={r['record_key'] for r in second['items']}
  self.assertIn(reading.key(old),known);self.assertIn(reading.key(new),known)
  self.assertEqual(second['editions']['2026-11-23'],first['editions']['2026-11-23'])
  self.assertEqual(second['editions']['2026-11-24']['items']['repo'],[])
 def test_preserved_catalog_rejects_private_fields_before_merge(self):
  self.add();self.sync();p=self.data/'library.json';value=reading.read(p);value['items'][0]['private_note']='secret';daily.atomic_json(p,value)
  with self.assertRaises(ValueError):self.sync(1)
 def test_next_batch_skips_already_featured_version(self):
  r=self.add();self.sync();self.assertEqual(reading.candidates(self.config,self.state,[r['id']],self.data,NOW)['paper'],[])
if __name__=='__main__':unittest.main()
