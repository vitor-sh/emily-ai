import unittest
from compare_vosk import evaluate

def word(text,start,end,confidence=1.):
    return dict(word=text,start=start,end=end,conf=confidence)

class VoskComparisonTests(unittest.TestCase):
    def test_accepts_only_complete_initial_call(self):
        call=[word('hey',.32,.50),word('emily',.51,.90)]
        self.assertEqual(evaluate(call),'accepted')
        self.assertEqual(evaluate(call[1:]),'missing_prefix')
        self.assertEqual(evaluate([word('[unk]',0,.2)]+call),'missing_prefix')
        self.assertEqual(evaluate(call+[word('[unk]',1,1.1),word('[unk]',1.2,1.3)]),'too_many_words')
    def test_confidence_and_timing_boundaries(self):
        self.assertEqual(evaluate([word('hey',.32,.50,.84),word('emily',.51,.9)]),'low_confidence')
        self.assertEqual(evaluate([word('hey',.32,.50),word('emily',1.1,1.5)]),'separated_call')
        self.assertEqual(evaluate([word('hey',.32,.50),word('emily',.51,.70)]),'too_short')
        self.assertEqual(evaluate([word('hey',.32,.50),word('emily',.51,.9,float('nan'))]),'invalid_timing')

if __name__=='__main__':unittest.main()
