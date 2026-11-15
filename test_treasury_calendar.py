import unittest,json
from treasury_calendar import *
class TestCalendar(unittest.TestCase):
    def test_pdf(self):
        txt='\n'.join(f'13-Week BILL  Thu, Nov 12, 2026  Mon, Nov {d:02}, 2026  Thu, Dec 03, 2026  Thu, Feb 18, 2027' for d in range(12,30))
        rows=parse_pdf_text(txt+'\n'+txt)
        self.assertEqual(rows[0]['date'],'2026-11-12');self.assertEqual(rows[0]['maturity'],'2027-02-18')
    def test_qra(self):
        h='<h3>DOCUMENTS RELEASED at 3:00 PM Monday, November 2, 2026</h3><a>Financing Estimates: 2026</a><p>(The next release is scheduled for February 1, 2027)</p><h3>DOCUMENTS RELEASED at 8:30 AM Wednesday, November 4, 2026</h3><a>Policy Statement: 2026</a><p>(The next release is scheduled for February 3, 2027)</p>'
        r=parse_qra(h);self.assertEqual(r[-1]['date'],'2027-02-03');self.assertEqual(r[-1]['clock'],'08:30')
    def test_merge(self):
        s=dict(date='2026-11-16',label='13-Week Bill',issue='2026-11-19',maturity='2027-02-18',clock=None,source=PDF)
        actual=actual_rows([dict(auction_date='2026-11-16',issue_date='2026-11-19',maturity_date='2027-02-18',security_type='Bill',security_term='52-Week',closing_time_comp='11:30 AM',cusip='912797TV9')])
        r=merge([s],actual,[],'2026-11-15');self.assertEqual(len(r),1);self.assertEqual(r[0]['clock'],'11:30');self.assertEqual(r[0]['label'],'13-Week Bill')
    def test_utc(self):
        r=[dict(date='2026-11-18',label='20-Year Bond',clock='13:00',source=ANN),dict(date='2027-06-01',label='Test',clock='13:00',source=ANN),dict(date='2027-06-02',label='No time',clock=None,source=PDF)]
        b=render(r,'20261115T000000Z');self.assertIn(b'DTSTART:20261118T180000Z',b);self.assertIn(b'DTSTART:20270601T170000Z',b);self.assertIn(b'DTSTART;VALUE=DATE:20270602',b)
    def test_seed(self):
        s=json.loads(SNAP.read_text());b=render(s['events'],s['stamp']);self.assertEqual(b.count(b'BEGIN:VEVENT'),len(s['events']));self.assertEqual(b.count(b'END:VEVENT'),len(s['events']));self.assertTrue(all(len(l)<=75 for l in b.split(b'\r\n')))
if __name__=='__main__':unittest.main()
