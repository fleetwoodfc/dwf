"""# frappe_dwf/tests/test_hl7.py
import frappe
import unittest
from types import SimpleNamespace

# sample HL7 v2.5.1 ORM^O01
SAMPLE_HL7 = (
    "MSH|^\\&|SendingApp|SendingFac|ReceivingApp|ReceivingFac|202511121130||ORM^O01|MSG00001|P|2.5.1\r"
    "PID|1||123456^^^Hospital^MR||Doe^John||19800101|M\r"
    "PV1|1|I|W^389^1^A||||1234^Physician^Primary|||||||||||\r"
    "ORC|NW|ORD448||OC456|CM||||202511121130|||1234^Clinician\r"
    "OBR|1|ORD448||TEST^Test Order^L|||||||||||||||||1234^Clinician\r"
    "NTE|1||Sample order note"
)

class TestHL7Parsing(unittest.TestCase):
    def test_hl7_parser_unit(self):
        """Unit test: normalize_hl7_v2 returns expected fields"""
        from frappe_dwf.api import normalize_hl7_v2
        parsed = normalize_hl7_v2(SAMPLE_HL7)
        # basic assertions
        self.assertIn("message_id", parsed)
        self.assertIn("message_type", parsed)
        self.assertEqual(parsed.get("message_id"), "MSG00001")
        # Message type could be 'ORM^O01' or similar
        self.assertTrue(parsed.get("message_type").startswith("ORM"))
        # correlation id should map to ORC-2 (ORD448)
        self.assertEqual(parsed.get("correlation_id"), "ORD448")
        # source & destination not None
        self.assertIsNotNone(parsed.get("source_actor"))
        self.assertIsNotNone(parsed.get("destination_actor"))

    def test_integration_post_message(self):
        """Integration-style test: simulate POST and assert Message doc saved"""
        from frappe_dwf.api import ihe_receive_message
        # simulate request in frappe.local
        sample = SAMPLE_HL7
        # create a minimal request-like object with get_data and headers
        req = SimpleNamespace()
        req.get_data = lambda as_text=True: sample
        req.headers = {"Content-Type": "text/plain"}
        # stash any existing frappe.local.request
        old_request = getattr(frappe.local, "request", None)
        frappe.local.request = req

        # ensure no preexisting message
        frappe.db.sql("DELETE FROM `tabMessage` WHERE message_id=%s", ("MSG00001",))
        frappe.db.commit()

        try:
            resp = ihe_receive_message()
            # response should indicate creation
            self.assertIn("data", resp)
            data = resp.get("data", {})
            self.assertEqual(data.get("message_id"), "MSG00001")

            # verify Message exists in DB
            exists = frappe.db.get_all("Message", filters={"message_id": "MSG00001"}, fields=["name", "status"])
            self.assertTrue(len(exists) == 1)

        finally:
            # cleanup
            frappe.db.sql("DELETE FROM `tabMessage` WHERE message_id=%s", ("MSG00001",))
            frappe.db.commit()
            # restore old request
            frappe.local.request = old_request

if __name__ == "__main__":
    unittest.main()
"""