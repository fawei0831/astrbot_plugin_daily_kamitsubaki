import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from build_catalog import Client, StopCollection, collect, export, match, read, write, wbi_params, video_artists


class Opener:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())


class Tests(unittest.TestCase):
    def test_official_first_fan_fallback_and_cover_singer(self):
        self.assertEqual(video_artists('道化師ブランケット / VALIS Covered by CIEL【神椿】'), ['ciel'])
        self.assertEqual(video_artists('曲子 covered by 琶舞'), [])
        write(self.root/'songs.json', [dict(id=x,title=t,artist='花譜',artists=['kaf'],bvid='') for x,t in [('a','魔女'),('b','雛鳥')]])
        write(self.root/'videos.json',[
            dict(bvid='BV1234567890',title='「魔女」',artist='kaf',source_type='fan'),
            dict(bvid='BV1234567891',title='「魔女」Live Ver.',artist='kaf',source_type='official'),
            dict(bvid='BV1234567892',title='「雛鳥」',artist='kaf',source_type='fan')])
        match(SimpleNamespace(work=self.root))
        self.assertEqual({r['bvid'] for r in read(self.root/'preferred.json')},{'BV1234567891','BV1234567892'})
        self.assertEqual(len(read(self.root/'review.json')),2)

    def test_previews_and_remix_versions_are_not_false_matches(self):
        write(self.root/'songs.json', [
            dict(id='a',title='魔女',artist='花譜',artists=['kaf'],bvid=''),
            dict(id='b',title='魔女(制作人 Remix)',artist='花譜',artists=['kaf'],bvid='')])
        write(self.root/'videos.json', [
            dict(bvid='BV1234567890',title='「魔女」MV即将公开',artist='kaf'),
            dict(bvid='BV1234567891',title='「魔女」Live Ver.',artist='kaf')])
        match(SimpleNamespace(work=self.root))
        review=read(self.root/'review.json')
        self.assertEqual([(v['song_id'],v['bvid']) for v in review],[('a','BV1234567891')])

    def test_wbi_known_vector(self):
        result = wbi_params({'foo': '114', 'bar': '514', 'zab': 1919810},
            '7cd084941338484aae1ad9425b84077c', '4932caff0ff746eab6f01bf08b70ac45', 1702204169)
        self.assertEqual(result['w_rid'], '8f6f2b5b3d485fe1886cec6a0be8c5d4')

    def test_signed_page_cache_and_pause(self):
        nav = {'code': -101, 'data': {'wbi_img': {
            'img_url': 'https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png',
            'sub_url': 'https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png'}}}
        op = Opener([nav, {'code': 0, 'data': {'list': {'vlist': []}}}])
        c = self.client(op)
        c.space_page('123', 1)
        c.sleep(10)
        c.space_page('123', 1)
        self.assertEqual(op.calls, 2)
        c.put_state('paused_until', c.clock() + 86400)
        with self.assertRaises(StopCollection): c.space_page('123', 2)
        self.assertEqual(op.calls, 2)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.db.close()
        self.tmp.cleanup()

    def client(self, opener, budget=10):
        now = [1000000.0]
        def sleep(seconds):
            now[0] += seconds
        c = Client(self.root / 'state.db', budget, 8, opener, lambda: now[0], sleep)
        self.clients.append(c)
        return c

    def test_cache_budget_and_spacing(self):
        op = Opener([{'code': 0, 'data': {}}, {'code': 0, 'data': {}}])
        c = self.client(op, budget=2)
        c.get('/test', {'p': 1}); c.get('/test', {'p': 1})
        self.assertEqual(op.calls, 1)
        c.get('/test', {'p': 2})
        self.assertGreaterEqual(c.clock(), 1000008)
        with self.assertRaises(StopCollection): c.get('/test', {'p': 3})
        self.assertEqual(op.calls, 2)

    def test_protection_persists_across_restart(self):
        for code in (-352, -412, -799):
            c = self.client(Opener([{'code': code}]))
            with self.assertRaises(StopCollection): c.get('/test', {'p': code})
            self.assertGreaterEqual(c.state('paused_until'), 1086400)
            c.db.execute('DELETE FROM state'); c.db.commit()
        c = self.client(Opener([urllib.error.HTTPError('https://example', 429, 'limited', {'Retry-After': '172800'}, None)]))
        with self.assertRaises(StopCollection): c.get('/test', {})
        op = Opener([]); second = self.client(op)
        with self.assertRaises(StopCollection): second.get('/test', {})
        self.assertEqual(op.calls, 0)
        self.assertGreaterEqual(second.state('paused_until'), 1172800)

    def test_network_error_not_retried(self):
        op = Opener([urllib.error.URLError('offline')]); c = self.client(op)
        with self.assertRaises(StopCollection): c.get('/test', {})
        self.assertEqual(op.calls, 1)

    def test_pagination_resumes_without_fetching_first_page_again(self):
        channels = self.root/'channels.json'
        write(channels, [{'artist':'kaf','mid':'123'}])
        def page(bvid):
            return {'code':0,'data':{'list':{'vlist':[{'bvid':bvid,'title':'Song','mid':123,'pic':''}]},'page':{'count':60}}}
        args = SimpleNamespace(work=self.root, channels=channels, max_requests=1, interval=8)
        first = Opener([page('BV1234567890')]); c = self.client(first, budget=1)
        c.space_page = lambda mid, pn: c.get('/test', {'mid': mid, 'pn': pn})
        with patch('build_catalog.Client', return_value=c): collect(args)
        self.assertEqual(first.calls, 1)
        second = Opener([page('BV1234567891')]); c = self.client(second, budget=1)
        c.space_page = lambda mid, pn: c.get('/test', {'mid': mid, 'pn': pn})
        with patch('build_catalog.Client', return_value=c): collect(args)
        self.assertEqual(second.calls, 1)
        self.assertEqual(len(read(self.root/'videos.json')), 2)

    def test_review_required_and_merge_preserves_existing(self):
        songs = [{'id': 'a', 'title': '魔女', 'artist': '花譜', 'artists': ['kaf'], 'bvid': ''}]
        videos = [dict(bvid='BV1234567890', title='【花譜】「魔女」原创歌曲', artist='kaf'),
                  dict(bvid='BV1234567891', title='「魔女」切片', artist='kaf'),
                  dict(bvid='BV1234567892', title='「魔女」', artist='rim')]
        write(self.root/'songs.json', songs); write(self.root/'videos.json', videos)
        match(SimpleNamespace(work=self.root))
        review = read(self.root/'review.json')
        self.assertEqual(len(review), 1); self.assertFalse(review[0]['approved'])
        base = self.root/'base.json'; write(base, [{'id':'old','title':'Existing','bvid':'BV1234567899'}])
        args = SimpleNamespace(work=self.root, base=base, review=self.root/'review.json', output=self.root/'new.json')
        export(args); self.assertEqual(len(read(args.output)), 1)
        review[0]['approved'] = True; write(args.review, review)
        export(args); self.assertEqual(len(read(args.output)), 2)
        args.output = base
        with self.assertRaises(ValueError): export(args)


if __name__ == '__main__':
    unittest.main()
