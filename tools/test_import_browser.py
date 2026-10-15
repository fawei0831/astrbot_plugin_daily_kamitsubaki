import tempfile
import unittest
from pathlib import Path
from build_catalog import read, write
from import_browser import import_files


class Tests(unittest.TestCase):
    def test_import_deduplicates_without_network_or_formal_changes(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            write(work/'songs.json', [{'id':'song','title':'魔女','artist':'花譜','artists':['kaf'],'bvid':''}])
            file = work/'page.json'
            payload = dict(format='daily-kamitsubaki-browser-v1',mid='488970166',
                source='https://space.bilibili.com/488970166/upload/video', videos=[
                dict(mid='488970166',bvid='BV1234567890',title='【花譜】「魔女」',cover_url='https://i0.hdslb.com/a.jpg')])
            write(file,payload)
            self.assertEqual(import_files([file],work),1)
            self.assertEqual(import_files([file],work),0)
            review=read(work/'review.json')
            self.assertEqual(len(review),1)
            self.assertFalse(review[0]['approved'])
            self.assertFalse((work/'catalog.json').exists())
            payload['videos'][0]['cover_url']='https://evil.example/a.jpg'; write(file,payload)
            before=(work/'videos.json').read_bytes()
            with self.assertRaises(ValueError): import_files([file],work)
            self.assertEqual((work/'videos.json').read_bytes(),before)
            payload['mid']='123'; write(file,payload)
            with self.assertRaises(ValueError): import_files([file],work)


if __name__ == '__main__': unittest.main()
