from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import stamp
from closed_loop.historical_links import discover_links,rank_links


class LinkTests(unittest.TestCase):
    def test_only_safe_same_company_links_are_observations_not_target_proofs(self):
        raw=b'''<html><a href="/pricing">Pricing plans</a><a href="/team">Our team</a>
        <a href="https://other.example/news">Other company</a><a href="javascript:bad()">bad</a>
        <a href="/login?access_token=SECRET">secret</a><a href="mailto:person@example.com">mail</a>
        <a href="/pricing#faq">Pricing FAQ</a></html>'''
        links=discover_links(raw,'https://synthetic.example/','S','synthetic.example',stamp('2024-03-20T00:00:00Z'),'source-id')
        self.assertEqual({x.path for x in links},{'/pricing','/team'})
        self.assertTrue(all(x.target_content_verified is False for x in links))
        self.assertTrue(all(x.found_in_source_id=='source-id' for x in links))

    def test_question_changes_which_historical_path_ranks_first(self):
        links=discover_links(b'<a href="/pricing">Pricing plans</a><a href="/team">Founders and team</a>',
            'https://synthetic.example/','S','synthetic.example',stamp('2024-03-20T00:00:00Z'),'source-id')
        self.assertEqual(rank_links(links,'product','What is the pricing model?',1)[0].path,'/pricing')
        self.assertEqual(rank_links(links,'founder','Who founded it?',1)[0].path,'/team')

    def test_unrelated_question_does_not_turn_arbitrary_links_into_sources(self):
        links=discover_links(b'<a href="/terms">Terms</a>','https://synthetic.example/','S','synthetic.example',
            stamp('2024-03-20T00:00:00Z'),'source-id')
        self.assertEqual(rank_links(links,'market','industry demand estimates'),())


if __name__=='__main__':unittest.main()
