import unittest
from analyze_wake_context import accepted_segment, analyze, is_current_call, full_confirmation


def segment(word='emily', conf=1., start=.2, end=.6):
    return dict(text=word,result=[dict(word=word,conf=conf,start=start,end=end)])


class WakeContextTest(unittest.TestCase):
    def test_old_name_only_label_now_counts_as_call(self):
        self.assertTrue(is_current_call(dict(positive=False,text='Emily.')))
        self.assertFalse(is_current_call(dict(positive=False,text='Ei, Emília.')))

    def test_matches_name_only_and_optional_prefix(self):
        self.assertTrue(accepted_segment(segment()))
        words=segment('hey',start=0.,end=.15)['result']+segment()['result']
        self.assertTrue(accepted_segment(dict(result=words)))
        self.assertFalse(accepted_segment(dict(result=words+segment('[unk]')['result'])))

    def test_requires_real_whole_words_confidence_duration_and_timing(self):
        for s in (segment('family'),segment(conf=.69),segment(end=.27),segment(start=float('nan'))):
            self.assertFalse(accepted_segment(s))
        self.assertFalse(accepted_segment(dict(result=segment('hey',start=0.,end=.1)['result']+segment(start=1.,end=1.4)['result'])))

    def test_confirmation_agrees_on_time_not_name_elsewhere(self):
        self.assertTrue(full_confirmation(segment(),[segment()]))
        self.assertFalse(full_confirmation(segment(),[segment('really')]))
        self.assertFalse(full_confirmation(segment(),[segment(start=3.,end=3.4)]))

    def test_report_exposes_lost_personal_call(self):
        a=dict(path='private',group='private',kind='fast',text='Ei Emily',positive=True,segments=[segment()])
        b=dict(a,full=[segment('family')])
        report=analyze([a],[b])
        self.assertEqual(1,report['summary']['calls']['baseline_accepted'])
        self.assertEqual(0,report['summary']['calls']['confirmed_accepted'])
        self.assertEqual('fast',report['lost_calls'][0]['kind'])

    def test_mismatched_inputs_cannot_produce_comparison(self):
        a=dict(path='a',group='x',text='Emily.',segments=[segment()],positive=False)
        with self.assertRaises(ValueError):analyze([a],[dict(a,path='b',full=[segment()])])
        with self.assertRaises(ValueError):analyze([a],[])

if __name__=='__main__':unittest.main()
