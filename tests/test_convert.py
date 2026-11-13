import unittest
from pathlib import Path
from src.convert import convert

class MappingTests(unittest.TestCase):
    def setUp(self): self.raw = Path('sample-data/result.hl7').read_text()
    def test_numeric_observation_and_resolved_references(self):
        bundle=convert(self.raw); entries=bundle['entry']; urls={e['fullUrl'] for e in entries}
        observation=next(e['resource'] for e in entries if e['resource']['resourceType']=='Observation')
        self.assertEqual(observation['valueQuantity']['value'],72)
        self.assertIn(observation['subject']['reference'],urls)
        report=entries[-1]['resource']; self.assertEqual(report['status'],'final')
        self.assertIn(report['result'][0]['reference'],urls)
    def test_registration_builds_encounter(self):
        resources=[e['resource'] for e in convert(Path('sample-data/registration.hl7').read_text())['entry']]
        self.assertEqual(resources[0]['birthDate'],'2000-01-01')
        self.assertEqual(resources[1]['class']['code'],'AMB')
    def test_rejects_missing_identifier(self):
        with self.assertRaises(ValueError): convert(self.raw.replace('SYNTHETIC-PATIENT-001',''))
    def test_rejects_nan(self):
        with self.assertRaises(ValueError): convert(self.raw.replace('||72|','||NaN|'))
    def test_rejects_invalid_calendar_date(self):
        with self.assertRaises(ValueError): convert(self.raw.replace('20000101','20000230'))
    def test_rejects_unsupported_event(self):
        with self.assertRaises(ValueError): convert(self.raw.replace('ORU^R01','ORM^O01'))
    def test_rejects_ambiguous_multiple_orders(self):
        with self.assertRaises(ValueError): convert(self.raw+'\rOBR|2|||another')
    def test_preserves_preliminary_status(self):
        self.assertEqual(convert(self.raw.replace('|||||F','|||||P'))['entry'][-1]['resource']['status'],'preliminary')
    def test_corrected_observation_is_not_downgraded_to_preliminary(self):
        self.assertEqual(convert(self.raw.replace('|||||F','|||||C'))['entry'][-1]['resource']['status'],'corrected')
    def test_numeric_overflow_rejected(self):
        with self.assertRaises(ValueError): convert(self.raw.replace('||72|','||1e500|'))

    def test_result_ids_are_scoped_to_patient(self):
        first=convert(self.raw)
        second=convert(self.raw.replace('SYNTHETIC-PATIENT-001','SYNTHETIC-PATIENT-002'))
        ids=lambda bundle:{e['resource']['id'] for e in bundle['entry'] if e['resource']['resourceType'] in ['Observation','DiagnosticReport']}
        self.assertFalse(ids(first)&ids(second))
        self.assertEqual(first,convert(self.raw))
    def test_patient_ids_are_scoped_to_sending_facility(self):
        first=convert(self.raw)['entry'][0]['resource']['id']
        second=convert(self.raw.replace('|SYNTHETIC|LAB|','|SYNTHETIC|OTHER-FACILITY|'))['entry'][0]['resource']['id']
        self.assertNotEqual(first,second)
    def test_assigning_authority_is_part_of_patient_identity(self):
        first=self.raw.replace('SYNTHETIC-PATIENT-001^^^LOCAL^MR','SYNTHETIC-PATIENT-001^^^AUTHORITY-A^MR')
        second=self.raw.replace('SYNTHETIC-PATIENT-001^^^LOCAL^MR','SYNTHETIC-PATIENT-001^^^AUTHORITY-B^MR')
        self.assertNotEqual(convert(first)['entry'][0]['resource']['id'],convert(second)['entry'][0]['resource']['id'])
    def test_missing_message_control_id_is_rejected(self):
        with self.assertRaises(ValueError):convert(self.raw.replace('SYNTHETIC-MSG-002',''))
    def test_missing_sending_facility_is_rejected(self):
        with self.assertRaises(ValueError):convert(self.raw.replace('|SYNTHETIC|LAB|','|SYNTHETIC||'))
