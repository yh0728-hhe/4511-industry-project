"""Render report figures from reviewed local metrics; no API or model calls."""
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/4511-matplotlib-cache')
from pathlib import Path
from datetime import datetime
import hashlib
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'docs/updates/2026-11-19-visual-report'
OUT = REPORT / 'figures'
METRICS = ROOT / 'data/weekly_audit_20261119/report_metrics.json'
INK, MUTED = '#14283f', '#526477'
BLUE, TEAL, AMBER, PALE, ROSE = '#2459a6', '#197c83', '#c98a22', '#e9eef4', '#a95563'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
    'axes.edgecolor': '#ccd5df', 'axes.labelcolor': MUTED, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': INK, 'axes.spines.top': False,
    'axes.spines.right': False, 'axes.spines.left': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'svg.fonttype': 'path'})


def heading(fig, number, title, subtitle):
    fig.text(.04, .955, f'{number:02d}  /  {title}', fontsize=21, weight='bold', va='top')
    fig.text(.04, .892, subtitle, fontsize=11, color=MUTED, va='top')


def footer(fig, text):
    fig.text(.04, .045, text, fontsize=9, color=MUTED, va='bottom', linespacing=1.45)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f'{name}.png', dpi=170)
    fig.savefig(OUT / f'{name}.svg')
    plt.close(fig)


def coverage(m):
    s = m['strict_disclosure']
    fig = plt.figure(figsize=(12, 6.7))
    heading(fig, 1, 'Funding disclosure: a one-company increase',
            'Same strict window: 2024-04-05 to 2026-04-04  |  Fixed cohort: 240 companies')
    ax = fig.add_axes([.23, .31, .69, .48])
    values = [s['baseline_percent'], s['candidate_percent']]
    for y, (v, n, color) in enumerate(zip(values, [102, 103], ['#8ea7c9', BLUE])):
        ax.barh(y, 100, color=PALE, height=.43)
        ax.barh(y, v, color=color, height=.43)
        ax.text(v+1.5, y, f'{n}/240  =  {v:.2f}%', va='center', fontsize=12, weight='bold')
    ax.set_yticks([0, 1], ['Last week\nfrozen baseline', 'This week\nreviewed candidate'])
    ax.invert_yaxis(); ax.set_xlim(0, 100); ax.set_ylim(1.6, -.6)
    ax.set_xticks([0, 25, 50, 75, 100], ['0%', '25%', '50%', '75%', '100%'])
    ax.axvline(90, color=ROSE, linestyle=(0, (4, 3)), linewidth=1.7)
    ax.text(90, -.52, '90% target\n216 companies', ha='center', va='bottom', color=ROSE, fontsize=10)
    ax.grid(axis='x', alpha=.13); ax.set_axisbelow(True)
    fig.text(.23, .19, '+1 company  /  +0.42 percentage points', color=BLUE, fontsize=17, weight='bold')
    fig.text(.23, .13, '113 additional qualifying disclosures would be needed to reach the stated target.', fontsize=11)
    footer(fig, 'Source: baseline and candidate funding CSVs. Baseline 102 carried forward; not fully reverified.\n'
                'The candidate is not a frozen label replacement. PR #3 composite164 uses a different definition/window.')
    save(fig, '01-coverage')


def disposition(m):
    fig = plt.figure(figsize=(12, 7.6))
    heading(fig, 2, 'What the 240 company records actually contain',
            'Evidence status categories are mutually exclusive; unknown is never a financing-negative label.')
    rows = sorted(m['disposition'], key=lambda r: -r['count'])
    ax = fig.add_axes([.35, .19, .55, .63])
    for y, r in enumerate(rows):
        color = BLUE if r['strict_disclosure_established'] else AMBER
        if r['key'] == 'IN_WINDOW_ISSUER_SEC_TRANSACTION_ONLY': color = TEAL
        ax.barh(y, r['count'], height=.58, color=color)
        ax.text(r['count']+1.2, y, f"{r['count']}  ({r['percent']:.2f}%)", va='center', fontsize=11)
    ax.set_yticks(range(len(rows)), [r['label_en'] for r in rows]); ax.invert_yaxis()
    ax.set_xlim(0, 125); ax.set_xticks([0, 25, 50, 75, 100, 125]); ax.set_xlabel('Companies (n = 240)')
    ax.grid(axis='x', alpha=.13); ax.set_axisbelow(True)
    footer(fig, '103 established strict disclosures; 137 without established strict disclosure; 0 verified financing negatives.\n'
                'Source: funding_outcomes_candidate.csv. No returned event means provider absence with an unknown cause.')
    save(fig, '02-disposition')


def evidence_matrix(m):
    fig = plt.figure(figsize=(12, 7.0))
    heading(fig, 3, 'Disclosure and first sale remain separate',
            'Fixed cohort: 240 companies. Evidence overlap, not a success/failure confusion matrix.')
    ax = fig.add_axes([.26, .23, .57, .52]); ax.set_xlim(0, 2); ax.set_ylim(0, 2); ax.axis('off')
    cells = [(0, 1, 11, '#d8ebef', 'Both evidence types'),
             (1, 1, 92, '#dce7f6', 'Disclosure only'),
             (0, 0, 1, '#e7f1f0', 'First-sale only'),
             (1, 0, 136, '#edf0f4', 'Neither established')]
    for x, y, n, color, label in cells:
        ax.add_patch(Rectangle((x+.015, y+.015), .97, .97, facecolor=color, edgecolor='white', lw=2))
        ax.text(x+.5, y+.60, str(n), ha='center', va='center', fontsize=32, weight='bold')
        ax.text(x+.5, y+.25, label, ha='center', fontsize=11)
    ax.text(.5, 2.12, 'SEC first sale\nestablished', ha='center', fontsize=12, color=TEAL)
    ax.text(1.5, 2.12, 'SEC first sale\nnot established', ha='center', fontsize=12, color=MUTED)
    ax.text(-.06, 1.5, 'Disclosure\nestablished', ha='right', va='center', fontsize=12, color=BLUE)
    ax.text(-.06, .5, 'Disclosure\nnot established', ha='right', va='center', fontsize=12)
    fig.text(.26, .135, 'Disclosure total: 103     |     Issuer SEC first-sale total: 12', weight='bold', fontsize=13)
    footer(fig, 'Source: candidate disclosure/transaction flags. "Not established" means missing qualifying evidence, not no funding.\n'
                'No transaction/disclosure union is used to add strict funding positives; 11 companies overlap.')
    save(fig, '03-evidence-matrix')


def round_dates(m):
    rows = m['original_13']['company_rows']
    fig = plt.figure(figsize=(13, 8.9))
    heading(fig, 4, '13 original rounds: date precision still unresolved',
            '12 provider dates have unreported precision; 1 has a visible day. No original announcement date was recovered.')
    ax = fig.add_axes([.18, .22, .77, .59])
    d = lambda s: mdates.date2num(datetime.fromisoformat(s))
    cutoff = d('2026-04-04')
    ax.axvspan(d('2025-12-20'), cutoff, color=TEAL, alpha=.055)
    ax.axvline(cutoff, color=ROSE, linewidth=1.6, linestyle='--')
    for i, row in enumerate(rows):
        start, end, display = map(d, [row['interval_start'], row['interval_end'], row['displayed_date']])
        if row['precision'] == 'UNREPORTED':
            ax.plot([start, end], [i, i], color=AMBER, linewidth=6, alpha=.32, solid_capstyle='butt')
            ax.scatter(display, i, color=AMBER, marker='D', s=26, zorder=3)
        else:
            ax.scatter(display, i, edgecolor=TEAL, facecolor='white', marker='o', s=65, lw=1.8, zorder=3)
        ax.text(d('2026-12-27'), i-.12, 'displayed: '+row['displayed_date'], ha='right', va='center', fontsize=9, color=MUTED)
    ax.set_yticks(range(len(rows)), [r['name'] for r in rows]); ax.invert_yaxis()
    ax.set_xlim(d('2025-12-20'), d('2027-01-04'))
    ax.set_xticks(list(map(d, ['2026-01-01', '2026-04-04', '2026-07-01', '2026-10-01', '2026-12-31'])),
                  ['Jan 1', 'Apr 4\nwindow end', 'Jul 1', 'Oct 1', 'Dec 31'])
    ax.grid(axis='x', alpha=.12); ax.set_axisbelow(True)
    fig.text(.18, .135, 'Amber span = conservative uncertainty envelope, not a measured transaction period.', fontsize=11, color='#885a14')
    footer(fig, 'Source: original_13_date_audit.csv. Diamonds mark displayed dates; the open circle is a provider day display only.\n'
                'TrueClaim separately has a 2024-06-12 investor disclosure; it is not matched to its ambiguous 2026 round.')
    save(fig, '04-round-date-precision')


def boundaries(m):
    b = m['boundary_review']; a = b['displayed_date_screen']; u = b['uncertainty_expanded_screen']
    fig = plt.figure(figsize=(12, 6.8))
    heading(fig, 5, 'Date uncertainty adds 29 companies to review',
            'Nested manual-review queues around the strict window boundaries; three calendar months on either side.')
    ax = fig.add_axes([.27, .35, .64, .40])
    ax.barh(1, 240, color=PALE, height=.40); ax.barh(0, 240, color=PALE, height=.40)
    ax.barh(1, a['companies'], color=BLUE, height=.40)
    ax.barh(0, a['companies'], color=BLUE, height=.40)
    ax.barh(0, 29, left=a['companies'], color=AMBER, height=.40)
    ax.text(27.5, 1, '55', color='white', ha='center', va='center', weight='bold', fontsize=15)
    ax.text(27.5, 0, '55', color='white', ha='center', va='center', weight='bold', fontsize=15)
    ax.text(69.5, 0, '+29', color='white', ha='center', va='center', weight='bold', fontsize=13)
    ax.text(88, 1, '55 companies / 60 evidence rows', va='center', fontsize=11)
    ax.text(88, 0, '84 companies / 102 evidence rows', va='center', fontsize=11)
    ax.set_yticks([1, 0], ['Displayed date\nscreen only', 'Precision-aware\nconservative screen'])
    ax.set_xlim(0, 240); ax.set_xticks([0, 60, 120, 180, 240]); ax.set_xlabel('Companies in fixed cohort (n = 240)')
    ax.set_ylim(-.65, 1.6); ax.grid(axis='x', alpha=.13); ax.set_axisbelow(True)
    fig.text(.27, .22, 'Start band: 2024-01-05 to 2024-07-05\nEnd band:   2026-01-04 to 2026-07-04', fontsize=11, color=MUTED, linespacing=1.6)
    footer(fig, 'Source: boundary_cases.csv; company IDs deduplicated. Source precision is never inferred from an ISO date string.\n'
                'These are review queues, not measured lag, new funding events or automatic positive admissions.')
    save(fig, '05-boundary-review')


def workflow():
    fig = plt.figure(figsize=(13, 6.5))
    heading(fig, 6, 'What is now wired in the research backend',
            'Bounded historical company-site navigation; general news and peer discovery remain incomplete.')
    ax = fig.add_axes([.035, .18, .93, .60]); ax.set_xlim(0, 12); ax.set_ylim(0, 4.5); ax.axis('off')
    positions = [(0, 2.8, 'Historical seed\ncutoff + mandate'), (3.1, 2.8, 'Lead selects\nresearch question'),
                 (6.2, 2.8, 'Archive bootstrap\nCDX + raw replay'), (9.3, 2.8, 'Temporal / identity\ngateway admission'),
                 (9.3, .45, 'Model selects only\nobserved old link'), (6.2, .45, 'Retrieve target\nverify + admit'),
                 (3.1, .45, 'Committee +\nevidence review'), (0, .45, 'Decision or\nMORE_DILIGENCE')]
    w, h = 2.55, 1.0
    for i, (x, y, label) in enumerate(positions):
        color = '#dce7f6' if i in (4, 5) else '#eef2f6'
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=.04,rounding_size=.09',
                                  edgecolor=BLUE if i in (4, 5) else '#c8d3df', facecolor=color, linewidth=1.2))
        ax.text(x+w/2, y+h/2, label, ha='center', va='center', fontsize=11)
    for p, q in [((2.6, 3.3), (3.04, 3.3)), ((5.7, 3.3), (6.14, 3.3)),
                 ((8.8, 3.3), (9.24, 3.3)), ((10.57, 2.73), (10.57, 1.51)),
                 ((9.24, .95), (8.8, .95)), ((6.14, .95), (5.7, .95)), ((3.04, .95), (2.6, .95))]:
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=14, color=MUTED))
    ax.annotate('', xy=(10.5, .35), xytext=(7.5, .35),
                arrowprops={'arrowstyle': '->', 'connectionstyle': 'arc3,rad=.4', 'color': BLUE, 'lw': 1.3})
    ax.text(8.8, -.02, 'Repeat within step / call caps', ha='center', color=BLUE, fontsize=10)
    ax.text(5.9, 2.0, 'One shared model / HTTP / deadline budget\nRejected or future source content stays out of model context',
            ha='center', va='center', fontsize=12, color=TEAL, linespacing=1.5)
    footer(fig, 'Source: research_backend.py, weekly_smoke.py and offline integration tests. Navigation model output is never a fact.\n'
                'No current-web fallback or outcome-file input; historical domain ownership and model-memory leakage remain unproven.')
    save(fig, '06-research-workflow')


def validation(m):
    v = m['validation']
    fig = plt.figure(figsize=(12, 6.9))
    heading(fig, 7, '142 offline tests: 38 checks added this week',
            'Test coverage of wiring, metering and admission rules; not a model-quality or investment-accuracy score.')
    ax = fig.add_axes([.10, .57, .82, .23])
    ax.barh(0, 104, color='#8ea7c9', height=.42)
    ax.barh(0, 38, left=104, color=BLUE, height=.42)
    ax.text(52, 0, '104 inherited tests', ha='center', va='center', color='white', fontsize=14, weight='bold')
    ax.text(123, 0, '+38', ha='center', va='center', color='white', fontsize=14, weight='bold')
    ax.text(144, 0, '142', va='center', fontsize=16, weight='bold', color=BLUE)
    ax.set_xlim(0, 155); ax.set_yticks([]); ax.set_xticks([0, 50, 100, 142]); ax.set_xlabel('Offline test cases')
    lines = [('Historical navigation backend', 15), ('Separate smoke-plan safeguards', 14),
             ('Date precision / evidence dimensions', 8), ('Navigation prompt cache invalidation', 1)]
    for i, (label, n) in enumerate(lines):
        y = .46-i*.071
        fig.text(.12, y, label, fontsize=12)
        fig.text(.79, y, str(n), fontsize=14, color=BLUE, weight='bold', ha='right')
    footer(fig, 'Sources: test module definitions and saved validation record. Current macOS: 142 passed, 0 failures, 0 skips.\n'
                'Prior Windows run had 103 pass / 1 skip; environments differ. New paid model requests: 0 (user deferred).')
    save(fig, '07-offline-validation')


def main():
    m = json.loads(METRICS.read_text())
    assert sum(r['count'] for r in m['disposition']) == m['cohort'] == 240
    assert sum(r['count'] for r in m['evidence_dimensions']['cells']) == 240
    assert m['boundary_review']['uncertainty_only_additional_companies'] == 29
    for f in (coverage, disposition, evidence_matrix, round_dates, boundaries, validation): f(m)
    workflow()
    figures = [dict(path=str(p.relative_to(ROOT)), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
               for p in sorted(OUT.glob('*')) if p.suffix in ('.png', '.svg')]
    (REPORT / 'figure_manifest.json').write_text(json.dumps(dict(
        report_date='2026-11-19', generator='scripts/build_weekly_charts.py',
        metrics_path=str(METRICS.relative_to(ROOT)), metrics_sha256=hashlib.sha256(METRICS.read_bytes()).hexdigest(),
        figures=figures, statement='All figures use reviewed local metrics; no API/model calls.'), indent=2)+'\n')
    print(json.dumps({'figures': len(figures), 'chart_types': 7, 'api_calls': 0}))


if __name__ == '__main__': main()
