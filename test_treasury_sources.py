import unittest
from unittest.mock import patch
import json
from datetime import date,timedelta
import treasury_calendar as t

TODAY='2026-11-15'

def record(i=0,**changes):
    d=date(2026,11,14)-timedelta(days=i)
    r=dict(cusip=f'9127{i:05d}',type='Bill',securityType='Bill',securityTerm='13-Week',originalSecurityTerm='13-Week',competitiveAuctionCloseDate=d.isoformat()+'T00:00:00',issueDate=(d+timedelta(days=3)).isoformat()+'T00:00:00',maturityDate=(d+timedelta(days=94)).isoformat()+'T00:00:00',competitiveAuctionCloseTime='11:30 AM',offeringAmount='70000000000',inflationProtected='No',cashManagementBill='No',floatingRate='No')
    r.update(changes);return r

class TestSources(unittest.TestCase):
    def test_new_schema(self):
        r=t.actual_rows([t.td_normalize(record())])[0]
        self.assertEqual((r['clock'],r['label'],r['amount']),('11:30','13-Week Bill','70000000000'))
    def test_old_schema(self):
        r=record();r['auctionDate']=r.pop('competitiveAuctionCloseDate');r['closingTimeCompetitive']=r.pop('competitiveAuctionCloseTime');r.pop('type')
        self.assertEqual(t.actual_rows([t.td_normalize(r)])[0]['clock'],'11:30')
    def test_reopening(self):
        r=record(type='Note',securityType='Note',securityTerm='9-Year 10-Month',originalSecurityTerm='10-Year',competitiveAuctionCloseTime='01:00 PM',maturityDate='2036-08-15')
        self.assertEqual(t.actual_rows([t.td_normalize(r)])[0]['label'],'10-Year Note')
    def test_type_flags(self):
        for kind,base,expected in [('TIPS','Note','TIPS'),('FRN','Note','FRN'),('CMB','Bill','Cash Management Bill')]:
            r=t.actual_rows([t.td_normalize(record(type=kind,securityType=base))])[0]
            self.assertIn(expected.lower(),r['label'].lower())
    def test_missing_time_field(self):
        r=record();r.pop('competitiveAuctionCloseTime')
        with self.assertRaises(ValueError): t.td_normalize(r)
    def test_empty_time_tbd(self):
        self.assertIsNone(t.actual_rows([t.td_normalize(record(competitiveAuctionCloseTime=''))])[0]['clock'])
    def test_primary_query(self):
        data=[record(i) for i in range(12)]
        with patch.object(t,'fetch',return_value=json.dumps(data).encode()) as f:
            rows=t.fetch_treasury_direct(TODAY)
        self.assertEqual(len(rows),12);self.assertIn('startDate=2026-10-16',f.call_args.args[0]);self.assertIn('endDate=2027-01-14',f.call_args.args[0])
    def test_primary_success(self):
        with patch.object(t,'fetch_treasury_direct',return_value=[{}]),patch.object(t,'fetch_fiscal_data') as secondary:
            self.assertEqual(t.fetch_actual(TODAY),[{}]);secondary.assert_not_called()
    def test_fallback(self):
        with patch.object(t,'fetch_treasury_direct',side_effect=TimeoutError('timeout')),patch.object(t,'fetch_fiscal_data',return_value=[{}]):
            self.assertEqual(t.fetch_actual(TODAY),[{}])
    def test_both_fail(self):
        with patch.object(t,'fetch_treasury_direct',side_effect=TimeoutError()),patch.object(t,'fetch_fiscal_data',side_effect=TimeoutError()):
            with self.assertRaisesRegex(RuntimeError,'Both official auction sources failed'): t.fetch_actual(TODAY)
    def test_incomplete_rejected(self):
        rows=t.actual_rows([t.td_normalize(record(i)) for i in range(12)])
        old=[dict(rows[0],cusip='999999999')]
        with self.assertRaisesRegex(ValueError,'missing previously confirmed'):t.validate_actual(rows,TODAY,old)
    def test_duplicate_rejected(self):
        rows=t.actual_rows([t.td_normalize(record(i)) for i in range(12)])
        with self.assertRaisesRegex(ValueError,'duplicate'):t.validate_actual(rows+[rows[0]],TODAY)
    def test_stale_rejected(self):
        rows=t.actual_rows([t.td_normalize(record(i)) for i in range(9,21)])
        with self.assertRaisesRegex(ValueError,'stale'):t.validate_actual(rows,TODAY)
    def test_known_time_loss_rejected(self):
        rows=t.actual_rows([t.td_normalize(record(i)) for i in range(12)])
        old=[rows[0].copy()];rows[0]['clock']=None
        with self.assertRaisesRegex(ValueError,'lost a previously confirmed'):t.validate_actual(rows,TODAY,old)
    def test_fallback_failure_does_not_write(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            snap=Path(td)/'dates.json';out=Path(td)/'treasury.ics'
            snap.write_text('{"events":[],"stamp":"old"}');out.write_text('old calendar')
            before=snap.read_bytes()
            with patch.object(t,'SNAP',snap),patch.object(t,'OUTPUT',out),patch.object(t,'fetch',return_value=b'PDF'),patch.object(t.subprocess,'check_output',return_value=b'fake text'),patch.object(t,'parse_pdf_text',return_value=[{'date':'2099-01-01'}]),patch.object(t,'fetch_actual',side_effect=RuntimeError('Both failed')),patch('sys.argv',['treasury_calendar.py']):
                with self.assertRaises(RuntimeError):t.main()
            self.assertEqual(snap.read_bytes(),before);self.assertEqual(out.read_text(),'old calendar')

if __name__=='__main__':unittest.main()
