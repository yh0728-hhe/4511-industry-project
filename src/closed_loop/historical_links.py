"""Discover source paths from verified historical HTML, without reading targets."""
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin,urlparse,urlunparse,parse_qsl


@dataclass(frozen=True)
class HistoricalLink:
    subject_id: str
    url: str
    path: str
    label: str
    observed_at: datetime
    found_in_source_id: str
    target_content_verified: bool = False


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[];self.current=None;self.label=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.current=dict(attrs).get('href');self.label=[]
    def handle_data(self,data):
        if self.current is not None:self.label.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:
            if len(self.links)<1000:self.links.append((self.current,' '.join(self.label)))
            self.current=None;self.label=[]


def discover_links(raw,original_url,subject_id,company_domain,observed_at,source_id):
    parser=LinkParser();parser.feed(raw.decode('utf-8',errors='strict'))
    base=company_domain.removeprefix('www.').lower();found={}
    for href,label in parser.links:
        if not isinstance(href,str) or len(href)>1024:continue
        try:
            parsed=urlparse(urljoin(original_url,href))
            host=(parsed.hostname or '').lower()
            if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.port not in (None,80,443):continue
            if host.removeprefix('www.')!=base:continue # other origins/subdomains need an explicit identity anchor
            query=parse_qsl(parsed.query,keep_blank_values=True)
            if any(re.search(r'(^|_)(token|password|secret|auth|api_key|key|code)($|_)',key,re.I) for key,_ in query):continue
            path=(parsed.path or '/')+('?' + parsed.query if parsed.query else '')
            if len(path)>512 or any(ord(char)<32 for char in path):continue
            clean=urlunparse((parsed.scheme,parsed.netloc,parsed.path or '/','',parsed.query,''))
            found[path]=HistoricalLink(subject_id,clean,path,' '.join(label.split())[:160],observed_at,source_id)
        except (TypeError,ValueError):continue
    return tuple(found[path] for path in sorted(found))


ROLE_WORDS={
    'team':{'team','about','founder','leadership'},'founder':{'team','about','founder','leadership'},
    'traction':{'customer','case','retention','testimonial','success'},
    'product':{'product','feature','platform','technology','how'},
    'market':{'market','industry','blog','insight','research'},
    'competition':{'comparison','alternative','versus','compare'},
    'regulatory':{'privacy','security','compliance','terms'},
    'unit_economics':{'pricing','price','cost','plans'},
}
STOP_WORDS={'what','which','with','from','that','this','their','there','does','have','about','into','company','specific','existing','current','using','used'}


def rank_links(links,role,question,limit=2):
    question_words={word for word in re.findall(r'[a-z]{3,}',question.lower()) if word not in STOP_WORDS}
    words=question_words|ROLE_WORDS.get(role,set())
    def score(link):
        tokens=set(re.findall(r'[a-z]{3,}',(link.path+' '+link.label).lower()))
        # Prefix matching links price/pricing and customer/customers without
        # assuming those pages contain any requested fact.
        return sum(2 if word in question_words else 1 for word in words
            if any(token==word or (len(word)>=4 and (token.startswith(word[:5]) or word.startswith(token))) for token in tokens))
    return tuple(link for link in sorted(links,key=lambda link:(-score(link),link.path)) if score(link)>0)[:limit]
