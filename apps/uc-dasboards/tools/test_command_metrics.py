import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from command_metrics import prepare, summarize

cfg = json.loads((ROOT / 'config/command_centers.json').read_text())['invoice_command']
df = pd.DataFrame({
    'id': [1, 2, 3, 4, 5, 6, 7, 8],
    'latest_invoice_timestamp': ['2026-09-14 02:00'] * 8,
    'refresh_time': ['2026-09-15 08:30'] * 8,
    'invoice_tat': [100, 200, 300, 400, 0, 600, 700, 50],
    'lender': ['MFL', 'HCPL', 'HCPL', 'HCPL', 'HCPL', 'MFL', 'HCPL', 'HCPL'],
    'risky_customer': [1, 1, 0, 0, 0, 0, 1, 0],
    'invoice_amount_tag': ['5L+', '5L+', '5L+', 'Below 5L', 'Below 5L', 'Below 5L', 'Below 5L', 'Below 5L'],
})
frame = prepare(df, cfg)
assert len(frame) == 8
assert frame['invoice_tat'].tolist() == [100, 200, 300, 400, 0, 600, 700, 50]
result = summarize(frame, cfg)
assert result['total'] == 8
assert abs(result['rate_pct'] - 50) < 1e-8
assert result['stages'] == [2, 2, 1]
assert result['eligible'] == 3
assert abs(result['eligible_pct'] - 37.5) < 1e-8
assert result['stage_tats'] == [550, 650, 300]
assert result['eligible_tat'] == 330
assert result['balance_tat'] == 660
assert result['total_tat'] == 630
assert abs(result['overall'] - 2350/8) < 1e-8
assert summarize(frame.iloc[:0], cfg)['rate_pct'] is None
print('PASS: latest_invoice_timestamp, direct invoice_tat seconds, sequential exclusions, counts and cohort P90 values')
