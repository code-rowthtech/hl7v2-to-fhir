"""Small explicit subset: one patient and one order; not a general HL7 engine."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid5, NAMESPACE_URL
import re
import math
import json


def convert(raw: str) -> dict:
    lines = [line for line in raw.replace("\r\n", "\r").replace("\n", "\r").split("\r") if line]
    if not lines or not lines[0].startswith("MSH|^~\\&|"):
        raise ValueError("Only standard HL7 delimiters are supported")
    segments = [line.split("|") for line in lines]
    def one(tag, required=True):
        rows = [s for s in segments if s[0] == tag]
        if len(rows) > 1 or (required and not rows):
            raise ValueError(f"Expected one {tag} segment")
        return rows[0] if rows else []
    def field(segment, n):
        index = n - 1 if segment and segment[0] == "MSH" else n
        return segment[index] if len(segment) > index else ""
    def decode(value):
        if "~" in value:
            raise ValueError("Repeating fields are outside this converter's subset")
        escapes = {"F": "|", "S": "^", "R": "~", "T": "&", "E": "\\"}
        def replace(match):
            if match[1] not in escapes:
                raise ValueError("Unsupported HL7 escape")
            return escapes[match[1]]
        result = re.sub(r"\\([^\\]+)\\", replace, value)
        if "\\" in result and "\\E\\" not in value:
            raise ValueError("Invalid HL7 escape")
        return result
    msh, pid = one("MSH"), one("PID")
    kind = field(msh, 9).split("^")
    if len(kind) < 2 or tuple(kind[:2]) not in [("ADT", "A01"), ("ADT", "A04"), ("ORU", "R01")]:
        raise ValueError("Supported events: ADT A01/A04 and ORU R01")
    if field(msh, 12) != "2.5.1":
        raise ValueError("Only the documented HL7 2.5.1 subset is supported")
    source = [field(msh, 3).strip(), field(msh, 4).strip()]
    control_id = field(msh, 10).strip()
    if not all(source):
        raise ValueError("MSH-3 sending application and MSH-4 facility are required")
    if not control_id:
        raise ValueError("MSH-10 message control ID is required")
    identifier = field(pid, 3).split("~")[0].split("^")
    mrn = decode(identifier[0])
    if not mrn:
        raise ValueError("PID-3 identifier is required")
    def rid(kind, seed):
        identity = json.dumps([source, kind, seed], sort_keys=True, separators=(",", ":"))
        return str(uuid5(NAMESPACE_URL, identity))
    patient_identity = {"mrn": mrn, "authority": identifier[3] if len(identifier) > 3 else "",
                        "identifier_type": identifier[4] if len(identifier) > 4 else ""}
    patient_id = rid("Patient", patient_identity)
    name = field(pid, 5).split("^")
    patient = {"resourceType": "Patient", "id": patient_id,
               "identifier": [{"system": "https://example.invalid/mrn", "value": mrn}],
               "name": [{"family": decode(name[0]), "given": [decode(v) for v in name[1:3] if v]}]}
    dob = field(pid, 7)
    if dob:
        try:
            if len(dob) != 8: raise ValueError()
            patient["birthDate"] = datetime.strptime(dob, "%Y%m%d").date().isoformat()
        except ValueError as error:
            raise ValueError("PID-7 must be a valid YYYYMMDD date") from error
    patient["gender"] = {"M": "male", "F": "female", "O": "other", "U": "unknown", "": "unknown"}.get(field(pid, 8), "unknown")
    resources = [patient]
    subject = {"reference": f"urn:uuid:{patient_id}"}
    pv1 = one("PV1", kind[0] == "ADT")
    if kind[0] == "ADT":
        visit = field(pv1, 19).split("^")[0]
        if not visit: raise ValueError("PV1-19 visit identifier is required")
        patient_class = {"I": "IMP", "O": "AMB"}.get(field(pv1, 2))
        if not patient_class: raise ValueError("Only inpatient/outpatient classes supported")
        resources.append({"resourceType": "Encounter", "id": rid("Encounter", [patient_id, visit]),
                          "identifier": [{"value": visit}], "status": "in-progress", "subject": subject,
                          "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": patient_class}})
    else:
        obr = one("OBR")
        order_code = field(obr, 4).split("^")
        if not order_code[0]: raise ValueError("OBR-4 order code is required")
        results = []
        statuses = {"F": "final", "P": "preliminary", "C": "corrected"}
        seen = set()
        for obx in [s for s in segments if s[0] == "OBX"]:
            sequence, value_type = field(obx, 1), field(obx, 2)
            if not sequence or sequence in seen: raise ValueError("OBX sequence must be unique")
            seen.add(sequence)
            code = field(obx, 3).split("^")
            if not code[0]: raise ValueError("OBX-3 observation code is required")
            status = statuses.get(field(obx, 11))
            if not status: raise ValueError("Unsupported OBX-11 result status")
            obs_id = rid("Observation", [patient_id, control_id, sequence])
            coding = {"code": code[0]}
            if len(code) > 1: coding["display"] = decode(code[1])
            if len(code) > 2 and code[2] == "LN": coding["system"] = "http://loinc.org"
            obs = {"resourceType": "Observation", "id": obs_id, "status": status,
                   "subject": subject, "code": {"coding": [coding]}}
            value = field(obx, 5)
            if value_type == "NM":
                try:
                    number = Decimal(value)
                    if not number.is_finite() or not math.isfinite(float(number)): raise InvalidOperation()
                except InvalidOperation as error: raise ValueError("Invalid numeric OBX value") from error
                units = field(obx, 6).split("^")
                obs["valueQuantity"] = {"value": float(number), "unit": units[0]}
                if len(units) > 2 and units[2] == "UCUM":
                    obs["valueQuantity"].update({"system": "http://unitsofmeasure.org", "code": units[0]})
            elif value_type == "ST": obs["valueString"] = decode(value)
            else: raise ValueError("Only NM and ST observations supported")
            resources.append(obs); results.append({"reference": f"urn:uuid:{obs_id}"})
        if not results: raise ValueError("ORU message must contain observations")
        resources.append({"resourceType": "DiagnosticReport", "id": rid("DiagnosticReport", [patient_id, control_id]),
                          "status": ("preliminary" if any(o["status"] == "preliminary" for o in resources[1:]) else "corrected" if any(o["status"] == "corrected" for o in resources[1:]) else "final"),
                          "code": {"coding": [{"code": order_code[0]}]}, "subject": subject, "result": results})
    return {"resourceType": "Bundle", "type": "collection", "entry": [
        {"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources]}
